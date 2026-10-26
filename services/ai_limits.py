"""Rate limits on AI (Gemini) requests made from the app, to protect the free daily quota.

Two limits, both checked before a request is sent:
- App-wide: at most AI_DAILY_LIMIT requests in any 24 hours, from everyone together.
- Per browser session: at most AI_SESSION_HOURLY_LIMIT requests in any 60 minutes.

There is no wait between requests: one click can need two requests in a row (Run research does).

Settings come from .env or Streamlit Cloud Secrets. Limits apply only inside the running app;
scripts and tests run outside it are not limited and are not counted.
"""

import math
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import db

DEFAULTS = {"AI_DAILY_LIMIT": 15, "AI_SESSION_HOURLY_LIMIT": 6}


@dataclass(frozen=True)
class Limits:
    daily: int
    hourly: int


@dataclass(frozen=True)
class Usage:
    used_today: int
    used_this_hour: int
    limits: Limits

    @property
    def left_today(self):
        return max(self.limits.daily - self.used_today, 0)

    @property
    def left_this_hour(self):
        return max(self.limits.hourly - self.used_this_hour, 0)


def _setting(name):
    try:
        return max(int(os.getenv(name, DEFAULTS[name])), 0)
    except ValueError:
        return DEFAULTS[name]


def limits():
    return Limits(_setting("AI_DAILY_LIMIT"), _setting("AI_SESSION_HOURLY_LIMIT"))


def current_session():
    """The browser session making this request, or None outside the running app."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except ImportError:
        return None
    ctx = get_script_run_ctx(suppress_warning=True)
    return ctx.session_id if ctx else None


def _stamp(moment):
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _ago(text, now):
    return now - datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def _wait_words(seconds):
    if seconds < 60:
        seconds = max(math.ceil(seconds), 1)
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    minutes = math.ceil(seconds / 60)
    if minutes < 120:
        return f"about {minutes} minutes"
    return f"about {round(minutes / 60)} hours"


def usage(session_id=None, db_path=None, now=None):
    """How much has been used. Reads only, and works on a database from before limits existed."""
    now = now or datetime.now(timezone.utc)
    path = db.project_path(db_path or db.DB_PATH)
    rows = []
    if path.exists():
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT session_id, created_at FROM ai_usage WHERE created_at >= ?",
                                (_stamp(now - timedelta(days=1)),)).fetchall()
        except sqlite3.OperationalError:
            rows = []
        finally:
            conn.close()
    hour_ago = _stamp(now - timedelta(hours=1))
    mine = [r for r in rows if r[0] == session_id and r[1] >= hour_ago] if session_id else []
    return Usage(len(rows), len(mine), limits())


def summary(session_id=None, db_path=None):
    """One line for the screen, such as 'AI requests left: 5 this hour (you), 12 today (whole app).'"""
    used = usage(session_id or current_session(), db_path)
    return f"AI requests left: {used.left_this_hour} this hour (you), {used.left_today} today (whole app)."


def acquire(session_id=None, db_path=None, now=None):
    """Check every limit and record one request. Raises RateLimited (with a plain message) if a limit is reached.

    Does nothing outside the running app (no session).
    """
    from services.gemini import RateLimited
    session_id = session_id or current_session()
    if session_id is None:
        return
    now = now or datetime.now(timezone.utc)
    current = limits()
    db.init_db(db_path)
    conn = db.get_connection(db_path)
    try:
        with conn:  # one transaction, so two clicks at once cannot both slip under a limit
            conn.execute("BEGIN IMMEDIATE")
            day = conn.execute("SELECT created_at FROM ai_usage WHERE created_at >= ? ORDER BY created_at",
                               (_stamp(now - timedelta(days=1)),)).fetchall()
            mine = [r["created_at"] for r in conn.execute(
                "SELECT created_at FROM ai_usage WHERE session_id = ? AND created_at >= ? ORDER BY created_at",
                (session_id, _stamp(now - timedelta(hours=1))))]
            if len(day) >= current.daily:
                wait = timedelta(days=1) - _ago(day[0]["created_at"], now) if day else timedelta(0)
                raise RateLimited(f"The app's AI limit of {current.daily} requests a day has been reached. "
                                  f"Try again in {_wait_words(wait.total_seconds())}.")
            if len(mine) >= current.hourly:
                wait = timedelta(hours=1) - _ago(mine[0], now)
                raise RateLimited(f"You have used your {current.hourly} AI requests for this hour. "
                                  f"Try again in {_wait_words(wait.total_seconds())}.")
            conn.execute("INSERT INTO ai_usage (session_id, created_at) VALUES (?, ?)", (session_id, _stamp(now)))
    finally:
        conn.close()
