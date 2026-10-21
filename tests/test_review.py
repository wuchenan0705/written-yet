from datetime import datetime

from sqlmodel import select

from app import review
from app.grader import ERROR_TYPES, SYSTEM_PROMPT
from app.models import Mistake, Submission

NOW = datetime(2026, 10, 21, 10)


def make_sub(session, correct_items=None, missing=None, q=3, c=1):
    sub = Submission(created_at=NOW, date="2026-10-21", skill="reading", source="web", raw_text="",
                     question_count=q, correct_count=c,
                     result={"correct_items": correct_items or [], "missing_answers": missing or []})
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


def add_mistake(session, sub, no="2", user="FALSE", correct="NOT GIVEN"):
    m = Mistake(submission_id=sub.id, created_at=NOW, skill="reading", question_no=no,
                question="Q", user_answer=user, correct_answer=correct, error_type="其他")
    session.add(m)
    session.commit()
    return m


def test_prompt_counts_blanks_as_wrong():
    assert ERROR_TYPES[0] == "未作答"
    assert "空格是空的" in SYSTEM_PROMPT and "空白的填空不是這種情況" in SYSTEM_PROMPT


def test_same_answer_ignores_case_and_spacing():
    assert review.same_answer(" not  given", "NOT GIVEN")
    assert not review.same_answer("", "")
    assert not review.same_answer("YES", "NO")


def test_mark_mistake_correct_moves_it_and_updates_counts(session):
    sub = make_sub(session, correct_items=[{"question_no": "3", "question": "", "answer": "A", "note": "", "evidence": ""}])
    m = add_mistake(session, sub)
    review.mistake_to_correct(session, m)
    session.refresh(sub)
    assert session.exec(select(Mistake)).all() == []
    assert (sub.question_count, sub.correct_count) == (3, 2)
    assert [i["question_no"] for i in sub.result["correct_items"]] == ["2", "3"]
    assert sub.result["edited"] is True


def test_edit_mistake_to_matching_answer_moves_to_correct(session):
    sub = make_sub(session)
    m = add_mistake(session, sub)
    assert review.edit_mistake(session, m, {"user_answer": "not given"}) is True
    session.refresh(sub)
    assert sub.correct_count == 2 and sub.result["correct_items"][0]["answer"] == "NOT GIVEN"


def test_edit_mistake_blank_answer_becomes_unanswered(session):
    sub = make_sub(session)
    m = add_mistake(session, sub)
    assert review.edit_mistake(session, m, {"user_answer": "", "correct_answer": "B"}) is False
    assert (m.user_answer, m.correct_answer, m.error_type) == ("", "B", "未作答")


def test_correct_item_marked_wrong(session):
    sub = make_sub(session, correct_items=[{"question_no": "5", "question": "Q5", "answer": "C", "note": "", "evidence": "line"}], c=2)
    m = review.correct_to_mistake(session, sub, 0, "D", "細節漏看", NOW)
    session.refresh(sub)
    assert sub.correct_count == 1 and sub.result["correct_items"] == []
    assert (m.question_no, m.user_answer, m.correct_answer, m.error_type, m.evidence) == ("5", "D", "C", "細節漏看", "line")
    assert review.correct_to_mistake(session, sub, 3, "x", "其他", NOW) is None


def test_parse_answers():
    assert review.parse_answers("27A 28c 29: B") == [("27", "A"), ("28", "c"), ("29", "B")]
    assert review.parse_answers("37 NOT GIVEN, 38 ng 39 yes") == [("37", "NOT GIVEN"), ("38", "ng"), ("39", "yes")]
    assert review.parse_answers("hello") == []


