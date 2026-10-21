"""Old storage -> Answer rows, using the shapes found in the real database."""
from datetime import datetime

from app import migrate, review
from app.models import BLANK, CORRECT, UNGRADED, WRONG, Mistake, Submission

NOW = datetime(2026, 10, 21, 21)
RAW = "27  jazz music: \nC   people would spend more money\nA   people may think the restaurant is overpriced\n"


def legacy_sub(session, result, mistakes=(), q=0, c=0, raw=RAW):
    sub = Submission(created_at=NOW, date="2026-10-21", skill="listening", source="web", raw_text=raw,
                     question_count=q, correct_count=c, result=result)
    session.add(sub)
    session.commit()
    session.refresh(sub)
    for no, user, key, etype, expl in mistakes:
        session.add(Mistake(submission_id=sub.id, created_at=NOW, skill="listening", question_no=no,
                            user_answer=user, correct_answer=key, error_type=etype, explanation=expl))
    session.commit()
    return sub


def item(no, answer, note=""):
    return {"question_no": no, "question": "", "answer": answer, "note": note, "evidence": ""}


def test_drifted_counts_duplicates_and_manual_fixes(session):
    # Like submission #3: stored 7/20, Q22 twice, Q27 in correct_items and a stale mistakes copy.
    garbage = "（教練判斷）選項方框中的文字不完整"
    sub = legacy_sub(session, {
        "summary": "s", "question_count": 20, "correct_count": 7, "edited": True,
        "correct_items": [item("22", "at a uniform level"), item("22", "at a uniform level", "（手動改為答對）"),
                          item("27", garbage, "（手動改為答對）"), item("29", "E people would leave")],
        "mistakes": [{"question_no": "27", "user_answer": "C people would spend more money",
                      "correct_answer": garbage}],
        "missing_answers": [],
    }, mistakes=[("21", "on food-making.", "on consumers.", "未作答", "（手動補上）"),
                 ("28", "F people would likely make complaints",
                  "people may think the restaurant is overpriced", "未作答", "（手動改為答錯）")], q=20, c=7)
    assert migrate.migrate_answers(session) == 1
    rows = {a.question_no: a for a in review.answers_of(session, sub.id)}
    assert list(rows) == ["21", "22", "27", "28", "29"]
    assert (sub.question_count, sub.correct_count) == (5, 3)
    assert rows["27"].status == CORRECT and rows["27"].accepted == ["C"] and rows["27"].verdict_by == "manual"
    assert rows["27"].key_text == "C people would spend more money"
    assert rows["28"].status == WRONG and rows["28"].accepted == ["A"] and rows["28"].user_answer == "F"
    assert rows["28"].error_type == "其他"  # non-blank answers can't be 未作答
    assert sorted(sub.result) == ["edited", "summary"]
    assert migrate.migrate_answers(session) == 0  # runs once


def test_missing_and_mistake_for_the_same_question(session):
    # Like submission #4: Q35 listed as missing and also as a mistake with the literal answer 未作答.
    sub = legacy_sub(session, {
        "correct_items": [item("32", "parking")], "missing_answers": ["35", "40"], "mistakes": [],
    }, mistakes=[("35", "未作答", "boxes", "定位錯誤", "留白。"), ("31", "acess", "access", "拼字錯誤", "")], q=10, c=4)
    migrate.migrate_answers(session)
    rows = {a.question_no: a for a in review.answers_of(session, sub.id)}
    assert [(n, a.status) for n, a in rows.items()] == [
        ("31", WRONG), ("32", CORRECT), ("35", BLANK), ("40", UNGRADED)]
    assert rows["35"].user_answer == "" and rows["35"].error_type == "未作答"
    assert (sub.question_count, sub.correct_count) == (3, 1)


def test_writing_only_drops_legacy_keys(session):
    sub = legacy_sub(session, {"band_estimate": "6.0", "question_count": 1, "mistakes": [],
                               "correct_items": [], "missing_answers": []}, q=1)
    sub.skill = "writing"
    session.add(sub)
    session.commit()
    migrate.migrate_answers(session)
    assert sub.result == {"band_estimate": "6.0", "question_count": 1}
    assert review.answers_of(session, sub.id) == [] and sub.question_count == 1
