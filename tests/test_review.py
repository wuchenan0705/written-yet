from datetime import datetime

import pytest
from sqlmodel import select

from app import review
from app.grader import SYSTEM_PROMPT, GradingError
from app.models import BLANK, CORRECT, UNGRADED, WRONG, Answer, Submission
from tests.fakes import explainer, q

NOW = datetime(2026, 10, 21, 10)
BOX = [("A", "people may think the restaurant is overpriced"), ("B", "people would come back again"),
       ("C", "people would spend more money"), ("F", "people would likely make complaints")]


def make_sub(session, skill="listening"):
    sub = Submission(created_at=NOW, date="2026-10-21", skill=skill, source="web", raw_text="passage",
                     result={"summary": ""})
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


def build(session, questions, first=0, last=0, overrides=None):
    sub = make_sub(session)
    review.build_answers(session, sub, questions, {"first": first, "last": last}, overrides or {}, NOW)
    session.flush()
    review.recount(session, sub)
    session.commit()
    return sub, {a.question_no: a for a in review.answers_of(session, sub.id)}


def assert_consistent(session, sub):
    rows = review.answers_of(session, sub.id)
    assert len({a.question_no for a in rows}) == len(rows)
    assert sub.question_count == sum(a.status != UNGRADED for a in rows)
    assert sub.correct_count == sum(a.status == CORRECT for a in rows)


def test_prompt_asks_for_transcription_not_verdicts():
    assert "照抄學生寫的" in SYSTEM_PROMPT and "不要漏題" in SYSTEM_PROMPT
    assert "你不用判斷" in SYSTEM_PROMPT and "依出現順序補 A、B、C" in SYSTEM_PROMPT


def test_build_judges_in_code_not_by_claude(session):
    sub, rows = build(session, [
        q("1", user="craswick", key="Creswick", error_type="詞彙不認識"),
        q("6", user="june 13", key="13th June/June 13th"),
        q("27", "matching", user="C", key="C", options=BOX),
        q("28", "matching", user="F people would likely make complaints", key="A", options=BOX),
        q("37", "tfng", user="NG", key="NOT GIVEN"),
        q("38", "tfng", user="", key="FALSE", error_type="定位錯誤"),
        q("39", "choice", visible=False, key="B", explanation="（教練判斷）…"),
        q("27", user="duplicate"),
    ])
    assert [(n, a.status) for n, a in rows.items()] == [
        ("1", WRONG), ("6", CORRECT), ("27", CORRECT), ("28", WRONG), ("37", CORRECT), ("38", BLANK), ("39", UNGRADED)]
    assert rows["1"].error_type == "拼字錯誤"  # read off the strings, beats Claude's guess
    assert rows["38"].error_type == "未作答"  # blank answers are always 未作答
    assert rows["28"].user_answer == "F" and rows["28"].show("F") == "F people would likely make complaints"
    assert rows["28"].key_text == "A people may think the restaurant is overpriced"
    assert (sub.question_count, sub.correct_count) == (6, 3)
    assert_consistent(session, sub)


def test_build_fills_gaps_in_range_and_applies_typed_answers(session):
    sub, rows = build(session, [q("1", user="x", key="x"), q("3", "choice", visible=False, key="B"),
                                q("4", user="y", key="y")],
                      first=1, last=4, overrides={"3": "b"})
    assert rows["2"].status == UNGRADED  # Claude skipped Q2
    assert rows["3"].status == CORRECT and rows["3"].user_answer == "B"
    assert (sub.question_count, sub.correct_count) == (3, 3)


def test_build_ignores_a_range_that_does_not_fit(session):
    _, rows = build(session, [q("21", user="x", key="x"), q("22", user="x", key="x")], first=1, last=40)
    assert list(rows) == ["21", "22"]


def test_build_choose_two(session):
    sub, rows = build(session, [q("25", "multi", user="E", key="A/E", group="25-26"),
                                q("26", "multi", user="E", key="A/E", group="25-26")])
    assert (rows["25"].status, rows["26"].status) == (CORRECT, WRONG)
    _, rows = build(session, [q("25-26", "multi", user="A, D", key="A, E")])
    assert (rows["25"].status, rows["26"].status, rows["25"].group_nos) == (CORRECT, WRONG, "25-26")


