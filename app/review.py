"""Per-question results: building them from a grading, filling in answers later, and
manual corrections.

Every change ends in _judge() and recount(): a question exists once per submission
(unique question_no), right/wrong comes from judge.py, and the score is always the count
of Answer rows. Nothing is adjusted by +/-1.
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Sequence

from sqlmodel import Session, select

from app import grader, judge
from app.logic import get_or_create_day, get_settings, move_progress, remove_progress
from app.models import (
    ANSWER_KINDS, CORRECT, ERROR_TYPES, OPTION_KINDS, SKILLS, UNANSWERED, UNGRADED, WRONG, BLANK,
    Answer, Mistake, Submission, SubmissionImage,
)

log = logging.getLogger(__name__)
ExplainFn = Callable[..., list[dict]]
# Error types judge.py can read off the strings; these beat Claude's guess.
STRING_ERROR_TYPES = ("拼字錯誤", "單複數/詞形")
_SINGLE_LETTER = re.compile(r"(?<![A-Za-z])[A-Za-z](?![A-Za-z])")


def clean_no(no) -> str:
    s = judge.clean(str(no or "")).upper().removeprefix("Q").strip(" .:、")
    return str(int(s)) if s.isdigit() else s


def sort_key(a: Answer):
    return (0, int(a.question_no), "") if a.question_no.isdigit() else (1, 0, a.question_no)


def answers_of(session: Session, sub_id: int) -> list[Answer]:
    return sorted(session.exec(select(Answer).where(Answer.submission_id == sub_id)).all(), key=sort_key)


def recount(session: Session, sub: Submission) -> None:
    rows = answers_of(session, sub.id)
    sub.question_count = sum(a.status != UNGRADED for a in rows)
    sub.correct_count = sum(a.status == CORRECT for a in rows)
    session.add(sub)


def _mark_edited(session: Session, sub: Submission) -> None:
    result = dict(sub.result)
    result["edited"] = True
    sub.result = result  # reassign so SQLAlchemy sees the JSON change
    session.add(sub)


def _finish(a: Answer, suggestion: str = "") -> None:
    """Error type follows the status: blank <-> 未作答, correct/ungraded have none."""
    if a.status == BLANK:
        a.error_type = UNANSWERED
    elif a.status == WRONG:
        guess = judge.guess_error_type(a.kind, a.user_answer, a.accepted)
        if guess in STRING_ERROR_TYPES:
            a.error_type = guess
        elif suggestion in ERROR_TYPES and suggestion != UNANSWERED:
            a.error_type = suggestion
        else:
            a.error_type = guess if guess and guess != UNANSWERED else "其他"
    else:
        a.error_type = ""


def _judge(rows: Iterable[Answer], all_rows: Sequence[Answer]) -> None:
    """Re-decide rows (and their choose-TWO group mates). Manual verdicts are left alone."""
    rows = [a for a in rows if a.verdict_by != "manual"]
    groups = set()
    for a in rows:
        if a.kind == "multi" and a.group_nos:
            groups.add(a.group_nos)
            continue
        a.status = judge.judge(a.kind, a.user_answer, a.accepted, a.options)
        _finish(a, a.error_type)
    now_ids = {id(a) for a in rows}
    for g in groups:
        mates = sorted((x for x in all_rows if x.kind == "multi" and x.group_nos == g), key=sort_key)
        options = next((x.options for x in mates if x.options), {})
        for x, status in zip(mates, judge.judge_group([(x.user_answer, x.accepted) for x in mates], options)):
            # A mate whose answer was never seen stays ungraded until it is filled in.
            if x.verdict_by == "manual" or (id(x) not in now_ids and x.status == UNGRADED):
                continue
            x.status = status
            _finish(x, x.error_type)


def _guess_kind(value: str) -> str:
    v = judge.clean(value)
    if re.fullmatch(r"[A-Ha-h]", v):
        return "choice"
    if judge.canon("tfng", v, {}) in judge.TFNG.values():
        return "tfng"
    return "fill"


def _expand_nos(raw: str) -> list[str]:
    """'25-26' / '25 & 26' -> ['25', '26']; '37' -> ['37']."""
    s = clean_no(raw)
    m = re.fullmatch(r"(\d+)\s*(?:-|–|~|to|&|,|、)\s*(\d+)", s)
    if m and 0 < int(m.group(2)) - int(m.group(1)) < 5:
        return [str(n) for n in range(int(m.group(1)), int(m.group(2)) + 1)]
    return [s] if s else []


def _options(q: dict, kind: str) -> dict:
    if kind not in OPTION_KINDS:
        return {}
    out = {}
    for o in q.get("options") or []:
        letter = judge.clean(o.get("letter", "")).upper().strip(".")
        if letter and letter not in out:
            out[letter] = judge.clean(o.get("text", ""))
    return out


def _new_answer(sub: Submission, no: str, now: datetime, **fields) -> Answer:
    return Answer(submission_id=sub.id, skill=sub.skill, created_at=now, question_no=no, **fields)


def build_answers(session: Session, sub: Submission, questions: Sequence[dict], question_range: dict,
                  overrides: dict[str, str], now: datetime) -> list[Answer]:
    """Turn Claude's per-question reading into Answer rows and judge them.

    overrides: answers the student typed separately ({"27": "A"}), e.g. multiple-choice
    picks that were lost when copying from 雅思哥; they win over what Claude read.
    """
    rows: dict[str, Answer] = {}
    hidden: set[str] = set()
    for q in questions:
        kind = q.get("kind") if q.get("kind") in ANSWER_KINDS else "fill"
        nos = _expand_nos(q.get("question_no", ""))
        users = [q.get("user_answer", "")]
        group = ""
        if len(nos) > 1:  # one item for a whole choose-TWO set
            kind = "multi"
            users = _SINGLE_LETTER.findall(judge.clean(users[0]))
        if kind == "multi":
            group = judge.clean(q.get("group", "")) or (f"{nos[0]}-{nos[-1]}" if len(nos) > 1 else "")
        options = _options(q, kind)
        for i, no in enumerate(nos):
            if no in rows:
                continue
            visible = bool(q.get("answer_visible", True))
            user = users[i] if i < len(users) else ""
            rows[no] = _new_answer(
                sub, no, now, kind=kind, group_nos=group, question=judge.clean(q.get("question", "")),
                options=options, user_answer=judge.canon(kind, user, options) if visible else "",
                accepted=judge.split_key(kind, q.get("answer_key", ""), options),
                key_source=q.get("key_source") or "page", status=UNGRADED,
                error_type=q.get("error_type", ""), note=q.get("note", ""),
                explanation=q.get("explanation", ""), evidence=q.get("evidence", ""), tip=q.get("tip", ""),
            )
            if not visible:
                hidden.add(no)

    for raw_no, user in overrides.items():
        no = clean_no(raw_no)
        if not no:
            continue
        a = rows.get(no) or rows.setdefault(no, _new_answer(sub, no, now, kind=_guess_kind(user)))
        a.user_answer = judge.canon(a.kind, user, a.options)
        hidden.discard(no)

    # Questions Claude skipped inside the stated range become ungraded rows to fill in,
    # unless the range looks wrong (far more gaps than questions read).
    first, last = int(question_range.get("first") or 0), int(question_range.get("last") or 0)
    if 0 < first <= last:
        gaps = [str(n) for n in range(first, last + 1) if str(n) not in rows]
        if len(gaps) <= max(3, len(rows) // 2):
            for no in gaps:
                rows[no] = _new_answer(sub, no, now)
                hidden.add(no)

    for a in rows.values():
        session.add(a)
    all_rows = list(rows.values())
    _judge([a for a in all_rows if a.question_no not in hidden], all_rows)
    return all_rows


def needs_explanation(a: Answer) -> bool:
    if a.status == UNGRADED:
        return bool(a.user_answer) and not a.accepted  # answered, but no key to compare with
    return a.is_mistake and not a.explanation.strip()


def _images(session: Session, sub: Submission) -> list[tuple[str, bytes]]:
    return [(i.media_type, i.data) for i in
            session.exec(select(SubmissionImage).where(SubmissionImage.submission_id == sub.id)).all()]


def explain_rows(session: Session, sub: Submission, rows: Sequence[Answer], all_rows: Sequence[Answer],
                 explain_fn: ExplainFn | None = None, images: Sequence[tuple[str, bytes]] | None = None) -> None:
    """Ask Claude for explanations (and a key where there is none), then judge again."""
    if not rows:
        return
    items = (explain_fn or grader.explain)(sub.skill, sub.raw_text, _images(session, sub) if images is None else images, [
        {"question_no": a.question_no, "kind": a.kind, "question": a.question, "options": a.options,
         "user_answer": a.user_answer, "answer_key": " / ".join(a.accepted)} for a in rows])
    by_no = {a.question_no: a for a in rows}
    for it in items:
        a = by_no.get(clean_no(it.get("question_no", "")))
        if a is None:
            continue
        if not a.accepted:
            if it.get("kind") in ANSWER_KINDS and it["kind"] != a.kind:
                a.kind = it["kind"]
                a.options = a.options or _options(it, a.kind)
                a.user_answer = judge.canon(a.kind, a.user_answer, a.options)
            a.options = a.options or _options(it, a.kind)
            a.accepted = judge.split_key(a.kind, it.get("answer_key", ""), a.options)
            a.key_source = it.get("key_source") or "coach"
        a.question = a.question or judge.clean(it.get("question", ""))
        for f in ("note", "explanation", "evidence", "tip"):
            if it.get(f):
                setattr(a, f, it[f])
        if it.get("error_type"):
            a.error_type = it["error_type"]
    _judge(rows, all_rows)


@dataclass
class FillResult:
    graded: int
    correct: int
    warning: str = ""


def fill_answers(session: Session, sub: Submission, answers: Sequence[tuple[str, str, str]],
                 now: datetime, explain_fn: ExplainFn | None = None) -> FillResult:
    """Answers filled in after grading (web form or LINE 補).

    answers: (question_no, user_answer, correct_answer_or_empty). Re-answering a question
    replaces its answer. With a known key the verdict is immediate; Claude is only asked
    for explanations of wrong answers and for keys that are missing.
    """
    all_rows = answers_of(session, sub.id)
    rows = {a.question_no: a for a in all_rows}
    touched: list[Answer] = []
    for raw_no, user, correct in answers:
        no = clean_no(raw_no)
        if not no or any(a.question_no == no for a in touched):
            continue
        a = rows.get(no)
        if a is None:
            a = rows[no] = _new_answer(sub, no, now, kind=_guess_kind(correct or user))
            all_rows.append(a)
            session.add(a)
        a.user_answer = judge.canon(a.kind, user, a.options)
        if correct.strip():
            a.accepted = judge.split_key(a.kind, correct, a.options)
            a.key_source = "user"
        a.verdict_by = "auto"
        touched.append(a)
    if not touched:
        return FillResult(0, 0)

    _judge(touched, all_rows)
    need = [a for a in touched if a.is_mistake or not a.accepted]
    warning = ""
    try:
        explain_rows(session, sub, need, all_rows, explain_fn)
    except grader.GradingError as e:
        warning = f"對錯已更新，但解析沒有產生：{e}"
    recount(session, sub)
    session.commit()
    return FillResult(len(touched), sum(a.status == CORRECT for a in touched), warning)


def mark_correct(session: Session, a: Answer) -> None:
    """「其實答對了」: the student's answer is accepted for this question from now on."""
    if a.user_answer and a.user_answer not in a.accepted:
        a.accepted = [*a.accepted, a.user_answer]
    a.status, a.verdict_by, a.error_type = CORRECT, "manual", ""
    a.note = a.note or "（手動改為答對）"
    _save_manual(session, a)


