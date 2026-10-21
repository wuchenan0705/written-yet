"""Shared submit flow for the web form and LINE."""
from collections import Counter
from datetime import datetime
from typing import Callable, Sequence

from sqlmodel import Session

from app import config, grader
from app.logic import add_progress, get_or_create_day, get_settings, progress_text
from app.models import SKILL_ZH, Mistake, Submission, SubmissionImage

GradeFn = Callable[..., dict]
SOURCE_FIELDS = ("book", "test", "part", "title")
Images = Sequence[tuple[str, bytes]]


def process(session: Session, skill: str, text: str, source: str, now: datetime,
            images: Images = (), grade_fn: GradeFn | None = None,
            book_info: dict | None = None) -> tuple[Submission, bool]:
    """Grade, store, and count progress. Returns (submission, finished_today).

    book_info: optional book/test/part/title typed by the user; blanks fall back to
    what Claude read from the screenshot or text.
    """
    result = (grade_fn or grader.grade)(skill, text, images)
    detected = result.get("source") or {}
    typed = book_info or {}
    src = {k: (typed.get(k) or detected.get(k) or "").strip() for k in SOURCE_FIELDS}
    st = get_settings(session)
    day_str = now.date().isoformat()
    sub = Submission(
        created_at=now, date=day_str, skill=skill, source=source, raw_text=text,
        question_count=result["question_count"], correct_count=result["correct_count"],
        result=result, **src,
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)
    for m in result.get("mistakes", []):
        session.add(Mistake(submission_id=sub.id, created_at=now, skill=skill, **m))
    for media_type, data in images:
        session.add(SubmissionImage(submission_id=sub.id, media_type=media_type, data=data))
    session.commit()

    day = get_or_create_day(session, st, day_str)
    finished = add_progress(session, st, day, skill, 1)  # goals count sets, not questions
    return sub, finished


def line_summary(session: Session, sub: Submission, finished: bool) -> str:
    st = get_settings(session)
    r = sub.result
    lines = [f"📝 {SKILL_ZH[sub.skill]}"]
    if sub.source_label:
        lines.insert(0, f"📖 {sub.source_label}")
    if sub.skill in ("listening", "reading"):
        lines[-1] += f" {sub.correct_count}/{sub.question_count} 題正確"
    elif r.get("band_estimate"):
        lines[-1] += f" 預估 Band {r['band_estimate']}"
    if r.get("summary"):
        lines.append(r["summary"])
    if r.get("missing_answers"):
        nos = r["missing_answers"]
        lines.append(f"⚠️ 第 {'、'.join(nos)} 題看不到你的答案（沒計分）")
        lines.append(f"補答案：傳「補 {nos[0]} A {nos[-1]} NG」這樣的格式" if len(nos) > 1 else f"補答案：傳「補 {nos[0]} 你的答案」")
    top = Counter(m["error_type"] for m in r.get("mistakes", [])).most_common(3)
    if top:
        lines.append("錯誤類型：" + "、".join(f"{t}×{n}" for t, n in top))
    lines.append(f"完整解析：{config.BASE_URL}/submissions/{sub.id}")
    lines.append("")
    if finished:
        lines.append("🎉 今日目標全部完成！")
    day = get_or_create_day(session, st, sub.date)
    lines.append(progress_text(st, day))
    return "\n".join(lines)
