from datetime import datetime

from app.logic import (
    add_progress, apply_pending, compute_debt, get_or_create_day, get_settings,
    update_settings, use_leave,
)
from app.models import DayRecord


def setup(session, goals=None):
    st = get_settings(session)
    st.goals = goals or {"listening": 10, "reading": 13, "writing": 0, "speaking": 0}
    session.add(st)
    session.commit()
    return st


def test_day_targets_skip_zero_goals(session):
    st = setup(session)
    day = get_or_create_day(session, st, "2026-10-20")
    assert day.targets == {"listening": 10, "reading": 13}


def test_completion_increments_streak_once(session):
    st = setup(session)
    day = get_or_create_day(session, st, "2026-10-20")
    assert add_progress(session, st, day, "listening", 10) is False
    assert add_progress(session, st, day, "reading", 13) is True
    assert add_progress(session, st, day, "reading", 5) is False
    assert st.streak == 1 and st.best_streak == 1 and day.status == "completed"


def test_debt_is_capped(session):
    st = setup(session)
    st.debt_cap = 2.0
    day = DayRecord(date="2026-10-20", targets={"listening": 18, "reading": 13},
                    done={"listening": 0, "reading": 10})
    # listening: 10 + 18 shortfall capped at 20 -> debt 10; reading: 10 + 3 = 13 -> debt 3
    assert compute_debt(st, day) == {"listening": 10, "reading": 3}


def test_next_day_inherits_debt_only_when_settled(session):
    st = setup(session)
    prev = DayRecord(date="2026-10-19", targets={}, done={}, debt_out={"reading": 5}, settled=True)
    session.add(prev)
    session.commit()
    day = get_or_create_day(session, st, "2026-10-20")
    assert day.targets == {"listening": 10, "reading": 18}


def test_leave_quota(session):
    st = setup(session)
    st.leave_per_month = 1
    d1 = get_or_create_day(session, st, "2026-10-01")
    assert "已請假" in use_leave(session, st, d1)
    d2 = get_or_create_day(session, st, "2026-10-02")
    assert "用完" in use_leave(session, st, d2)
    assert d2.status == "open"
    d3 = get_or_create_day(session, st, "2026-11-01")
    assert "已請假" in use_leave(session, st, d3)


def form(st, **over):
    f = {"goal_listening": "10", "goal_reading": "13", "goal_writing": "0", "goal_speaking": "0",
         "debt_cap": str(st.debt_cap), "shame_template": st.shame_template,
         "fine_amount": str(st.fine_amount), "fine_note": st.fine_note,
         "bomb_intervals": st.bomb_intervals, "bomb_max_per_day": str(st.bomb_max_per_day),
         "leave_per_month": str(st.leave_per_month)}
    for k in ("pen_streak", "pen_shame", "pen_fine", "pen_bomb"):
        if getattr(st, k):
            f[k] = "on"
    f.update(over)
    return {k: v for k, v in f.items() if v is not None}


def test_enabling_penalty_is_immediate_disabling_waits(session):
    st = setup(session)
    now = datetime(2026, 10, 20, 12, 0)
    update_settings(session, st, form(st, pen_fine="on"), now)
    assert st.pen_fine is True and st.pending_penalty is None

    notes = update_settings(session, st, form(st, pen_fine=None, fine_amount="10"), now)
    assert st.pen_fine is True and st.fine_amount == 100
    assert st.pending_penalty == {"pen_fine": False, "fine_amount": 10} and notes

    assert apply_pending(session, st, datetime(2026, 10, 21, 11, 59)) is False
    assert apply_pending(session, st, datetime(2026, 10, 21, 12, 0)) is True
    assert st.pen_fine is False and st.fine_amount == 10


def test_reverting_change_clears_pending(session):
    st = setup(session)
    now = datetime(2026, 10, 20, 12, 0)
    update_settings(session, st, form(st, pen_streak=None), now)
    assert st.pending_penalty == {"pen_streak": False}
    update_settings(session, st, form(st, pen_streak="on"), now)
    assert st.pending_penalty is None and st.pending_apply_at is None