def mark_wrong(session: Session, a: Answer, user_answer: str, error_type: str) -> None:
    """「其實答錯了」: user_answer is what the student really wrote (blank = unanswered)."""
    a.user_answer = judge.canon(a.kind, user_answer, a.options)
    a.status = WRONG if a.user_answer else BLANK
    a.verdict_by = "manual"
    if a.status == BLANK:
        a.error_type = UNANSWERED
    else:
        a.error_type = error_type if error_type in ERROR_TYPES and error_type != UNANSWERED else "其他"
    a.explanation = a.explanation or "（手動改為答錯）"
    _save_manual(session, a)


def edit_answer(session: Session, a: Answer, fields: dict) -> str:
    """Edit a question from the 修改這題 form. Returns the new status.

    Raises ValueError if the new question number is already used in this submission.
    """
    all_rows = answers_of(session, a.submission_id)
    new_no = clean_no(fields.get("question_no", a.question_no)) or a.question_no
    if new_no != a.question_no and any(x.question_no == new_no for x in all_rows if x.id != a.id):
        raise ValueError(f"第 {new_no} 題已經存在，請直接修改那一題。")
    a.question_no = new_no
    for f in ("question", "explanation", "tip"):
        if f in fields:
            setattr(a, f, str(fields[f]).strip())
    old_type = a.error_type
    changed = False
    if "user_answer" in fields:
        value = judge.canon(a.kind, str(fields["user_answer"]), a.options)
        changed |= value != a.user_answer
        a.user_answer = value
    if "correct_answer" in fields:
        value = judge.split_key(a.kind, str(fields["correct_answer"]), a.options)
        if value != a.accepted:
            a.accepted, a.key_source, changed = value, "user", True
    if changed:
        a.verdict_by = "auto"
        _judge([a], all_rows)
    chosen = str(fields.get("error_type", ""))
    if a.status == WRONG and chosen != old_type and chosen in ERROR_TYPES and chosen != UNANSWERED:
        a.error_type = chosen
    _save_manual(session, a)
    return a.status


