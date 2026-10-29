"""LINE webhook: owner binding, commands, and quick submit."""
import hmac
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    PushMessageRequest,
    ReplyMessageRequest,
    ShowLoadingAnimationRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    FollowEvent,
    ImageMessageContent,
    JoinEvent,
    MessageEvent,
    TextMessageContent,
)
from sqlmodel import Session, select

from app import clock, config, images, push, review, submissions, writing_guide
from app.db import engine
from app.grader import GradingError
from app.logic import get_or_create_day, get_settings, outstanding_fines, practice_date, progress_text, use_leave
from app.models import MISTAKE_STATUSES, OBJECTIVE_SKILLS, SKILL_ZH, UNGRADED, Answer, DraftImage, Submission

log = logging.getLogger(__name__)
router = APIRouter()

SKILL_ALIASES = {
    "聽力": "listening", "聽": "listening",
    "閱讀": "reading", "讀": "reading",
    "寫作": "writing", "寫": "writing",
    "口說": "speaking", "說": "speaking",
}
SUBMIT_RE = re.compile(r"^交\s*(聽力|閱讀|寫作|口說|聽|讀|寫|說)\s*(.*)$", re.S)

HELP = f"""📘 指令
進度｜今天的進度與連續天數
先傳雅思哥檢討頁截圖，再傳「交 閱讀」｜批改一篇（聽力/閱讀/寫作/口說）
交 閱讀 ＋換行＋文字｜也可以直接貼文字，或文字＋截圖一起
補 37 NO 38 NG｜補上最近一份有這些題號的提交的答案（勾選沒複製到、漏批的題目）
清除｜丟掉還沒交的截圖
寫作｜寫作題型與工具書
連接詞 對比｜查某類連接詞（補充/對比/原因/結果/舉例/讓步/強調/順序/條件/換句話說/立場/結論）
錯題｜最近 5 題還沒搞懂的錯題
請假｜用掉一次請假額度
罰金｜未付罰金總額
監督群組｜（在群組裡輸入）設為公開羞恥的群組
網頁｜{config.BASE_URL}"""


SUBMIT_USAGE = """交一篇{skill}的方式（擇一或混用）：
1️⃣ 先傳雅思哥檢討頁截圖（要有「正确答案／我的答案」那塊），再傳「交 {skill}」
2️⃣ 「交 {skill}」換行貼上從雅思哥複製的文字，再加一行你的答案，例如：27A 28A 29C 37 NO"""
DRAFT_TTL = timedelta(hours=6)


def pending_drafts(session: Session, now: datetime) -> list[DraftImage]:
    return session.exec(
        select(DraftImage).where(DraftImage.created_at >= now - DRAFT_TTL).order_by(DraftImage.id)
    ).all()


def clear_drafts(session: Session) -> int:
    drafts = session.exec(select(DraftImage)).all()
    for d in drafts:
        session.delete(d)
    session.commit()
    return len(drafts)


def handle_image(session: Session, t: "LineTransport", ev) -> None:
    now = clock.now()
    try:
        media_type, data = images.normalize(t.download(ev.message.id))
    except images.ImageError as e:
        t.reply(ev.reply_token, str(e))
        return
    session.add(DraftImage(created_at=now, media_type=media_type, data=data))
    session.commit()
    image_set = ev.message.image_set
    if image_set and image_set.index != image_set.total:
        return  # reply once per batch, on the last image
    n = len(pending_drafts(session, now))
    extra = f"\n⚠️ 一次最多 {images.MAX_IMAGES} 張，只會用最後 {images.MAX_IMAGES} 張。" if n > images.MAX_IMAGES else ""
    t.reply(ev.reply_token, f"📥 已收到截圖（共 {n} 張待批改）。\n傳完後輸入「交 閱讀」或「交 聽力」開始批改。{extra}")


class LineTransport:
    """push.Transport implementation backed by the Messaging API."""

    def __init__(self, token: str):
        self.conf = Configuration(access_token=token)

    def _api(self):
        return ApiClient(self.conf)

    def push(self, to: str, text: str) -> None:
        with self._api() as c:
            MessagingApi(c).push_message(PushMessageRequest(to=to, messages=[TextMessage(text=text)]))

    def group_member_count(self, group_id: str) -> int:
        with self._api() as c:
            return MessagingApi(c).get_group_member_count(group_id).count

    def reply(self, token: str, text: str) -> bool:
        try:
            with self._api() as c:
                MessagingApi(c).reply_message(
                    ReplyMessageRequest(reply_token=token, messages=[TextMessage(text=text[:4900])])
                )
            return True
        except Exception:
            log.warning("reply failed", exc_info=True)
            return False

    def download(self, message_id: str) -> bytes:
        with self._api() as c:
            return bytes(MessagingApiBlob(c).get_message_content(message_id))

    def loading(self, user_id: str) -> None:
        try:
            with self._api() as c:
                MessagingApi(c).show_loading_animation(
                    ShowLoadingAnimationRequest(chat_id=user_id, loading_seconds=60)
                )
        except Exception:
            log.warning("loading animation failed", exc_info=True)


