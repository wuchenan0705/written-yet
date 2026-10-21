"""One-time conversion of the old per-question storage into Answer rows.

Before Answer existed, wrong answers were Mistake rows, right ones a correct_items list in
Submission.result, and unseen ones a missing_answers list, while the score was adjusted
by +/-1 and drifted. Each old submission is rebuilt from those pieces once: a question
appears once (a Mistake row wins over correct_items), the old verdicts are kept, and the
score is recounted. The legacy keys are then removed from result, so it never runs twice.
"""
import logging
import re

from sqlmodel import Session, select

from app import judge, review
from app.models import (
    BLANK, CORRECT, OBJECTIVE_SKILLS, OPTION_KINDS, UNANSWERED, UNGRADED, WRONG,
    Answer, Mistake, Submission,
)

log = logging.getLogger(__name__)
LEGACY_KEYS = ("mistakes", "correct_items", "missing_answers")
STALE_COUNTS = ("question_count", "correct_count")  # Claude's original totals
MANUAL_NOTES = ("（手動改為答對）", "（手動改為答錯）", "（手動補上）")
_PREFIXED = re.compile(r"^([A-H])\s+(\S.*)$")  # "C   people would spend more money"
# An option box line in copied 雅思哥 text: unchosen options are listed as "A   text".
_BOX_LINE = re.compile(r"^\s*([A-H])\s{2,}(\S.*?)\s*$", re.M)


def _kind(*values: str) -> str:
    vals = [judge.clean(v) for v in values if judge.clean(v)]
    if any(_PREFIXED.match(v) for v in vals) or (vals and all(re.fullmatch(r"[A-H]", v) for v in vals)):
        return "matching"
    if vals and all(judge.canon("tfng", v, {}) in judge.TFNG.values() for v in vals):
        return "tfng"
    return "fill"


def _box(raw_text: str, values: list[str]) -> dict:
    """Option texts seen next to letters anywhere in the set: {'C': 'people would spend more money'}."""
    box = {m.group(1): m.group(2) for m in _BOX_LINE.finditer(raw_text or "")}
    for v in values:
        m = _PREFIXED.match(judge.clean(v))
        if m:
            box.setdefault(m.group(1), m.group(2).strip())
    return box


def migrate_submission(session: Session, sub: Submission) -> None:
    result = dict(sub.result)
    if sub.skill in OBJECTIVE_SKILLS and not review.answers_of(session, sub.id):
        mistakes = session.exec(select(Mistake).where(Mistake.submission_id == sub.id).order_by(Mistake.id)).all()
        stale = {review.clean_no(m.get("question_no", "")): m for m in result.get("mistakes", [])}
        correct = result.get("correct_items", [])
        box = _box(sub.raw_text, [m.user_answer for m in mistakes] + [m.correct_answer for m in mistakes]
                   + [s.get("user_answer", "") for s in stale.values()] + [c.get("answer", "") for c in correct])

        rows: dict[str, Answer] = {}

        def add(no, kind, user, key, **fields):
            options = box if kind in OPTION_KINDS else {}
            rows[no] = Answer(
                submission_id=sub.id, skill=sub.skill, created_at=sub.created_at, question_no=no, kind=kind,
                options=options, user_answer=judge.canon(kind, user, options),
                accepted=judge.split_key(kind, key, options), **fields)
            return rows[no]

        for m in mistakes:  # later rows are later verdicts for the same question
            no = review.clean_no(m.question_no) or f"?{m.id}"
            a = add(no, _kind(m.user_answer, m.correct_answer), m.user_answer, m.correct_answer,
                    question=m.question, explanation=m.explanation, evidence=m.evidence, tip=m.tip,
                    understood=m.understood, verdict_by="manual" if m.explanation in MANUAL_NOTES else "auto")
            a.status = WRONG if a.user_answer else BLANK
            a.error_type = UNANSWERED if a.status == BLANK else (
                m.error_type if m.error_type and m.error_type != UNANSWERED else "其他")

        for c in correct:
            no = review.clean_no(c.get("question_no", ""))
            if not no or no in rows:
                continue
            answer, manual = c.get("answer", ""), c.get("note") in MANUAL_NOTES
            if manual and no in stale:  # marked right by hand: the student's answer is the key
                answer = stale[no].get("user_answer", "") or answer
            a = add(no, _kind(answer), answer, answer, question=c.get("question", ""), note=c.get("note", ""),
                    evidence=c.get("evidence", ""), verdict_by="manual" if manual else "auto")
            a.status = CORRECT

        for raw in result.get("missing_answers", []):
            no = review.clean_no(raw)
            if no and no not in rows:
                rows[no] = Answer(submission_id=sub.id, skill=sub.skill, created_at=sub.created_at,
                                  question_no=no, status=UNGRADED)

        for a in rows.values():
            session.add(a)
        session.flush()
        review.recount(session, sub)
    for k in LEGACY_KEYS + (STALE_COUNTS if sub.skill in OBJECTIVE_SKILLS else ()):
        result.pop(k, None)
    sub.result = result
    session.add(sub)
    session.commit()


def migrate_answers(session: Session) -> int:
    """Convert every submission that still has legacy per-question data. Returns the count."""
    done = 0
    for sub in session.exec(select(Submission).order_by(Submission.id)).all():
        if any(k in sub.result for k in LEGACY_KEYS):
            migrate_submission(session, sub)
            done += 1
    if done:
        log.info("migrated %d submissions to per-question answers", done)
    return done
