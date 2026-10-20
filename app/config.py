import os
import secrets

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "")
# Without SESSION_SECRET a random one is used, so logins reset on every restart.
SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
DATABASE_PATH = os.environ.get("DATABASE_PATH", "data/app.db")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
DISABLE_SCHEDULER = os.environ.get("DISABLE_SCHEDULER") == "1"
