import io
from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

from app import images, line_bot, review, submissions
from app.db import engine, init_db
from app.line_bot import parse_command
from app.logic import get_settings
from app.main import app
from app.models import CORRECT, UNGRADED, WRONG, Answer, DraftImage, Submission, SubmissionImage
from tests.fakes import explainer, q, result

FAKE = result([
    q("27", "choice", visible=False, key="B", explanation="（教練判斷）…"),
    q("28", "choice", visible=False, key="C", explanation="（教練判斷）…"),
    q("37", "tfng", user="FALSE", key="NOT GIVEN", error_type="NOT GIVEN/FALSE 混淆", explanation="原文沒提到"),
    q("38", "tfng", user="NG", key="NOT GIVEN", note="原文只提到亞洲產地"),
    q("39", "fill", user="china", key="China"),
], first=27, last=39, summary="不錯",
    source={"book": "C21", "test": "Test 1", "part": "Passage 3", "title": "A Short History of Tea"})


def png(w=3000, h=1800) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, "PNG")
    return buf.getvalue()


def fake_grade(calls):
    def grade(skill, text, imgs=()):
        calls.append((skill, text, list(imgs)))
        return FAKE
    return grade


def test_parse_command():
    assert parse_command("交 閱讀\n1. abc") == ("submit", "reading", "1. abc")
    assert parse_command("交聽力 x") == ("submit", "listening", "x")
    assert parse_command("交 寫") == ("submit", "writing", "")
    assert parse_command("綁定 pw") == ("bind", None, "pw")
    assert parse_command("清除")[0] == "清除"
    assert parse_command("hello")[0] == ""


def test_normalize_shrinks_large_screenshots():
    media_type, data = images.normalize(png())
    assert media_type == "image/png"
    assert max(Image.open(io.BytesIO(data)).size) == images.MAX_EDGE


def test_process_submission_counts_sets_and_keeps_images(session):
    st = get_settings(session)
    st.goals = {"listening": 0, "reading": 2, "writing": 0, "speaking": 0}
    now = datetime(2026, 10, 20, 10)
    calls = []
    imgs = [("image/png", b"x")]
    sub, finished = submissions.process(session, "reading", "", "web", now, imgs, fake_grade(calls))
    assert not finished and (sub.correct_count, sub.question_count) == (2, 3)  # still one set
    assert calls[0][2] == imgs
    assert session.exec(select(SubmissionImage)).one().submission_id == sub.id
    m = session.exec(select(Answer).where(Answer.question_no == "37")).first()
    assert (m.status, m.error_type) == (WRONG, "NOT GIVEN/FALSE 混淆")
    sub, finished = submissions.process(session, "reading", "t", "web", now, (), fake_grade(calls),
                                        answers=[("27", "B"), ("28", "A")], explain_fn=explainer()[0])
    assert finished and (sub.correct_count, sub.question_count) == (3, 5)
    assert "我的答案：27 B 28 A" in calls[-1][1]  # Claude sees the typed answers too
    summary = submissions.line_summary(session, sub, finished)
    assert "3/5" in summary and "看不到你的答案" not in summary and "今日目標全部完成" in summary
    sub, _ = submissions.process(session, "reading", "", "web", now, (), fake_grade(calls))
    assert "第 27、28 題看不到你的答案" in submissions.line_summary(session, sub, False)


def test_web_login_and_pages(monkeypatch):
    init_db()
    calls = []
    monkeypatch.setattr(submissions.grader, "grade", fake_grade(calls))
    with TestClient(app) as c:
        assert c.get("/", follow_redirects=False).headers["location"] == "/login"
        assert "密碼錯誤" in c.post("/login", data={"password": "no"}).text
        c.post("/login", data={"password": "pw"})
        assert "今日目標" in c.get("/").text
        assert "請選科目" in c.post("/submit", data={"skill": "reading", "text": ""}).text
        r = c.post("/submit", data={"skill": "reading", "text": ""},
                   files=[("files", ("a.png", png(), "image/png")), ("files", ("b.png", png(800, 600), "image/png"))])
        assert "錯題解析" in r.text and "找不到你在第 27、28 題" in r.text
        assert len(calls[-1][2]) == 2
        img_src = r.text.split('src="/images/')[1].split('"')[0]
        assert c.get(f"/images/{img_src}").headers["content-type"] == "image/png"
        assert "看不懂這個檔案" in c.post("/submit", data={"skill": "reading"},
                                       files=[("files", ("x.png", b"nope", "image/png"))]).text
        assert "答對的題目（2）" in r.text and "原文只提到亞洲產地" in r.text
        r = c.post("/submit", data={"skill": "reading", "text": "x", "answers": "27B 28 c"})
        assert "找不到你在第" not in r.text and "答對的題目（4）" in r.text
        assert "C21 Test 1 Passage 3｜A Short History of Tea" in r.text

        # Typed source overrides what was detected.
        c.post("/submit", data={"skill": "reading", "text": "x", "book": "C18", "test": "Test 2"})
        page = c.get("/mistakes").text
        assert "C21 Test 1 Passage 3" in page and "C18 Test 2 Passage 3" in page
        page = c.get("/mistakes", params={"book": "C18"}).text
        assert "C18 Test 2" in page and "C21 Test 1 Passage 3｜" not in page
        assert "Q37" in page
        assert "NOT GIVEN/FALSE" in c.get("/mistakes", params={"book": "C21", "test": "Test 1"}).text
        assert "懲罰機制" in c.get("/settings").text
        assert c.get("/fines").status_code == 200
        r = c.post("/settings", data={"goal_reading": "2", "pen_streak": "on", "pen_bomb": "on",
                                      "debt_cap": "2", "fine_amount": "100", "bomb_intervals": "30,15,10",
                                      "bomb_max_per_day": "8", "leave_per_month": "2",
                                      "morning_time": "08:30"})
        assert r.status_code == 200
    with Session(engine) as s:
        st = get_settings(s)
        assert st.goals["reading"] == 2 and st.pen_bomb and st.morning_time == "08:30"


