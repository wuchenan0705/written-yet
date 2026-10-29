"""A once-a-minute tick that drives reminders, bombing and settlement.

Reading the times from the DB on every tick means settings changes apply
without rescheduling, and a restarted server catches up on unsettled days.
"""
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session, select

from app import clock, push
from app.db import engine
from app.logic import (
    apply_pending, day_minute, get_or_create_day, get_settings, is_complete, parse_hhmm, practice_date,
    progress_text, settle_minute, time_label,
)
from app.models import DayRecord
from app.penalties import bomb_tick, settle_day

log = logging.getLogger(__name__)


def tick(session: Session, now: datetime) -> None:
    st = get_settings(session)
    apply_pending(session, st, now)
    today = practice_date(st, now)

    for old in session.exec(
        select(DayRecord).where(DayRecord.settled == False, DayRecord.date < today)  # noqa: E712
    ).all():
        settle_day(session, st, old, now)

    day = get_or_create_day(session, st, today)
    t = day_minute(st, now.time())
    deadline = day_minute(st, parse_hhmm(st.deadline_time))

    if not day.morning_sent and day_minute(st, parse_hhmm(st.morning_time)) <= t < deadline:
        day.morning_sent = True
        session.add(day)
        session.commit()
        push.send_owner(session, st, now, "☀️ 早安！今天的雅思目標：\n" + progress_text(st, day), "morning")

    if (not day.evening_sent and day.status == "open" and not is_complete(day)
            and day_minute(st, parse_hhmm(st.evening_time)) <= t < deadline):
        day.evening_sent = True
        session.add(day)
        session.commit()
        push.send_owner(
            session, st, now,
            f"⚠️ 寫未？今天還沒完成，{time_label(st, st.deadline_time)} 截止！\n" + progress_text(st, day),
            "evening",
        )

    bomb_tick(session, st, day, now)

    if not day.settled and t >= settle_minute(st):
        settle_day(session, st, day, now)


def _run() -> None:
    try:
        with Session(engine) as session:
            tick(session, clock.now())
    except Exception:
        log.exception("tick failed")


def start() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=clock.TZ)
    sched.add_job(_run, "cron", second=0, max_instances=1, coalesce=True)
    sched.start()
    return sched
