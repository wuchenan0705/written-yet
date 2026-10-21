"""Manual corrections to a graded set, for when Claude misreads a screenshot.

Counts are adjusted by +/-1 rather than recomputed, because submissions graded
before correct_items existed only have Claude's totals, not the per-question list.
"""
import re

from sqlmodel import Session, select

from app import grader
from app.logic import get_or_create_day, get_settings, move_progress, remove_progress
from app.models import SKILLS, Mistake, Submission, SubmissionImage

BLANK = "未作答"


def normalize(answer: str) -> str:
    return re.sub(r"\s+", " ", answer or "").strip().lower()


def same_answer(a: str, b: str) -> bool:
    return bool(normalize(a)) and normalize(a) == normalize(b)


def _update(session: Session, sub: Submission, result: dict, d_questions: int, d_correct: int) -> None:
    sub.question_count = max(0, sub.question_count + d_questions)
    sub.correct_count = min(max(0, sub.correct_count + d_correct), sub.question_count)
    result["question_count"] = sub.question_count
    result["correct_count"] = sub.correct_count
    result["edited"] = True
    sub.result = result  # reassign so SQLAlchemy sees the JSON change
    session.add(sub)


def _sort_key(item: dict):
    no = item.get("question_no", "")
    return (0, int(no)) if no.isdigit() else (1, no)


def _add_correct(result: dict, item: dict) -> None:
    items = list(result.get("correct_items", []))
    items.append(item)
    result["correct_items"] = sorted(items, key=_sort_key)


def edit_mistake(session: Session, m: Mistake, fields: dict) -> bool:
    """Update a mistake. Returns True if the edit made it correct (it is then moved)."""
    for f in ("question_no", "question", "user_answer", "correct_answer", "error_type", "explanation", "tip"):
        if f in fields:
            setattr(m, f, str(fields[f]).strip())
    if same_answer(m.user_answer, m.correct_answer):
        mistake_to_correct(session, m)
        return True
    if not m.user_answer:
        m.error_type = BLANK
    session.add(m)
    session.commit()
    return False


def mistake_to_correct(session: Session, m: Mistake) -> None:
    sub = session.get(Submission, m.submission_id)
    result = dict(sub.result)
    _add_correct(result, {
        "question_no": m.question_no, "question": m.question,
        "answer": m.correct_answer or m.user_answer, "note": "（手動改為答對）", "evidence": m.evidence,
    })
    _update(session, sub, result, 0, +1)
    session.delete(m)
    session.commit()


def correct_to_mistake(session: Session, sub: Submission, index: int, user_answer: str,
                       error_type: str, now) -> Mistake | None:
    result = dict(sub.result)
    items = list(result.get("correct_items", []))
    if not 0 <= index < len(items):
        return None
    item = items.pop(index)
    result["correct_items"] = items
    user_answer = user_answer.strip()
    m = Mistake(
        submission_id=sub.id, created_at=now, skill=sub.skill,
        question_no=item.get("question_no", ""), question=item.get("question", ""),
        user_answer=user_answer, correct_answer=item.get("answer", ""),
        error_type=BLANK if not user_answer else (error_type or "其他"),
        explanation="（手動改為答錯）", evidence=item.get("evidence", ""),
    )
    session.add(m)
    _update(session, sub, result, 0, -1)
    session.commit()
    return m


def parse_answers(text: str) -> list[tuple[str, str]]:
    """Parse '27A 28 NOT GIVEN 29: ng' into [('27','A'), ('28','NOT GIVEN'), ('29','ng')]."""
    pairs: list[tuple[str, list[str]]] = []
    for tok in re.findall(r"\d+|[^\d\s,，;；:：、.]+", text):
        if tok.isdigit():
            pairs.append((tok, []))
        elif pairs:
            pairs[-1][1].append(tok)
    return [(no, " ".join(words)) for no, words in pairs]


def fill_answers(session: Session, sub: Submission, answers: list[tuple[str, str, str]],
                 now, grade_fn=None) -> tuple[int, int]:
    """Have Claude grade answers filled in after submission (e.g. multiple-choice
    selections lost when copying text). Re-answering a question replaces it.

    answers: (question_no, user_answer, correct_answer_or_empty).
    Returns (graded, correct).
    """
    answers = [(no.strip(), user.strip(), correct.strip()) for no, user, correct in answers if no.strip()]
    if not answers:
        return 0, 0
    images = [(i.media_type, i.data) for i in
              session.exec(select(SubmissionImage).where(SubmissionImage.submission_id == sub.id)).all()]
    graded = (grade_fn or grader.grade_answers)(sub.skill, sub.raw_text, images, answers)

    result = dict(sub.result)
    nos = {c["question_no"].strip() for c in graded["correct_items"]} | {m["question_no"].strip() for m in graded["mistakes"]}
    d_q = d_c = 0
    # Drop earlier verdicts for the same questions so they are not counted twice.
    for m in session.exec(select(Mistake).where(Mistake.submission_id == sub.id)).all():
        if m.question_no.strip() in nos:
            session.delete(m)
            d_q -= 1
    kept = []
    for c in result.get("correct_items", []):
        if c.get("question_no", "").strip() in nos:
            d_q -= 1
            d_c -= 1
        else:
            kept.append(c)
    result["correct_items"] = kept

    for c in graded["correct_items"]:
        _add_correct(result, c)
        d_q += 1
        d_c += 1
    for m in graded["mistakes"]:
        session.add(Mistake(submission_id=sub.id, created_at=now, skill=sub.skill, **m))
        d_q += 1
    result["missing_answers"] = [q for q in result.get("missing_answers", []) if q.strip() not in nos]
    _update(session, sub, result, d_q, d_c)
    session.commit()
    return len(nos), len(graded["correct_items"])


def change_info(session: Session, sub: Submission, skill: str, book: str, test: str,
                part: str, title: str) -> None:
    """Fix a submission filed under the wrong skill or source."""
    if skill in SKILLS and skill != sub.skill:
        old = sub.skill
        sub.skill = skill
        for m in session.exec(select(Mistake).where(Mistake.submission_id == sub.id)).all():
            m.skill = skill
            session.add(m)
        st = get_settings(session)
        move_progress(session, st, get_or_create_day(session, st, sub.date), old, skill)
    sub.book, sub.test, sub.part, sub.title = (v.strip() for v in (book, test, part, title))
    session.add(sub)
    session.commit()


def delete_submission(session: Session, sub: Submission) -> None:
    """Delete a submission with its mistakes and screenshots, and take back its progress."""
    for model in (Mistake, SubmissionImage):
        for row in session.exec(select(model).where(model.submission_id == sub.id)).all():
            session.delete(row)
    skill, day_str = sub.skill, sub.date
    session.delete(sub)
    session.commit()
    st = get_settings(session)
    remove_progress(session, st, get_or_create_day(session, st, day_str), skill)