def _save_manual(session: Session, a: Answer) -> None:
    sub = session.get(Submission, a.submission_id)
    session.add(a)
    session.flush()
    recount(session, sub)
    _mark_edited(session, sub)
    session.commit()


def parse_answers(text: str) -> list[tuple[str, str]]:
    """Parse '27A 28 NOT GIVEN 29: ng' into [('27','A'), ('28','NOT GIVEN'), ('29','ng')]."""
    pairs: list[tuple[str, list[str]]] = []
    for tok in re.findall(r"\d+|[^\d\s,，;；:：、.]+", text):
        if tok.isdigit():
            pairs.append((tok, []))
        elif pairs:
            pairs[-1][1].append(tok)
    return [(no, " ".join(words)) for no, words in pairs]


def change_info(session: Session, sub: Submission, skill: str, book: str, test: str,
                part: str, title: str) -> None:
    """Fix a submission filed under the wrong skill or source."""
    if skill in SKILLS and skill != sub.skill:
        old = sub.skill
        sub.skill = skill
        for a in answers_of(session, sub.id):
            a.skill = skill
            session.add(a)
        st = get_settings(session)
        move_progress(session, st, get_or_create_day(session, st, sub.date), old, skill)
    sub.book, sub.test, sub.part, sub.title = (v.strip() for v in (book, test, part, title))
    session.add(sub)
    session.commit()


def delete_submission(session: Session, sub: Submission) -> None:
    """Delete a submission with its answers and screenshots, and take back its progress."""
    for model in (Answer, Mistake, SubmissionImage):
        for row in session.exec(select(model).where(model.submission_id == sub.id)).all():
            session.delete(row)
    skill, day_str = sub.skill, sub.date
    session.delete(sub)
    session.commit()
    st = get_settings(session)
    remove_progress(session, st, get_or_create_day(session, st, day_str), skill)