def fake_answers(correct_nos=(), wrong_nos=()):
    calls = []

    def grade(skill, text, images, answers):
        calls.append(list(answers))
        return {
            "correct_items": [{"question_no": n, "question": f"Q{n}", "answer": "YES", "note": "", "evidence": ""}
                              for n in correct_nos],
            "mistakes": [{"question_no": n, "question": f"Q{n}", "user_answer": "NO", "correct_answer": "NOT GIVEN",
                          "error_type": "NOT GIVEN/FALSE 混淆", "explanation": "", "evidence": "", "tip": ""}
                         for n in wrong_nos],
        }
    return grade, calls


def test_fill_answers_grades_missing_questions_with_claude(session):
    sub = make_sub(session, missing=["37", "38", "39"], q=2, c=1)
    grade, calls = fake_answers(correct_nos=["37"], wrong_nos=["38"])
    assert review.fill_answers(session, sub, [("37", "Y", ""), ("38", "N", "NG"), (" ", "x", "")], NOW, grade) == (2, 1)
    assert calls[0] == [("37", "Y", ""), ("38", "N", "NG")]
    session.refresh(sub)
    assert sub.result["missing_answers"] == ["39"]
    assert (sub.question_count, sub.correct_count) == (4, 2)
    assert session.exec(select(Mistake)).one().error_type == "NOT GIVEN/FALSE 混淆"


def test_fill_answers_regrading_replaces_old_verdict(session):
    sub = make_sub(session, correct_items=[{"question_no": "5", "question": "", "answer": "A", "note": "", "evidence": ""}], q=2, c=1)
    add_mistake(session, sub, no="6")
    grade, _ = fake_answers(correct_nos=["6"], wrong_nos=["5"])
    review.fill_answers(session, sub, [("5", "B", ""), ("6", "C", "")], NOW, grade)
    session.refresh(sub)
    assert (sub.question_count, sub.correct_count) == (2, 1)
    assert [c["question_no"] for c in sub.result["correct_items"]] == ["6"]
    assert session.exec(select(Mistake)).one().question_no == "5"


