"""Shared submit flow for the web form and LINE."""
import logging
from collections import Counter
from datetime import datetime
from typing import Callable, Sequence

from sqlmodel import Session

from app import config, grader, review
from app.logic import add_progress, get_or_create_day, get_settings, current_date, progress_text
from app.models import OBJECTIVE_SKILLS, SKILL_ZH, UNGRADED, Submission, SubmissionImage

log = logging.getLogger(__name__)
GradeFn = Callable[..., dict]
SOURCE_FIELDS = ("book", "test", "part", "title")
# Per-question data lives in Answer rows, not in Submission.result.
ROW_FIELDS = ("questions", "question_range")
Images = Sequence[tuple[str, bytes]]


def process(session: Session, skill: str, text: str, source: str, now: datetime,
            images: Images = (), grade_fn: GradeFn | None = None,
            book_info: dict | None = None, answers: Sequence[tuple[str, str]] = (),
            explain_fn: review.ExplainFn | None = None) -> tuple[Submission, bool]:
    """Grade, store, and count progress. Returns (submission, finished_today).

    book_info: optional book/test/part/title typed by the user; blanks fall back to
    what Claude read from the screenshot or text.
    answers: (question_no, answer) the student typed separately; they override what
    Claude read for those questions.
    """
    prompt_text = text
    if answers:
        prompt_text += "\n\n我的答案：" + " ".join(f"{no} {a}" for no, a in answers)
    result = (grade_fn or grader.grade)(skill, prompt_text, images)
    detected = result.get("source") or {}
    typed = book_info or {}
    src = {k: (typed.get(k) or detected.get(k) or "").strip() for k in SOURCE_FIELDS}
    st = get_settings(session)
    day_str = current_date(session, st, now)
    sub = Submission(
        created_at=now, date=day_str, skill=skill, source=source, raw_text=prompt_text,
        question_count=result.get("question_count", 0), correct_count=0,
        result={k: v for k, v in result.items() if k not in ROW_FIELDS}, **src,
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)
    for media_type, data in images:
        session.add(SubmissionImage(submission_id=sub.id, media_type=media_type, data=data))
    if skill in OBJECTIVE_SKILLS:
        rows = review.build_answers(session, sub, result.get("questions") or [],
                                    result.get("question_range") or {}, dict(answers), now)
        try:
            review.explain_rows(session, sub, [a for a in rows if review.needs_explanation(a)], rows,
                                explain_fn, images=images)
        except grader.GradingError:
            log.warning("explanations for submission %s failed", sub.id, exc_info=True)
        session.flush()
        review.recount(session, sub)
    session.commit()

    day = get_or_create_day(session, st, day_str)
    finished = add_progress(session, st, day, skill, 1)  # goals count sets, not questions
    return sub, finished


def line_summary(session: Session, sub: Submission, finished: bool) -> str:
    st = get_settings(session)
    r = sub.result
    rows = review.answers_of(session, sub.id)
    lines = [f"📝 {SKILL_ZH[sub.skill]}"]
    if sub.source_label:
        lines.insert(0, f"📖 {sub.source_label}")
    if sub.skill in OBJECTIVE_SKILLS:
        lines[-1] += f" {sub.correct_count}/{sub.question_count} 題正確"
    elif r.get("band_estimate"):
        lines[-1] += f" 預估 Band {r['band_estimate']}"
    if r.get("summary"):
        lines.append(r["summary"])
    nos = [a.question_no for a in rows if a.status == UNGRADED]
    if nos:
        lines.append(f"⚠️ 第 {'、'.join(nos)} 題看不到你的答案（沒計分）")
        lines.append(f"補答案：傳「補 {nos[0]} A {nos[-1]} NG」這樣的格式" if len(nos) > 1 else f"補答案：傳「補 {nos[0]} 你的答案」")
    top = Counter(a.error_type for a in rows if a.is_mistake).most_common(3)
    if top:
        lines.append("錯誤類型：" + "、".join(f"{t}×{n}" for t, n in top))
    lines.append(f"完整解析：{config.BASE_URL}/submissions/{sub.id}")
    lines.append("")
    if finished:
        lines.append("🎉 今日目標全部完成！")
    day = get_or_create_day(session, st, sub.date)
    lines.append(progress_text(st, day))
    return "\n".join(lines)
