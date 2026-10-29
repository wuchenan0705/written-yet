"""Daily goals, progress, streak, debt and leave rules."""
import math
from datetime import date, datetime, time, timedelta

from sqlmodel import Session, func, select

from app.models import (
    PENALTY_FIELDS,
    PENALTY_TOGGLES,
    SKILL_ZH,
    SKILLS,
    AppSettings,
    DayRecord,
    FineEntry,
)

COOLDOWN = timedelta(hours=24)
DAY_MINUTES = 24 * 60
TIME_FIELDS = ("morning_time", "evening_time", "deadline_time", "settle_time")


class SettingsError(ValueError):
    pass


def parse_hhmm(value: str) -> time:
    h, m = value.strip().split(":")
    return time(int(h), int(m))


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def day_start(st: AppSettings) -> int:
    """Clock minute at which a practice day begins: midnight, or the settle time when
    settlement is set for the next morning (the day then runs until it)."""
    return _minutes(parse_hhmm(st.settle_time)) if st.settle_next_day else 0


def practice_date(st: AppSettings, now: datetime) -> str:
    """The practice day `now` belongs to: 01:30 still counts as yesterday if it settles at 02:00 the next day."""
    return (now - timedelta(minutes=day_start(st))).date().isoformat()


def day_minute(st: AppSettings, now: datetime) -> int:
    """Minutes since midnight at the start of now's practice day (01:00 the next day = 1500)."""
    start = datetime.combine(date.fromisoformat(practice_date(st, now)), time())
    return int((now - start).total_seconds() // 60)


def setting_minute(st: AppSettings, field: str) -> int:
    """A time setting on the same scale as day_minute."""
    next_day = {"deadline_time": st.deadline_next_day, "settle_time": st.settle_next_day}.get(field, False)
    return _minutes(parse_hhmm(getattr(st, field))) + (DAY_MINUTES if next_day else 0)


def time_label(st: AppSettings, field: str) -> str:
    """'凌晨 01:00' for a next-morning time, else the time as set."""
    value = getattr(st, field)
    return f"凌晨 {value}" if setting_minute(st, field) >= DAY_MINUTES else value


def check_times(st: AppSettings) -> None:
    order = [setting_minute(st, f) for f in TIME_FIELDS]
    if order != sorted(order):
        raise SettingsError("時間順序要是：早上提醒 ≤ 晚上警告 ≤ 截止 ≤ 結算（隔天凌晨的時間排在當天之後）。")
    if st.settle_next_day and _minutes(parse_hhmm(st.settle_time)) > _minutes(parse_hhmm(st.morning_time)):
        raise SettingsError("隔天的結算要早於早上提醒，不然會和下一天重疊。")


def get_settings(session: Session) -> AppSettings:
    st = session.get(AppSettings, 1)
    if st is None:
        st = AppSettings(id=1)
        session.add(st)
        session.commit()
        session.refresh(st)
    return st


def active_goals(st: AppSettings) -> dict[str, int]:
    return {s: int(st.goals.get(s, 0)) for s in SKILLS if int(st.goals.get(s, 0)) > 0}


def get_or_create_day(session: Session, st: AppSettings, day_str: str) -> DayRecord:
    day = session.get(DayRecord, day_str)
    if day:
        return day
    prev_str = (date.fromisoformat(day_str) - timedelta(days=1)).isoformat()
    prev = session.get(DayRecord, prev_str)
    debt = prev.debt_out if prev and prev.settled else {}
    targets = {s: g + int(debt.get(s, 0)) for s, g in active_goals(st).items()}
    day = DayRecord(date=day_str, targets=targets, done={s: 0 for s in targets})
    session.add(day)
    session.commit()
    session.refresh(day)
    return day


def is_complete(day: DayRecord) -> bool:
    return bool(day.targets) and all(
        day.done.get(s, 0) >= t for s, t in day.targets.items()
    )


def totals(day: DayRecord) -> tuple[int, int]:
    done = sum(min(day.done.get(s, 0), t) for s, t in day.targets.items())
    return done, sum(day.targets.values())


def add_progress(session: Session, st: AppSettings, day: DayRecord, skill: str, n: int) -> bool:
    """Record n finished questions. Returns True if this finished the day."""
    done = dict(day.done)
    done[skill] = done.get(skill, 0) + n
    day.done = done
    finished = False
    if day.status == "open" and is_complete(day):
        day.status = "completed"
        st.streak += 1
        st.best_streak = max(st.best_streak, st.streak)
        finished = True
    session.add(day)
    session.add(st)
    session.commit()
    return finished


def _recheck_completion(st: AppSettings, day: DayRecord) -> None:
    """Before settlement, completion and streak follow the corrected counts.
    Once a day is settled its outcome stays as it was."""
    if day.settled:
        return
    if day.status == "completed" and not is_complete(day):
        day.status = "open"
        st.streak = max(0, st.streak - 1)
    elif day.status == "open" and is_complete(day):
        day.status = "completed"
        st.streak += 1
        st.best_streak = max(st.best_streak, st.streak)


def move_progress(session: Session, st: AppSettings, day: DayRecord, old: str, new: str) -> None:
    """Move one finished set from skill `old` to `new` (a submission was filed under the wrong skill)."""
    done = dict(day.done)
    done[old] = max(0, done.get(old, 0) - 1)
    done[new] = done.get(new, 0) + 1
    day.done = done
    _recheck_completion(st, day)
    session.add(day)
    session.add(st)
    session.commit()


def remove_progress(session: Session, st: AppSettings, day: DayRecord, skill: str) -> None:
    """Take back one finished set (a submission was deleted)."""
    done = dict(day.done)
    done[skill] = max(0, done.get(skill, 0) - 1)
    day.done = done
    _recheck_completion(st, day)
    session.add(day)
    session.add(st)
    session.commit()


def compute_debt(st: AppSettings, day: DayRecord) -> dict[str, int]:
    """Shortfall carried into tomorrow, capped at goal * debt_cap in total."""
    out = {}
    for s, g in active_goals(st).items():
        shortfall = max(0, day.targets.get(s, g) - day.done.get(s, 0))
        nxt = min(g + shortfall, math.ceil(g * st.debt_cap))
        if nxt > g:
            out[s] = nxt - g
    return out


def carried_debt(st: AppSettings, day: DayRecord) -> dict[str, int]:
    """Existing debt passed through unchanged (used on leave days)."""
    goals = active_goals(st)
    return {s: day.targets[s] - g for s, g in goals.items() if day.targets.get(s, 0) > g}


def leaves_used(session: Session, day_str: str) -> int:
    month = day_str[:7]
    return session.exec(
        select(func.count()).select_from(DayRecord).where(
            DayRecord.status == "leave", DayRecord.date.startswith(month)
        )
    ).one()


def use_leave(session: Session, st: AppSettings, day: DayRecord) -> str:
    if day.status == "leave":
        return "今天已經請過假了。"
    if day.status != "open" or day.settled:
        return "今天已經結算或完成，不能請假。"
    used = leaves_used(session, day.date)
    if used >= st.leave_per_month:
        return f"這個月的請假額度（{st.leave_per_month} 次）已經用完了，乖乖做題吧 💪"
    day.status = "leave"
    session.add(day)
    session.commit()
    return f"🛌 已請假，今天不會懲罰，連續紀錄保留。本月剩 {st.leave_per_month - used - 1} 次。"


def outstanding_fines(session: Session) -> int:
    return session.exec(
        select(func.coalesce(func.sum(FineEntry.amount), 0)).where(FineEntry.paid == False)  # noqa: E712
    ).one()


def progress_text(st: AppSettings, day: DayRecord) -> str:
    lines = [f"📅 {day.date} 進度"]
    for s, t in day.targets.items():
        d = day.done.get(s, 0)
        mark = "✅" if d >= t else "⬜"
        debt = t - int(st.goals.get(s, 0))
        extra = f"（含欠債 {debt} 篇）" if debt > 0 else ""
        lines.append(f"{mark} {SKILL_ZH[s]} {d}/{t} 篇{extra}")
    status = {"completed": "🎉 今天完成了！", "leave": "🛌 今天請假", "failed": "❌ 今天未完成"}.get(day.status)
    if status:
        lines.append(status)
    lines.append(f"🔥 連續 {st.streak} 天（最佳 {st.best_streak}）")
    return "\n".join(lines)


def _coerce(field: str, raw):
    default = AppSettings.model_fields[field].default
    if isinstance(default, bool):
        return raw in (True, "on", "true", "1", 1)
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    return str(raw)


def update_settings(session: Session, st: AppSettings, form: dict, now: datetime) -> list[str]:
    """Apply a settings form. Penalty changes wait 24h unless they switch a penalty on."""
    notes = []
    goals = dict(st.goals)
    for s in SKILLS:
        if f"goal_{s}" in form:
            goals[s] = max(0, int(form[f"goal_{s}"] or 0))
    st.goals = goals
    for f in ("display_name", *TIME_FIELDS):
        if f in form:
            setattr(st, f, str(form[f]).strip())
    for f in ("deadline_next_day", "settle_next_day"):
        if f in form:
            setattr(st, f, form[f] in ("1", "on", "true", True))
    check_times(st)
    if "push_monthly_limit" in form:
        st.push_monthly_limit = int(form["push_monthly_limit"])

    pending = dict(st.pending_penalty or {})
    for f in PENALTY_FIELDS:
        new = _coerce(f, form.get(f, False)) if f in PENALTY_TOGGLES else (
            _coerce(f, form[f]) if f in form else None
        )
        if new is None or new == getattr(st, f):
            pending.pop(f, None)
            continue
        if f in PENALTY_TOGGLES and new is True:
            setattr(st, f, True)
            pending.pop(f, None)
        else:
            pending[f] = new
    if pending:
        if pending != (st.pending_penalty or {}) or st.pending_apply_at is None:
            st.pending_apply_at = now + COOLDOWN
        notes.append(f"懲罰相關的放寬/修改將於 {st.pending_apply_at:%m/%d %H:%M} 生效（24 小時冷靜期）。")
    else:
        st.pending_apply_at = None
    st.pending_penalty = pending or None
    session.add(st)
    session.commit()
    return notes


def apply_pending(session: Session, st: AppSettings, now: datetime) -> bool:
    if not st.pending_penalty or not st.pending_apply_at or now < st.pending_apply_at:
        return False
    for f, v in st.pending_penalty.items():
        if f in PENALTY_FIELDS:
            setattr(st, f, v)
    st.pending_penalty = None
    st.pending_apply_at = None
    session.add(st)
    session.commit()
    return True