def test_review_page_routes(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlmodel import Session

    from app import submissions
    from app.db import engine, init_db
    from app.main import app

    init_db()
    fake = {
        "question_count": 2, "correct_count": 1, "summary": "", "source": {"book": "", "test": "", "part": "", "title": ""},
        "mistakes": [{"question_no": "1", "question": "Q1", "user_answer": "", "correct_answer": "river",
                      "error_type": "未作答", "explanation": "", "evidence": "", "tip": ""}],
        "correct_items": [{"question_no": "2", "question": "Q2", "answer": "B", "note": "", "evidence": ""}],
        "band_estimate": "", "criteria": [], "corrections": [], "improved_version": "", "missing_answers": ["3"],
    }
    monkeypatch.setattr(submissions.grader, "grade", lambda *a: fake)
    with TestClient(app) as c:
        c.post("/login", data={"password": "pw"})
        r = c.post("/submit", data={"skill": "reading", "text": "x"})
        sub_id = int(str(r.url).split("/submissions/")[1].split("?")[0])
        assert "（未作答）" in r.text and "其實答對了" in r.text and "其實答錯了" in r.text and "補答案，交給教練批改" in r.text
        with Session(engine) as s:
            mid = s.exec(select(Mistake).where(Mistake.submission_id == sub_id)).one().id
        r = c.post(f"/mistakes/{mid}/edit", data={"user_answer": "River", "correct_answer": "river",
                                                  "question_no": "1", "error_type": "其他"})
        assert "答對的題目（2）" in r.text and "✏️ 這份批改有手動修正過" in r.text
        r = c.post(f"/submissions/{sub_id}/correct/1/mark-wrong", data={"user_answer": "C", "error_type": "細節漏看"})
        assert "答對的題目（1）" in r.text and "錯題解析（1）" in r.text
        grade, calls = fake_answers(correct_nos=["3"])
        monkeypatch.setattr(review.grader, "grade_answers", grade)
        r = c.post(f"/submissions/{sub_id}/answers",
                   data={"no": ["3", ""], "user": ["C", ""], "correct": ["", ""], "quick": "3 D"})
        assert calls[-1] == [("3", "D", "")]
        assert "看不到你" not in r.text and "找不到你在第" not in r.text

        def broken(*a):
            raise review.grader.GradingError("API 掛了")
        monkeypatch.setattr(review.grader, "grade_answers", broken)
        r = c.post(f"/submissions/{sub_id}/answers", data={"no": "9", "user": "A", "correct": ""})
        assert "批改失敗：API 掛了" in r.text
        assert "修改科目／出處" in r.text
        r = c.post(f"/submissions/{sub_id}/info", data={"skill": "listening", "book": "C18", "test": "Test 2",
                                                       "part": "Section 1", "title": ""})
        assert "聽力 ·" in r.text and "C18 Test 2 Section 1" in r.text
        with Session(engine) as s:
            sub = s.get(Submission, sub_id)
            assert (sub.question_count, sub.correct_count) == (3, 2) and sub.skill == "listening"


def test_change_skill_moves_progress_and_fixes_completion(session):
    from app.logic import add_progress, get_or_create_day, get_settings

    st = get_settings(session)
    st.goals = {"listening": 1, "reading": 1, "writing": 0, "speaking": 0}
    session.add(st)
    session.commit()
    day = get_or_create_day(session, st, "2026-10-21")
    # Two sets both filed as reading: reading 2/1, listening 0/1 -> not complete.
    sub = make_sub(session)
    add_mistake(session, sub)
    add_progress(session, st, day, "reading", 2)
    assert day.status == "open"

    review.change_info(session, sub, "listening", "C18", "Test 2", "Section 1", "")
    session.refresh(sub)
    assert sub.skill == "listening" and sub.source_label == "C18 Test 2 Section 1"
    assert day.done == {"listening": 1, "reading": 1} and day.status == "completed" and st.streak == 1
    assert session.exec(select(Mistake)).one().skill == "listening"

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
    sub = make_sub(session)
    review.change_info(session, sub, "listening", "", "", "", "")
    assert day.done == {"listening": 1, "reading": 1} and day.status == "failed"


def test_delete_submission_takes_back_progress(session):
    from app.logic import add_progress, get_or_create_day, get_settings
    from app.models import SubmissionImage

    st = get_settings(session)
    st.goals = {"listening": 0, "reading": 1, "writing": 0, "speaking": 0}
    session.add(st)
    session.commit()
    day = get_or_create_day(session, st, "2026-10-21")
    sub = make_sub(session)
    add_mistake(session, sub)
    session.add(SubmissionImage(submission_id=sub.id, media_type="image/png", data=b"x"))
    session.commit()
    add_progress(session, st, day, "reading", 1)
    assert day.status == "completed" and st.streak == 1

    review.delete_submission(session, sub)
    assert session.exec(select(Submission)).all() == []
    assert session.exec(select(Mistake)).all() == []
    assert session.exec(select(SubmissionImage)).all() == []
    assert day.done["reading"] == 0 and day.status == "open" and st.streak == 0


def test_submissions_page_lists_filters_and_deletes(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlmodel import Session

    from app import submissions
    from app.db import engine, init_db
    from app.main import app

    init_db()

    def fake(book, wrong):
        return {
            "question_count": 2, "correct_count": 2 - wrong, "summary": "",
            "source": {"book": book, "test": "Test 4", "part": "Passage 1", "title": "History page"},
            "mistakes": [{"question_no": "1", "question": "Q", "user_answer": "A", "correct_answer": "B",
                          "error_type": "其他", "explanation": "", "evidence": "", "tip": ""}] * wrong,
            "correct_items": [], "band_estimate": "", "criteria": [], "corrections": [],
            "improved_version": "", "missing_answers": [],
        }

    with TestClient(app) as c:
        c.post("/login", data={"password": "pw"})
        monkeypatch.setattr(submissions.grader, "grade", lambda *a: fake("C10", 1))
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