def parse_command(text: str) -> tuple[str, Optional[str], str]:
    """Return (command, skill, body). command is '' when not recognised."""
    text = text.strip()
    m = SUBMIT_RE.match(text)
    if m:
        return "submit", SKILL_ALIASES[m.group(1)], m.group(2).strip()
    if text.startswith("綁定"):
        return "bind", None, text[2:].strip()
    if text.startswith("補"):
        return "補", None, text[1:].strip()
    if text.startswith("連接詞"):
        return "連接詞", None, text[3:].strip()
    for cmd in ("進度", "錯題", "請假", "罰金", "監督群組", "說明", "清除", "寫作"):
        if text == cmd:
            return cmd, None, ""
    if text in ("help", "指令", "?", "？"):
        return "說明", None, ""
    return "", None, text


def fill_target(session: Session, nos: list[str]) -> Optional[Submission]:
    """The latest listening/reading submission that has all these question numbers,
    preferring one that still has ungraded questions."""
    subs = session.exec(select(Submission).where(Submission.skill.in_(OBJECTIVE_SKILLS))
                        .order_by(Submission.id.desc()).limit(20)).all()
    matches = []
    for sub in subs:
        rows = {a.question_no: a for a in review.answers_of(session, sub.id)}
        if all(no in rows for no in nos):
            matches.append((sub, any(rows[no].status == UNGRADED for no in nos)))
    return next((sub for sub, open_ in matches if open_), matches[0][0] if matches else None)


def fill_from_line(session: Session, t: "LineTransport", user_id: str, body: str) -> str:
    """補 27A 28 NG — answer questions of the latest submission that has these numbers."""
    answers = review.parse_answers(body)
    if not answers:
        return "格式：補 37 NO 38 NG 39 YES（或 27A 28C）\n會補到最近一份有這些題號的提交。"
    nos = [review.clean_no(no) for no, _ in answers]
    target = fill_target(session, nos)
    if target is None:
        return f"最近 20 份聽力/閱讀都找不到第 {'、'.join(nos)} 題，請到網頁的提交頁面補。"
    t.loading(user_id)
    res = review.fill_answers(session, target, [(no, a, "") for no, a in answers], clock.now())
    session.refresh(target)
    lines = [f"✍️ {target.source_label or SKILL_ZH[target.skill]}",
             f"補批 {res.graded} 題，答對 {res.correct} 題",
             f"這份目前 {target.correct_count}/{target.question_count}"]
    left = [a.question_no for a in review.answers_of(session, target.id) if a.status == UNGRADED]
    if left:
        lines.append(f"還沒計分：第 {'、'.join(left)} 題")
    if res.warning:
        lines.append(f"⚠️ {res.warning}")
    lines.append(f"解析：{config.BASE_URL}/submissions/{target.id}")
    return "\n".join(lines)


def writing_summary() -> str:
    t1 = "\n".join(f"・{t['name']}：{t['focus']}" for t in writing_guide.TASK1_TYPES)
    t2 = "\n".join(f"・{t['name']}｜{t['keywords'][0]}" for t in writing_guide.TASK2_TYPES)
    return (f"✍️ Academic 寫作\n\n【Task 1】20 分鐘・150 字以上\n{t1}\n\n"
            f"【Task 2】40 分鐘・250 字以上\n{t2}\n\n"
            f"查連接詞：傳「連接詞 對比」\n完整工具書：{config.BASE_URL}/writing")


def _transport() -> Optional[LineTransport]:
    return LineTransport(config.LINE_CHANNEL_ACCESS_TOKEN) if config.LINE_CHANNEL_ACCESS_TOKEN else None


