"""LINE push messages with a monthly quota guard.

LINE counts one message per recipient, so a push to a group costs as many
messages as the group has members. Replies are free and do not go through here.
"""
import calendar
import logging
from datetime import datetime
from typing import Optional, Protocol

from sqlmodel import Session, func, select

from app.models import AppSettings, PushLog

log = logging.getLogger(__name__)

CORE_PUSHES_PER_DAY = 3  # morning, evening, settlement
LOW_PRIORITY = {"bomb"}


class Transport(Protocol):
    def push(self, to: str, text: str) -> None: ...
    def group_member_count(self, group_id: str) -> int: ...


_transport: Optional[Transport] = None


def set_transport(t: Optional[Transport]) -> None:
    global _transport
    _transport = t


def month_used(session: Session, now: datetime) -> int:
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return session.exec(
        select(func.coalesce(func.sum(PushLog.cost), 0)).where(PushLog.sent_at >= start)
    ).one()


def remaining(session: Session, st: AppSettings, now: datetime) -> int:
    return st.push_monthly_limit - month_used(session, now)


def can_push(session: Session, st: AppSettings, now: datetime, kind: str, cost: int = 1) -> bool:
    left = remaining(session, st, now)
    if kind in LOW_PRIORITY:
        days_after_today = calendar.monthrange(now.year, now.month)[1] - now.day
        left -= days_after_today * CORE_PUSHES_PER_DAY + 1  # keep tonight's settlement
    return left >= cost


def send(session: Session, st: AppSettings, now: datetime, to: Optional[str], text: str,
         kind: str, cost: int = 1) -> bool:
    if not to or _transport is None:
        return False
    if not can_push(session, st, now, kind, cost):
        log.info("push %s skipped: monthly quota", kind)
        return False
    try:
        _transport.push(to, text[:4900])
    except Exception:
        log.exception("push %s failed", kind)
        return False
    session.add(PushLog(sent_at=now, kind=kind, target=to, cost=cost))
    session.commit()
    return True


def send_owner(session: Session, st: AppSettings, now: datetime, text: str, kind: str) -> bool:
    return send(session, st, now, st.owner_user_id, text, kind)


def send_group(session: Session, st: AppSettings, now: datetime, group_id: str, text: str,
               kind: str) -> bool:
    if _transport is None:
        return False
    try:
        cost = max(1, _transport.group_member_count(group_id))
    except Exception:
        log.exception("group member count failed")
        cost = 10
    return send(session, st, now, group_id, text, kind, cost)
