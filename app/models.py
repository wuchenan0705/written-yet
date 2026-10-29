from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column, LargeBinary, UniqueConstraint
from sqlmodel import Field, SQLModel

SKILLS = ("listening", "reading", "writing", "speaking")
SKILL_ZH = {"listening": "聽力", "reading": "閱讀", "writing": "寫作", "speaking": "口說"}
# Skills graded question by question (Answer rows); writing/speaking get a band estimate instead.
OBJECTIVE_SKILLS = ("listening", "reading")

# Answer.kind: fill = write words/numbers, choice = single letter, matching = letter from a
# shared box, tfng = TRUE/FALSE/NOT GIVEN or YES/NO/NOT GIVEN, multi = "choose TWO" set.
ANSWER_KINDS = ("fill", "choice", "matching", "tfng", "multi")
OPTION_KINDS = ("choice", "matching", "multi")  # answers stored as letters
# Answer.status
CORRECT, WRONG, BLANK, UNGRADED = "correct", "wrong", "blank", "ungraded"
MISTAKE_STATUSES = (WRONG, BLANK)

UNANSWERED = "未作答"  # the error type of every blank answer, and only of blank answers
ERROR_TYPES = [
    UNANSWERED, "同義替換沒認出", "NOT GIVEN/FALSE 混淆", "定位錯誤", "細節漏看", "拼字錯誤",
    "單複數/詞形", "字數限制", "數字/日期", "詞彙不認識", "推論/邏輯", "文法", "其他",
]
# Goals are counted in sets: one submission = one passage / section / essay / speaking part.
DEFAULT_GOALS = {"listening": 1, "reading": 1, "writing": 1, "speaking": 1}

# Changes to these fields only take effect after a 24h cooldown (see logic.update_settings),
# except switching a penalty on, which is immediate.
PENALTY_FIELDS = (
    "pen_streak", "debt_cap",
    "pen_shame", "shame_template",
    "pen_fine", "fine_amount", "fine_note",
    "pen_bomb", "bomb_intervals", "bomb_max_per_day",
    "leave_per_month",
)
PENALTY_TOGGLES = ("pen_streak", "pen_shame", "pen_fine", "pen_bomb")


def json_field(default_factory=dict):
    return Field(default_factory=default_factory, sa_column=Column(JSON))


class AppSettings(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    owner_user_id: Optional[str] = None
    display_name: str = "我"
    goals: dict = json_field(lambda: dict(DEFAULT_GOALS))
    morning_time: str = "09:00"
    evening_time: str = "21:00"
    deadline_time: str = "23:00"
    settle_time: str = "23:59"
    # True = the time is in the early morning after the practice day (e.g. 01:00 the next day).
    deadline_next_day: bool = False
    settle_next_day: bool = False
    streak: int = 0
    best_streak: int = 0
    push_monthly_limit: int = 200

    leave_per_month: int = 2
    pen_streak: bool = True
    debt_cap: float = 2.0
    pen_shame: bool = False
    shame_group_id: Optional[str] = None
    shame_template: str = "📢 {name} 今天雅思只完成 {done}/{target} 篇，連續 {streak} 天的紀錄斷了 🫠 大家快來督促一下！"
    pen_fine: bool = False
    fine_amount: int = 100
    fine_note: str = "轉給監督我的朋友"
    pen_bomb: bool = False
    bomb_intervals: str = "30,15,10"
    bomb_max_per_day: int = 8

    pending_penalty: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    pending_apply_at: Optional[datetime] = None


class DayRecord(SQLModel, table=True):
    date: str = Field(primary_key=True)  # YYYY-MM-DD, Taipei
    targets: dict = json_field()
    done: dict = json_field()
    status: str = "open"  # open / completed / failed / leave
    debt_out: dict = json_field()  # extra questions carried to the next day
    settled: bool = False
    morning_sent: bool = False
    evening_sent: bool = False
    bomb_count: int = 0
    last_bomb_at: Optional[datetime] = None


class Submission(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime
    date: str = Field(index=True)
    skill: str
    source: str  # web / line
    raw_text: str
    question_count: int = 0
    correct_count: int = 0
    result: dict = json_field()
    # Where the set came from, e.g. book "C21", test "Test 1", part "Passage 3"
    book: str = Field(default="", index=True)
    test: str = ""
    part: str = ""
    title: str = ""

    @property
    def source_label(self) -> str:
        label = " ".join(x for x in (self.book, self.test, self.part) if x)
        return f"{label}｜{self.title}" if label and self.title else (label or self.title)


class Answer(SQLModel, table=True):
    """One question of a listening/reading set: the only record of per-question results.

    Submission.question_count / correct_count are recomputed from these rows
    (review.recount) and never adjusted by hand.
    """
    __table_args__ = (UniqueConstraint("submission_id", "question_no"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    submission_id: int = Field(index=True)
    skill: str
    created_at: datetime
    question_no: str
    kind: str = "fill"
    group_nos: str = ""  # "25-26" for a choose-TWO set, scored order-free
    question: str = ""
    options: dict = json_field()  # {"A": "competitors nearby", ...}
    user_answer: str = ""  # "" = unanswered; a letter for option kinds
    accepted: list = json_field(list)  # acceptable answers, letters for option kinds
    key_source: str = "page"  # page (answer key shown) / coach (Claude solved it) / user
    status: str = UNGRADED
    error_type: str = ""  # set only for wrong / blank
    verdict_by: str = "auto"  # auto (judge.py) / manual (user overrode it)
    note: str = ""
    explanation: str = ""
    evidence: str = ""
    tip: str = ""
    understood: bool = False

    @property
    def is_mistake(self) -> bool:
        return self.status in MISTAKE_STATUSES

    def show(self, value: str) -> str:
        """A letter answer with its option text, e.g. 'B involve more children in need'."""
        text = self.options.get(value, "") if self.kind in OPTION_KINDS else ""
        return f"{value} {text}" if text else value

    @property
    def key_text(self) -> str:
        return " / ".join(self.show(k) for k in self.accepted)


class Mistake(SQLModel, table=True):
    """Legacy per-question table, replaced by Answer (see migrate.py). Kept for old databases."""
    id: Optional[int] = Field(default=None, primary_key=True)
    submission_id: int = Field(index=True)
    created_at: datetime
    skill: str
    question_no: str = ""
    question: str = ""
    user_answer: str = ""
    correct_answer: str = ""
    error_type: str = "其他"
    explanation: str = ""
    evidence: str = ""
    tip: str = ""
    understood: bool = False


class FineEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: str
    amount: int
    note: str = ""
    paid: bool = False
    paid_at: Optional[datetime] = None


class PushLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    sent_at: datetime = Field(index=True)
    kind: str
    target: str
    cost: int = 1


class DraftImage(SQLModel, table=True):
    """Screenshots sent to the LINE bot, waiting for the next 交 command."""
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime
    media_type: str
    data: bytes = Field(sa_column=Column(LargeBinary))


class SubmissionImage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    submission_id: int = Field(index=True)
    media_type: str
    data: bytes = Field(sa_column=Column(LargeBinary))
