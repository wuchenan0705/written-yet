from datetime import datetime

from app import push
from app.logic import add_progress, get_or_create_day, get_settings, outstanding_fines
from app.models import DayRecord, PushLog
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


def late_night(session):
    st = setup(session)
    st.deadline_time, st.settle_time = "01:00", "02:00"
    st.deadline_next_day = st.settle_next_day = True
    st.pen_bomb, st.bomb_intervals = True, "30"
    session.add(st)
    session.commit()
    return st


def test_practice_day_runs_past_midnight(session):
    from app.logic import practice_date

    st = late_night(session)
    assert practice_date(st, datetime(2026, 10, 21, 1, 59)) == "2026-10-20"
    assert practice_date(st, datetime(2026, 10, 21, 2, 0)) == "2026-10-21"
    assert practice_date(st, datetime(2026, 10, 20, 23, 0)) == "2026-10-20"
    st.settle_next_day = False
    assert practice_date(st, datetime(2026, 10, 21, 1, 59)) == "2026-10-21"


def test_tick_with_deadline_and_settlement_after_midnight(session, transport):
    st = late_night(session)
    tick(session, datetime(2026, 10, 20, 9, 0))
    tick(session, datetime(2026, 10, 20, 21, 0))
    assert "凌晨 01:00 截止" in transport.sent[-1][1]
    tick(session, datetime(2026, 10, 20, 23, 59))
    day = get_or_create_day(session, st, "2026-10-20")
    assert not day.settled and day.bomb_count == 0  # not past the deadline yet
    tick(session, datetime(2026, 10, 21, 1, 0))
    assert day.bomb_count == 1 and not day.settled
    # Work done at 01:30 still counts for the 20th.
    from app import submissions
    from tests.fakes import q, result
    sub, _ = submissions.process(session, "reading", "x", "web", datetime(2026, 10, 21, 1, 30),
                                 grade_fn=lambda *a: result([q("1", user="a", key="a")]))
    assert sub.date == "2026-10-20" and day.done["reading"] == 1
    tick(session, datetime(2026, 10, 21, 2, 0))
    assert day.settled and any("2026-10-20 結算" in t for _, t in transport.sent)
    assert session.get(DayRecord, "2026-10-21") is not None


def test_settle_at_midnight(session, transport):
    st = setup(session)
    st.settle_time, st.settle_next_day = "00:00", True
    tick(session, datetime(2026, 10, 20, 23, 59))
    assert session.get(DayRecord, "2026-10-20").settled is False
    tick(session, datetime(2026, 10, 21, 0, 0))
    assert session.get(DayRecord, "2026-10-20").settled is True


def test_settings_page_shows_day_choice():
    from fastapi.testclient import TestClient

    from app.db import init_db
    from app.main import app

    init_db()
    with TestClient(app) as c:
        c.post("/login", data={"password": "pw"})
        assert "隔天凌晨" in c.get("/settings").text
        r = c.post("/settings", data={"deadline_time": "01:00", "deadline_next_day": "0", "settle_time": "23:59",
                                      "settle_next_day": "0", "morning_time": "09:00", "evening_time": "21:00"})
        assert "時間順序要是" in r.text


def test_settings_reject_out_of_order_times(session):
    import pytest
    from app.logic import SettingsError, update_settings

    st = setup(session)
    noon = datetime(2026, 10, 20, 12)
    update_settings(session, st, {"deadline_time": "01:00", "deadline_next_day": "1",
                                  "settle_time": "02:00", "settle_next_day": "1"}, noon)
    assert (st.deadline_time, st.settle_time, st.deadline_next_day, st.settle_next_day) == ("01:00", "02:00", True, True)
    with pytest.raises(SettingsError):  # next-morning deadline after a same-day settlement
        update_settings(session, st, {"deadline_next_day": "1", "settle_time": "23:59", "settle_next_day": "0"}, noon)
    session.rollback()
    with pytest.raises(SettingsError):  # same-day 01:00 deadline is before the morning reminder
        update_settings(session, st, {"deadline_time": "01:00", "deadline_next_day": "0",
                                      "settle_time": "23:59", "settle_next_day": "0"}, noon)
    session.rollback()
    with pytest.raises(SettingsError):  # settling after the morning reminder would overlap the next day
        update_settings(session, st, {"deadline_time": "08:00", "settle_time": "10:00", "settle_next_day": "1"}, noon)


def test_switching_to_next_morning_settlement_does_not_reopen_a_settled_day(session, transport):
    st = setup(session)
    tick(session, datetime(2026, 10, 29, 23, 59))  # settled under the old same-day rule
    tick(session, datetime(2026, 10, 30, 0, 0))
    st.settle_time, st.settle_next_day, st.deadline_time, st.deadline_next_day = "01:59", True, "01:58", True
    session.add(st)
    session.commit()
    from app import submissions
    from tests.fakes import q, result
    sub, _ = submissions.process(session, "reading", "x", "web", datetime(2026, 10, 30, 0, 22),
                                 grade_fn=lambda *a: result([q("1", user="a", key="a")]))
    assert sub.date == "2026-10-30"
    tick(session, datetime(2026, 10, 30, 0, 23))
    assert session.get(DayRecord, "2026-10-30").settled is False
