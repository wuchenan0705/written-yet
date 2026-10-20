"""End-of-day settlement, the four penalties, and the weekly report."""
from collections import Counter
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from app import push
from app.logic import carried_debt, compute_debt, is_complete, outstanding_fines, parse_hhmm, totals
from app.models import SKILL_ZH, AppSettings, DayRecord, FineEntry, Mistake, Submission

BOMB_LINES = [
    "⏰ 已經過截止時間了，今天的雅思還沒做完！",
    "⏰⏰ 還沒做？現在打開雅思哥，做完就不吵你。",
    "🚨 第 {n} 次提醒。每拖一分鐘，明天欠債就更多。",
    "🚨🚨 第 {n} 次！你的連續 {streak} 天紀錄快要沒了！",
    "💣 第 {n} 次轟炸。手機放下，題目打開。",
]


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def settle_day(session: Session, st: AppSettings, day: DayRecord, now: datetime) -> str:
    """Close a day: decide completed/failed/leave and apply enabled penalties."""
    if day.settled:
        return ""
    if day.status == "open":
        day.status = "completed" if is_complete(day) else "failed"

    lines = [f"🌙 {day.date} 結算"]
    if day.status == "completed":
        day.debt_out = {}
        lines.append(f"✅ 完成！連續 {st.streak} 天，繼續保持。")
    elif day.status == "leave":
        day.debt_out = carried_debt(st, day)
        lines.append("🛌 請假日，不懲罰。")
    else:
        done, target = totals(day)
        broken = st.streak
        lines.append(f"❌ 只完成 {done}/{target} 篇。")
        if st.pen_streak:
            st.streak = 0
            day.debt_out = compute_debt(st, day)
            lines.append(f"🔥 連續紀錄 {broken} 天 → 0")
            if day.debt_out:
                debt = "、".join(f"{SKILL_ZH[s]} +{n} 篇" for s, n in day.debt_out.items())
                lines.append(f"📈 明天欠債：{debt}")
        else:
            day.debt_out = {}
        if st.pen_fine:
            session.add(FineEntry(date=day.date, amount=st.fine_amount, note=st.fine_note))
            session.flush()
            lines.append(f"💸 罰金 +{st.fine_amount}，未付總額 {outstanding_fines(session)}（{st.fine_note}）")
        if st.pen_shame and st.shame_group_id:
            text = st.shame_template.format_map(
                _SafeDict(name=st.display_name, done=done, target=target, streak=broken)
            )
            sent = push.send_group(session, st, now, st.shame_group_id, text, "shame")
            lines.append("📢 已在監督群組公告。" if sent else "📢 群組公告失敗（推播額度不足？）")

    day.settled = True
    session.add(day)
    session.add(st)
    session.commit()

    if date.fromisoformat(day.date).weekday() == 6:
        lines.append("")
        lines.append(weekly_report(session, day.date))
    text = "\n".join(lines)
    push.send_owner(session, st, now, text, "settle")
    return text


def weekly_report(session: Session, end_str: str) -> str:
    end = date.fromisoformat(end_str)
    start_str = (end - timedelta(days=6)).isoformat()
    days = session.exec(
        select(DayRecord).where(DayRecord.date >= start_str, DayRecord.date <= end_str)
    ).all()
    subs = session.exec(
        select(Submission).where(Submission.date >= start_str, Submission.date <= end_str)
    ).all()
    mistakes = session.exec(
        select(Mistake).join(Submission, Mistake.submission_id == Submission.id).where(
            Submission.date >= start_str, Submission.date <= end_str
        )
    ).all()
    completed = sum(d.status == "completed" for d in days)
    lines = [f"📊 本週週報（{start_str} ~ {end_str}）", f"完成天數：{completed}/7"]
    for skill in ("listening", "reading", "writing", "speaking"):
        mine = [s for s in subs if s.skill == skill]
        if not mine:
            continue
        line = f"{SKILL_ZH[skill]}：{len(mine)} 篇"
        q = sum(s.question_count for s in mine)
        if skill in ("listening", "reading") and q:
            line += f"（{q} 題，正確率 {sum(s.correct_count for s in mine) * 100 // q}%）"
        lines.append(line)
    top = Counter(m.error_type for m in mistakes).most_common(3)
    if top:
        lines.append("最常錯：" + "、".join(f"{t}×{n}" for t, n in top))
    return "\n".join(lines)


def bomb_intervals(st: AppSettings) -> list[int]:
    try:
        vals = [max(1, int(x)) for x in st.bomb_intervals.split(",") if x.strip()]
    except ValueError:
        vals = []
    return vals or [30]


def bomb_tick(session: Session, st: AppSettings, day: DayRecord, now: datetime) -> bool:
    """Send an escalating reminder after the deadline if the day is still unfinished."""
    if not st.pen_bomb or day.status != "open" or day.settled:
        return False
    t = now.time()
    if not (parse_hhmm(st.deadline_time) <= t < parse_hhmm(st.settle_time)):
        return False
    if day.bomb_count >= st.bomb_max_per_day:
        return False
    if day.last_bomb_at is not None:
        steps = bomb_intervals(st)
        wait = steps[min(day.bomb_count - 1, len(steps) - 1)]
        if now - day.last_bomb_at < timedelta(minutes=wait):
            return False
    n = day.bomb_count + 1
    line = BOMB_LINES[min(n - 1, len(BOMB_LINES) - 1)].format(n=n, streak=st.streak)
    done, target = totals(day)
    text = f"{line}\n目前 {done}/{target} 篇。"
    if not push.send_owner(session, st, now, text, "bomb"):
        return False
    day.bomb_count = n
    day.last_bomb_at = now
    session.add(day)
    session.commit()
    return True