def test_mark_correct_and_wrong_round_trip(session):
    sub, rows = build(session, [q("9", user="online", key="internet"), q("10", user="leaflet", key="leaflet")])
    review.mark_correct(session, rows["9"])
    assert rows["9"].status == CORRECT and rows["9"].accepted == ["internet", "online"]
    assert sub.correct_count == 2 and sub.result["edited"] is True
    review.mark_wrong(session, rows["10"], "email", "")
    assert rows["10"].status == WRONG and rows["10"].error_type == "其他"
    review.mark_wrong(session, rows["9"], "", "細節漏看")
    assert rows["9"].status == BLANK and rows["9"].error_type == "未作答"
    assert (sub.question_count, sub.correct_count) == (2, 0)
    assert_consistent(session, sub)


def test_manual_verdict_survives_regrading_others(session):
    sub, rows = build(session, [q("9", user="online", key="internet"), q("10", user="x", key="y")])
    review.mark_correct(session, rows["9"])
    review.fill_answers(session, sub, [("10", "y", "")], NOW, explainer()[0])
    assert rows["9"].status == CORRECT and rows["10"].status == CORRECT


def test_edit_answer(session):
    sub, rows = build(session, [q("5", user="comady", key="comedy"), q("6", user="x", key="x")])
    assert review.edit_answer(session, rows["5"], {"user_answer": "Comedy", "error_type": "拼字錯誤"}) == CORRECT
    assert review.edit_answer(session, rows["5"], {"user_answer": ""}) == BLANK
    assert rows["5"].error_type == "未作答"
    assert review.edit_answer(session, rows["5"], {"user_answer": "drama", "correct_answer": "comic/comedy",
                                                    "error_type": "未作答"}) == WRONG
    assert rows["5"].accepted == ["comic", "comedy"] and rows["5"].error_type == "其他"
    review.edit_answer(session, rows["5"], {"error_type": "詞彙不認識"})
    assert rows["5"].error_type == "詞彙不認識"  # the user's own choice of type sticks
    with pytest.raises(ValueError):
        review.edit_answer(session, rows["5"], {"question_no": "6"})
    assert_consistent(session, sub)


def test_fill_with_known_key_needs_no_claude_for_right_answers(session):
    sub, rows = build(session, [q("11", "choice", visible=False, key="B", options=[("A", "15"), ("B", "30")]),
                                q("12", "choice", visible=False, key="A"),
                                q("13", "tfng", visible=False, key="NO")])
    assert sub.question_count == 0
    explain, calls = explainer()
    res = review.fill_answers(session, sub, [("11", "30", ""), ("12", "c", ""), ("13", "n", ""), (" ", "x", "")],
                              NOW, explain)
    assert (res.graded, res.correct, res.warning) == (3, 2, "")
    assert [x["question_no"] for c in calls for x in c] == ["12"]  # only the wrong one is explained
    assert rows["12"].explanation == "解析 12" and rows["11"].user_answer == "B"
    assert (sub.question_count, sub.correct_count) == (3, 2)
    # Answering again replaces the old answer instead of adding a question.
    review.fill_answers(session, sub, [("12", "A", "")], NOW, explain)
    assert (sub.question_count, sub.correct_count) == (3, 3)
    assert_consistent(session, sub)


def test_fill_new_question_gets_key_from_claude(session):
    sub, _ = build(session, [q("1", user="x", key="x")])
    explain, calls = explainer({"2": {"answer_key": "theatre/theater", "kind": "fill", "key_source": "coach"}})
    res = review.fill_answers(session, sub, [("2", "theatre", "")], NOW, explain)
    row = review.answers_of(session, sub.id)[1]
    assert (row.question_no, row.status, row.key_source, res.correct) == ("2", CORRECT, "coach", 1)
    assert calls[0][0]["answer_key"] == ""


