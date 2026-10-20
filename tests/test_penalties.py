from datetime import datetime

from app import push
from app.logic import add_progress, get_or_create_day, get_settings, outstanding_fines
from app.models import PushLog
from app.penalties import bomb_tick, settle_day
from app.scheduler import tick


def setup(session):
    st = get_settings(session)
    st.goals = {"listening": 0, "reading": 10, "writing": 0, "speaking": 0}
    st.owner_user_id = "U1"
    st.streak = 5
    st.best_streak = 5
    session.add(st)
    session.commit()
    return st


def test_failed_day_applies_all_enabled_penalties(session, transport):
    st = setup(session)
    st.pen_fine = st.pen_shame = True
    st.shame_group_id = "G1"
    day = get_or_create_day(session, st, "2026-10-20")
    add_progress(session, st, day, "reading", 4)
    text = settle_day(session, st, day, datetime(2026, 10, 20, 23, 59))

    assert day.status == "failed" and st.streak == 0
    assert day.debt_out == {"reading": 6}
    assert outstanding_fines(session) == 100
    group_msgs = [t for to, t in transport.sent if to == "G1"]
    assert group_msgs and "4/10" in group_msgs[0] and "5 天" in group_msgs[0]
    assert ("U1", text) in transport.sent
    assert session.get(PushLog, 1).cost == 3  # group push charged per member


def test_failed_day_with_penalties_off(session, transport):
    st = setup(session)
    st.pen_streak = False
    day = get_or_create_day(session, st, "2026-10-20")
    settle_day(session, st, day, datetime(2026, 10, 20, 23, 59))
    assert st.streak == 5 and day.debt_out == {} and outstanding_fines(session) == 0


def test_leave_day_keeps_streak_and_existing_debt(session, transport):
    st = setup(session)
    day = get_or_create_day(session, st, "2026-10-20")
    day.targets = {"reading": 14}
    day.status = "leave"
    settle_day(session, st, day, datetime(2026, 10, 20, 23, 59))
    assert st.streak == 5 and day.debt_out == {"reading": 4}


def test_bombing_escalates_with_intervals(session, transport):
    st = setup(session)
    st.pen_bomb = True
    st.bomb_intervals = "30,10"
    st.bomb_max_per_day = 3
    day = get_or_create_day(session, st, "2026-10-20")
    times = [(22, 59, False), (23, 0, True), (23, 29, False), (23, 30, True),
             (23, 39, False), (23, 40, True), (23, 50, False)]
    for h, m, expected in times:
        assert bomb_tick(session, st, day, datetime(2026, 10, 20, h, m)) is expected, (h, m)


def test_bombing_respects_quota_reserve(session, transport):
    st = setup(session)
    st.pen_bomb = True
    st.push_monthly_limit = 200
    day = get_or_create_day(session, st, "2026-10-20")
    # 11 days left after the 20th -> reserve 11*3+1 = 34; leave exactly 34
    session.add(PushLog(sent_at=datetime(2026, 10, 5), kind="x", target="U1", cost=166))
    session.commit()
    assert not push.can_push(session, st, datetime(2026, 10, 20, 23, 0), "bomb")
    assert push.can_push(session, st, datetime(2026, 10, 20, 23, 0), "settle")
    assert bomb_tick(session, st, day, datetime(2026, 10, 20, 23, 0)) is False


def test_tick_full_day(session, transport):
    st = setup(session)
    tick(session, datetime(2026, 10, 20, 8, 0))
    assert transport.sent == []
    tick(session, datetime(2026, 10, 20, 9, 0))
    tick(session, datetime(2026, 10, 20, 9, 1))
    assert len(transport.sent) == 1 and "早安" in transport.sent[0][1]
    tick(session, datetime(2026, 10, 20, 21, 0))
    assert "寫未？" in transport.sent[-1][1]
    tick(session, datetime(2026, 10, 20, 23, 59))
    assert "結算" in transport.sent[-1][1] and st.streak == 0
    tick(session, datetime(2026, 10, 21, 0, 0))
    day2 = get_or_create_day(session, st, "2026-10-21")
    assert day2.targets == {"reading": 20}


def test_tick_catches_up_missed_settlement(session, transport):
    st = setup(session)
    get_or_create_day(session, st, "2026-10-19")
    tick(session, datetime(2026, 10, 20, 8, 0))
    assert any("2026-10-19 結算" in t for _, t in transport.sent)
