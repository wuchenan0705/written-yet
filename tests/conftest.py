import os
import tempfile

os.environ.setdefault("DATABASE_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("WEB_PASSWORD", "pw")
os.environ.setdefault("DISABLE_SCHEDULER", "1")

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import models, push  # noqa: F401


class FakeTransport:
    def __init__(self, members=3):
        self.sent = []
        self.members = members

    def push(self, to, text):
        self.sent.append((to, text))

    def group_member_count(self, group_id):
        return self.members


@pytest.fixture(autouse=True)
def no_claude_api(monkeypatch):
    """Tests must pass fakes; reaching the real API is a bug in the test."""
    from app import grader

    def refuse(*a, **k):
        raise AssertionError("test tried to call the Claude API")
    monkeypatch.setattr(grader, "_call", refuse)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def transport():
    t = FakeTransport()
    push.set_transport(t)
    yield t
    push.set_transport(None)
