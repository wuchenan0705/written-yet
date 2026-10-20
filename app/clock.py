from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")


def now() -> datetime:
    """Current Taipei time as a naive datetime (SQLite stores naive values)."""
    return datetime.now(TZ).replace(tzinfo=None)
