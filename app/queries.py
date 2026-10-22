"""Every database read the screens need. The app only reads: it opens the database read-only."""

import json
import sqlite3

import db


def database_ready():
    """True when the database file exists and holds sample deals. Never creates the file."""
    if not db.DB_PATH.exists():
        return False
    try:
        return _one("SELECT COUNT(*) AS n FROM deals")["n"] > 0
    except sqlite3.Error:
        return False


def _connect():
    conn = sqlite3.connect(f"file:{db.DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _all(sql, params=()):
    conn = _connect()
    try:
        return [dict(row) for row in conn.execute(sql, params)]
    finally:
        conn.close()


def _one(sql, params=()):
    rows = _all(sql, params)
    return rows[0] if rows else None


def demo_user(role):
    return _one("SELECT email, full_name, role FROM users WHERE role = ? ORDER BY id", (role,))


def dashboard_stats():
    return _one(
        """SELECT
             (SELECT COUNT(*) FROM deals WHERE status != 'Approved')     AS active_deals,
             (SELECT COUNT(*) FROM deals WHERE status = 'Needs Review')  AS needs_review,
             (SELECT COUNT(*) FROM flags WHERE status = 'open')          AS anomalies"""
    )


def needs_attention(deal):
    """A deal a person should look at first: it is waiting for review or has an anomaly."""
    return deal["status"] == "Needs Review" or deal["flag_count"] > 0


def list_deals():
    """Every deal, the ones needing attention first, approved ones last."""
    return _all(
        """SELECT d.id, d.name, d.property_type, d.submarket, d.status,
                  (SELECT COUNT(*) FROM rent_roll_units u WHERE u.deal_id = d.id) AS unit_count,
                  (SELECT COUNT(*) FROM flags f WHERE f.deal_id = d.id AND f.status = 'open') AS flag_count
           FROM deals d
           ORDER BY CASE WHEN flag_count > 0 OR d.status = 'Needs Review' THEN 0
                         WHEN d.status = 'Approved' THEN 2 ELSE 1 END, d.id"""
    )


def get_deal(deal_id):
    return _one("SELECT * FROM deals WHERE id = ?", (deal_id,))


def deal_units(deal_id):
    return _all("SELECT * FROM rent_roll_units WHERE deal_id = ? ORDER BY id", (deal_id,))


def deal_flags(deal_id):
    return _all("SELECT * FROM flags WHERE deal_id = ? ORDER BY id", (deal_id,))


def deal_t12(deal_id):
    return _all(
        "SELECT category, line_item, period, amount FROM t12_line_items WHERE deal_id = ? ORDER BY id", (deal_id,)
    )


def latest_draft(deal_id):
    """The newest draft narrative, or None. A database from before drafts were reshaped has none."""
    try:
        return _one("SELECT id, deal_id, text, status, edited, created_at FROM drafts WHERE deal_id = ? "
                    "ORDER BY id DESC LIMIT 1", (deal_id,))
    except sqlite3.OperationalError:
        return None


def deal_notes(deal_id):
    """Notes on a deal, oldest first. A database from before notes existed simply has none."""
    try:
        return _all("SELECT id, text, source, created_at FROM deal_notes WHERE deal_id = ? ORDER BY id", (deal_id,))
    except sqlite3.OperationalError:
        return []


def deal_findings(deal_id):
    """Saved research findings with their sources decoded. A database from before research has none."""
    try:
        rows = _all("SELECT * FROM research_findings WHERE deal_id = ? ORDER BY id", (deal_id,))
    except sqlite3.OperationalError:
        return []
    for row in rows:
        row["sources"] = json.loads(row["sources"])
    return rows


def deal_recommendations(deal_id):
    """Saved recommendations (rule decisions and AI suggestions) with evidence decoded."""
    try:
        rows = _all("SELECT * FROM recommendations WHERE deal_id = ? ORDER BY id", (deal_id,))
    except sqlite3.OperationalError:
        return []
    for row in rows:
        row["evidence"] = json.loads(row["evidence"])
    return rows


def deal_edits(deal_id):
    try:
        return _all("SELECT * FROM edits WHERE deal_id = ? ORDER BY id", (deal_id,))
    except sqlite3.OperationalError:
        return []


def deal_events(deal_id):
    """The activity timeline, newest first."""
    try:
        return _all("SELECT * FROM deal_events WHERE deal_id = ? ORDER BY id DESC", (deal_id,))
    except sqlite3.OperationalError:
        return []


def deal_documents(deal_id):
    return _all("SELECT * FROM documents WHERE deal_id = ? ORDER BY id", (deal_id,))