def test_fill_user_given_key_and_explain_failure(session):
    sub, rows = build(session, [q("13", "choice", visible=False, key="C")])

    def broken(*a):
        raise GradingError("API 掛了")
    res = review.fill_answers(session, sub, [("13", "B", "recordings")], NOW, broken)
    assert "API 掛了" in res.warning
    assert rows["13"].status == WRONG and rows["13"].key_source == "user"  # verdict saved anyway
    assert (sub.question_count, sub.correct_count) == (1, 0)


def test_parse_answers():
    assert review.parse_answers("27A 28c 29: B") == [("27", "A"), ("28", "c"), ("29", "B")]
    assert review.parse_answers("37 NOT GIVEN, 38 ng 39 yes") == [("37", "NOT GIVEN"), ("38", "ng"), ("39", "yes")]
    assert review.parse_answers("hello") == []


def test_clean_no():
    assert [review.clean_no(x) for x in ("Q37", " 037 ", "37.", "")] == ["37", "37", "37", ""]


def test_review_page_routes(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlmodel import Session

    from app import submissions
    from app.db import engine, init_db
    from app.main import app
    from tests.fakes import result

    init_db()
    fake = result([q("1", user="", key="river"), q("2", "choice", user="B", key="B"),
                   q("3", "choice", visible=False, key="C")])
    monkeypatch.setattr(submissions.grader, "grade", lambda *a: fake)
    explain, calls = explainer()
    monkeypatch.setattr(review.grader, "explain", explain)
    with TestClient(app) as c:
        c.post("/login", data={"password": "pw"})
        r = c.post("/submit", data={"skill": "reading", "text": "x"})
        sub_id = int(str(r.url).split("/submissions/")[1].split("?")[0])
        assert "（未作答）" in r.text and "其實答對了" in r.text and "其實答錯了" in r.text and "補答案" in r.text
        assert "找不到你在第 3 題" in r.text and "1/2" in r.text
        assert [x["question_no"] for x in calls.pop()] == ["1"]  # blank answer gets an explanation
        with Session(engine) as s:
            ids = {a.question_no: a.id for a in review.answers_of(s, sub_id)}
        r = c.post(f"/mistakes/{ids['1']}/edit", data={"user_answer": "River", "correct_answer": "river",
                                                      "question_no": "1", "error_type": "未作答"})
        assert "答對的題目（2）" in r.text and "✏️ 這份批改有手動修正過" in r.text
        r = c.post(f"/mistakes/{ids['1']}/edit", data={"question_no": "2"})
        assert "第 2 題已經存在" in r.text
        r = c.post(f"/mistakes/{ids['2']}/mark-wrong", data={"user_answer": "C", "error_type": "細節漏看"})
        assert "答對的題目（1）" in r.text and "錯題解析（1）" in r.text
        r = c.post(f"/submissions/{sub_id}/answers",
                   data={"no": ["3", ""], "user": ["A", ""], "correct": ["", ""], "quick": "3 C"})
        assert "找不到你在第" not in r.text and calls == []  # 3 C matches the key: no Claude call

        def broken(*a):
            raise GradingError("API 掛了")
        monkeypatch.setattr(review.grader, "explain", broken)
        r = c.post(f"/submissions/{sub_id}/answers", data={"no": "9", "user": "A", "correct": ""})
        assert "解析沒有產生：API 掛了" in r.text
        assert "修改科目／出處" in r.text
        r = c.post(f"/submissions/{sub_id}/info", data={"skill": "listening", "book": "C18", "test": "Test 2",
                                                       "part": "Section 1", "title": ""})
        assert "聽力 ·" in r.text and "C18 Test 2 Section 1" in r.text
        with Session(engine) as s:
            sub = s.get(Submission, sub_id)
            assert (sub.question_count, sub.correct_count) == (3, 2) and sub.skill == "listening"
            assert review.answers_of(s, sub_id)[-1].status == UNGRADED  # Q9: no key yet


def test_change_skill_moves_progress_and_fixes_completion(session):
    from app.logic import add_progress, get_or_create_day, get_settings

    st = get_settings(session)
    st.goals = {"listening": 1, "reading": 1, "writing": 0, "speaking": 0}
    session.add(st)
    session.commit()
    day = get_or_create_day(session, st, "2026-10-21")
    # Two sets both filed as reading: reading 2/1, listening 0/1 -> not complete.
    sub, _ = build(session, [q("1", user="a", key="b")])
    sub.skill = "reading"
    add_progress(session, st, day, "reading", 2)
    assert day.status == "open"

    review.change_info(session, sub, "listening", "C18", "Test 2", "Section 1", "")
    session.refresh(sub)
    assert sub.skill == "listening" and sub.source_label == "C18 Test 2 Section 1"
    assert day.done == {"listening": 1, "reading": 1} and day.status == "completed" and st.streak == 1
    assert session.exec(select(Answer)).one().skill == "listening"

    # Moving it back undoes the completion before settlement.
    review.change_info(session, sub, "reading", "C18", "Test 2", "Section 1", "")
    assert day.status == "open" and st.streak == 0


def test_change_skill_on_settled_day_keeps_outcome(session):
    from app.logic import get_or_create_day, get_settings

    st = get_settings(session)
    st.goals = {"listening": 1, "reading": 1, "writing": 0, "speaking": 0}
    day = get_or_create_day(session, st, "2026-10-21")
    day.done = {"listening": 0, "reading": 2}
    day.status, day.settled = "failed", True
    session.add(day)
    session.commit()
    sub = make_sub(session, "reading")
    review.change_info(session, sub, "listening", "", "", "", "")
    assert day.done == {"listening": 1, "reading": 1} and day.status == "failed"


def test_delete_submission_takes_back_progress(session):
    from app.logic import add_progress, get_or_create_day, get_settings
    from app.models import SubmissionImage

    st = get_settings(session)
    st.goals = {"listening": 1, "reading": 0, "writing": 0, "speaking": 0}
    session.add(st)
    session.commit()
    day = get_or_create_day(session, st, "2026-10-21")
    sub, _ = build(session, [q("1", user="a", key="b")])
    session.add(SubmissionImage(submission_id=sub.id, media_type="image/png", data=b"x"))
    session.commit()
    add_progress(session, st, day, "listening", 1)
    assert day.status == "completed" and st.streak == 1

    review.delete_submission(session, sub)
    assert session.exec(select(Submission)).all() == []
    assert session.exec(select(Answer)).all() == []
    assert session.exec(select(SubmissionImage)).all() == []
    assert day.done["listening"] == 0 and day.status == "open" and st.streak == 0


def test_submissions_page_lists_filters_and_deletes(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlmodel import Session

    from app import submissions
    from app.db import engine, init_db
    from app.main import app
    from tests.fakes import result

    init_db()

    def fake(book, wrong):
        return result([q("1", user="A" if wrong else "B", key="B"), q("2", user="C", key="C")],
                      source={"book": book, "test": "Test 4", "part": "Passage 1", "title": "History page"})

    with TestClient(app) as c:
        c.post("/login", data={"password": "pw"})
        monkeypatch.setattr(submissions.grader, "grade", lambda *a: fake("C10", 1))
        monkeypatch.setattr(review.grader, "explain", explainer()[0])
        r1 = c.post("/submit", data={"skill": "reading", "text": "x"})
        monkeypatch.setattr(submissions.grader, "grade", lambda *a: fake("C11", 0))
        c.post("/submit", data={"skill": "reading", "text": "x"})
        page = c.get("/submissions").text
        assert "C10 Test 4 Passage 1｜History page" in page and "C11 Test 4 Passage 1" in page
        assert "1 題還沒懂" in page
        page = c.get("/submissions", params={"book": "C11"}).text
        assert "C11 Test 4" in page and "C10 Test 4" not in page
        page = c.get("/submissions", params={"only": "open"}).text
        assert "C10 Test 4" in page and "C11 Test 4" not in page

        sub_id = int(str(r1.url).split("/submissions/")[1].split("?")[0])
        assert "刪除這份提交" in r1.text
        r = c.post(f"/submissions/{sub_id}/delete")
        assert "已刪除" in r.text and "C10 Test 4" not in r.text
        with Session(engine) as s:
            assert s.get(Submission, sub_id) is None
        assert "📚 已做題目" in c.get("/").text
