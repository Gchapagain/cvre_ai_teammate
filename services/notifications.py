"""The writes Home makes, each only when a person clicks: feed item state, meetings, and emails.

Viewing Home never comes through here (it reads with app/queries.py). Times passed in are the
person's local time.
"""

import json
from datetime import datetime

import db
from services.feed import SNOOZE, stamp

MEETING_SOURCES = ("Manual", "Sample", "Google Calendar", "Outlook Calendar")


def _connect(db_path):
    db.init_db(db_path)  # also adds any table a database from an older version is missing
    return db.get_connection(db_path)


def _set_state(keys, column, value, db_path=None):
    conn = _connect(db_path)
    try:
        with conn:
            for key in keys:
                conn.execute(f"INSERT INTO notification_state (item_key, {column}) VALUES (?, ?) "
                             f"ON CONFLICT(item_key) DO UPDATE SET {column} = excluded.{column}", (key, value))
    finally:
        conn.close()


def mark_read(keys, now, db_path=None):
    _set_state(list(keys), "read_at", stamp(now), db_path)


def snooze(key, now, db_path=None):
    """Hide an item for a day. Flags are never passed here: the screen does not offer it for them."""
    if key.startswith("flag:"):
        raise ValueError("Flags cannot be snoozed. Resolve the flag on the deal instead.")
    _set_state([key], "snoozed_until", stamp(now + SNOOZE), db_path)


def dismiss(key, now, db_path=None):
    if key.startswith("flag:"):
        raise ValueError("Flags cannot be dismissed. Resolve the flag on the deal instead.")
    _set_state([key], "dismissed_at", stamp(now), db_path)


def add_meeting(title, starts_at, ends_at=None, deal_id=None, client_name=None, location=None, notes=None,
                source="Manual", db_path=None):
    """Save a meeting a person typed in. Times are datetimes in the person's local time. Returns its ID."""
    title = (title or "").strip()
    if not title:
        raise ValueError("A meeting needs a title.")
    if ends_at is not None and ends_at <= starts_at:
        raise ValueError("The meeting must end after it starts.")
    if source not in MEETING_SOURCES:
        raise ValueError(f"A meeting's source must be one of {MEETING_SOURCES}.")
    conn = _connect(db_path)
    try:
        with conn:
            return conn.execute(
                """INSERT INTO meetings (deal_id, title, client_name, starts_at, ends_at, location, notes, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (deal_id, title, (client_name or "").strip() or None, stamp(starts_at),
                 stamp(ends_at) if ends_at else None, (location or "").strip() or None, (notes or "").strip() or None,
                 source)).lastrowid
    finally:
        conn.close()


def save_brief(meeting_id, brief, now, db_path=None):
    """Keep a prep brief on its meeting. brief is a dict: {text, unverified}."""
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute("UPDATE meetings SET brief = ?, brief_at = ? WHERE id = ?",
                         (json.dumps(brief), stamp(now), meeting_id))
    finally:
        conn.close()


def add_email_to_deal(email_id, deal_id, db_path=None):
    """Add an email's attachments to a deal as documents (source Email, status Received) and mark it added.

    No file is downloaded: no real inbox is connected yet, so the documents are records of what
    arrived. Returns the new document IDs.
    """
    conn = _connect(db_path)
    try:
        with conn:
            email = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
            if email is None:
                raise ValueError("That email could not be found.")
            if email["status"] != "new":
                raise ValueError("That email has already been dealt with.")
            if conn.execute("SELECT 1 FROM deals WHERE id = ?", (deal_id,)).fetchone() is None:
                raise ValueError("Choose a deal to add it to.")
            names = json.loads(email["attachment_names"] or "[]")
            if not names:
                raise ValueError("This email has no attachments to add.")
            ids = [conn.execute("INSERT INTO documents (deal_id, filename, source, status) VALUES (?, ?, 'Email', 'Received')",
                                (deal_id, name)).lastrowid for name in names]
            conn.execute("UPDATE emails SET status = 'added', deal_id = ? WHERE id = ?", (deal_id, email_id))
            return ids
    finally:
        conn.close()


def dismiss_email(email_id, db_path=None):
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute("UPDATE emails SET status = 'dismissed' WHERE id = ? AND status = 'new'", (email_id,))
    finally:
        conn.close()


def to_datetime(day, time):
    return datetime.combine(day, time)