class FakeLine:
    def __init__(self):
        self.replies = []

    def reply(self, token, text):
        self.replies.append(text)
        return True

    def download(self, message_id):
        return png(1000, 800)

    def loading(self, user_id):
        pass


def image_event(i, total):
    return SimpleNamespace(
        reply_token=f"r{i}", source=SimpleNamespace(type="user", user_id="OWNER"),
        message=SimpleNamespace(id=str(i), image_set=SimpleNamespace(index=i, total=total)),
    )


def test_line_screenshots_then_submit(monkeypatch):
    init_db()
    with Session(engine) as s:
        st = get_settings(s)
        st.owner_user_id = "OWNER"
        s.add(st)
        s.commit()
        for d in s.exec(select(DraftImage)).all():
            s.delete(d)
        s.commit()
    fake = FakeLine()
    calls = []
    monkeypatch.setattr(line_bot, "_transport", lambda: fake)
    monkeypatch.setattr(submissions.grader, "grade", fake_grade(calls))
    monkeypatch.setattr(line_bot, "MessageEvent", SimpleNamespace)
    monkeypatch.setattr(line_bot, "ImageMessageContent", SimpleNamespace)
    monkeypatch.setattr(line_bot, "TextMessageContent", str)

    for i in (1, 2):
        line_bot.handle_event(image_event(i, 2))
    assert len(fake.replies) == 1 and "共 2 張" in fake.replies[0]

    # A str subclass with .text stands in for TextMessageContent.
    text_msg = type("T", (str,), {"text": property(lambda self: str(self))})("交 閱讀")
    monkeypatch.setattr(line_bot, "ImageMessageContent", type("Never", (), {}))
    submit = SimpleNamespace(reply_token="r9", source=SimpleNamespace(type="user", user_id="OWNER"),
                             message=text_msg)
    line_bot.handle_event(submit)
    assert len(calls[-1][2]) == 2 and calls[-1][1] == ""
    assert "2/3 題正確" in fake.replies[-1] and "📖 C21 Test 1 Passage 3" in fake.replies[-1]
    assert "第 27、28 題看不到你的答案" in fake.replies[-1]
    with Session(engine) as s:
        assert s.exec(select(DraftImage)).all() == []
        assert s.exec(select(Submission).where(Submission.source == "line")).first()


def test_line_webhook_rejects_bad_signature():
    with TestClient(app) as c:
        r = c.post("/callback", content="{}", headers={"X-Line-Signature": "bad"})
        assert r.status_code == 400


def test_writing_guide_page_and_line_lookup():
    from app import writing_guide
    assert parse_command("連接詞 對比") == ("連接詞", None, "對比")
    assert parse_command("寫作")[0] == "寫作"
    assert writing_guide.find_connector_group("對比")["id"] == "contrast"
    assert writing_guide.find_connector_group("result")["id"] == "result"
    assert writing_guide.find_connector_group("xyz") is None
    assert "Although it is expensive" in writing_guide.connector_text(writing_guide.find_connector_group("對比"))
    assert "Process diagram" in line_bot.writing_summary()
    init_db()
    with TestClient(app) as c:
        c.post("/login", data={"password": "pw"})
        page = c.get("/writing").text
        assert "Task 1 題型（7 種）" in page and "Task 2 題型（6 種）" in page
        assert "Despite of" in page and 'id="c-contrast"' in page


def test_line_fill_command(monkeypatch):
    init_db()
    with Session(engine) as s:
        sub = Submission(created_at=datetime(2026, 10, 21, 9), date="2026-10-21", skill="reading", source="web",
                         raw_text="passage", book="C9", result={})
        s.add(sub)
        s.commit()
        s.refresh(sub)
        for no, status, key in (("36", CORRECT, "YES"), ("37", UNGRADED, "NO"), ("38", UNGRADED, "FALSE")):
            s.add(Answer(submission_id=sub.id, skill="reading", created_at=sub.created_at, question_no=no,
                         kind="tfng", accepted=[key], status=status, user_answer=key if status == CORRECT else ""))
        s.commit()
        review.recount(s, sub)
        s.commit()
        # A newer submission without these question numbers must not receive the answers.
        s.add(Submission(created_at=datetime(2026, 10, 21, 10), date="2026-10-21", skill="listening",
                         source="web", raw_text="", result={}))
        s.commit()

        explain, calls = explainer()
        monkeypatch.setattr(review.grader, "explain", explain)
        assert parse_command("補 37 NO 38 NG") == ("補", None, "37 NO 38 NG")
        text = line_bot.fill_from_line(s, FakeLine(), "OWNER", "37 NO 38 NG")
        assert "補批 2 題，答對 1 題" in text and "2/3" in text and f"/submissions/{sub.id}" in text
        assert [x["question_no"] for x in calls[0]] == ["38"]  # only the wrong answer needs Claude
        assert "還沒計分" not in text
        assert "格式：補" in line_bot.fill_from_line(s, FakeLine(), "OWNER", "")
        assert "找不到第 99 題" in line_bot.fill_from_line(s, FakeLine(), "OWNER", "99 A")