@router.post("/callback")
async def callback(request: Request, background: BackgroundTasks,
                   x_line_signature: str = Header(default="")):
    body = (await request.body()).decode()
    try:
        events = WebhookParser(config.LINE_CHANNEL_SECRET).parse(body, x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(400, "invalid signature")
    for ev in events:
        background.add_task(handle_event, ev)
    return "OK"


def handle_event(ev) -> None:
    t = _transport()
    if t is None:
        return
    with Session(engine) as session:
        st = get_settings(session)
        if isinstance(ev, JoinEvent):
            t.reply(ev.reply_token, "👀 我是「寫未？」，每天問雅思寫了沒的機器人。擁有者在這裡輸入「監督群組」，偷懶的時候我就會在這裡公告。")
            return
        if isinstance(ev, FollowEvent):
            t.reply(ev.reply_token, "嗨！我是「寫未？」📝 每天問你雅思寫了沒。\n請輸入「綁定 你的網頁密碼」把我綁定成你的私人教練。")
            return
        if not isinstance(ev, MessageEvent):
            return
        user_id = ev.source.user_id
        if isinstance(ev.message, ImageMessageContent):
            if user_id == st.owner_user_id and ev.source.type == "user":
                handle_image(session, t, ev)
            return
        if not isinstance(ev.message, TextMessageContent):
            return
        cmd, skill, body = parse_command(ev.message.text)

        if cmd == "bind" and ev.source.type == "user":
            if config.WEB_PASSWORD and hmac.compare_digest(body, config.WEB_PASSWORD):
                st.owner_user_id = user_id
                session.add(st)
                session.commit()
                t.reply(ev.reply_token, "✅ 綁定成功！之後每天提醒都會發給你。\n\n" + HELP)
            else:
                t.reply(ev.reply_token, "密碼錯誤。")
            return
        if user_id != st.owner_user_id:
            if ev.source.type == "user":
                t.reply(ev.reply_token, "這是私人機器人，請先輸入「綁定 密碼」。")
            return

        if cmd == "監督群組":
            if ev.source.type != "group":
                t.reply(ev.reply_token, "請在要公告的群組裡輸入這個指令。")
                return
            st.shame_group_id = ev.source.group_id
            session.add(st)
            session.commit()
            note = "" if st.pen_shame else "\n（公開羞恥目前是關閉的，到網頁設定開啟）"
            t.reply(ev.reply_token, f"😈 已設為監督群組，{st.display_name}偷懶時我會在這裡公告。{note}")
            return
        if ev.source.type != "user":
            return  # only the group binding command works in groups

        now = clock.now()
        day = get_or_create_day(session, st, practice_date(st, now))
        if cmd == "submit":
            drafts = pending_drafts(session, now)
            if not body and not drafts:
                t.reply(ev.reply_token, SUBMIT_USAGE.format(skill=SKILL_ZH[skill]))
                return
            t.loading(user_id)
            try:
                imgs = [(d.media_type, d.data) for d in drafts[-images.MAX_IMAGES:]]
                sub, finished = submissions.process(session, skill, body, "line", now, imgs)
                text = submissions.line_summary(session, sub, finished)
                clear_drafts(session)
            except GradingError as e:
                text = f"⚠️ 批改失敗：{e}\n（截圖還留著，可以直接再傳一次「交 {SKILL_ZH[skill]}」）"
            if not t.reply(ev.reply_token, text):  # reply token can expire during grading
                push.send_owner(session, st, clock.now(), text, "reply")
        elif cmd == "寫作":
            t.reply(ev.reply_token, writing_summary())
        elif cmd == "連接詞":
            group = writing_guide.find_connector_group(body)
            if group:
                t.reply(ev.reply_token, writing_guide.connector_text(group))
            else:
                names = "、".join(g["title"] for g in writing_guide.CONNECTORS)
                t.reply(ev.reply_token, f"要查哪一類？例如「連接詞 對比」\n{names}\n\n完整版：{config.BASE_URL}/writing#connectors")
        elif cmd == "補":
            text = fill_from_line(session, t, user_id, body)
            if not t.reply(ev.reply_token, text):  # reply token can expire during grading
                push.send_owner(session, st, clock.now(), text, "reply")
        elif cmd == "清除":
            n = clear_drafts(session)
            t.reply(ev.reply_token, f"🗑 已清除 {n} 張待批改截圖。")
        elif cmd == "進度":
            t.reply(ev.reply_token, progress_text(st, day))
        elif cmd == "請假":
            t.reply(ev.reply_token, use_leave(session, st, day))
        elif cmd == "罰金":
            t.reply(ev.reply_token, f"💸 未付罰金：{outstanding_fines(session)}（{st.fine_note}）\n付款後到網頁標記已付。")
        elif cmd == "錯題":
            rows = session.exec(
                select(Answer, Submission).join(Submission, Answer.submission_id == Submission.id)
                .where(Answer.status.in_(MISTAKE_STATUSES), Answer.understood == False)  # noqa: E712
                .order_by(Submission.id.desc(), Answer.id.desc()).limit(5)
            ).all()
            if not rows:
                t.reply(ev.reply_token, "🎉 目前沒有待複習的錯題。")
            else:
                parts = [
                    f"【{sub.source_label or SKILL_ZH[m.skill]}"
                    f"{' Q' + m.question_no if m.question_no else ''}｜{m.error_type}】{m.question[:80]}\n"
                    f"你：{m.show(m.user_answer) or '（未作答）'} → 正解：{m.key_text}\n💡 {m.tip}"
                    for m, sub in rows
                ]
                t.reply(ev.reply_token, "\n\n".join(parts) + f"\n\n更多：{config.BASE_URL}/mistakes")
        else:
            t.reply(ev.reply_token, HELP)
