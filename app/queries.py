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


def schema_version():
    """The schema version recorded in the database (0 for one made before versions were recorded)."""
    conn = _connect()
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def projects():
    """Every deal for the Home project strip, with the counts its progress is calculated from.

    Needing attention first and approved last, like the deals list. Research counts only real
    findings: simulated ones can never be accepted, so they never count as reviewed or waiting.
    """
    return _all(
        """SELECT d.id, d.name, d.property_type, d.submarket, d.status, d.photo_path,
                  (SELECT COUNT(*) FROM documents x WHERE x.deal_id = d.id) AS documents,
                  (SELECT COUNT(*) FROM rent_roll_units x WHERE x.deal_id = d.id) AS units,
                  (SELECT COUNT(*) FROM flags x WHERE x.deal_id = d.id AND x.status = 'open') AS open_flags,
                  (SELECT COUNT(*) FROM drafts x WHERE x.deal_id = d.id) AS drafts,
                  (SELECT COUNT(*) FROM research_findings x
                    WHERE x.deal_id = d.id AND x.simulated = 0 AND x.status = 'new') AS findings_new,
                  (SELECT COUNT(*) FROM research_findings x
                    WHERE x.deal_id = d.id AND x.simulated = 0 AND x.status != 'new') AS findings_reviewed
           FROM deals d
           ORDER BY CASE WHEN open_flags > 0 OR d.status = 'Needs Review' THEN 0
                         WHEN d.status = 'Approved' THEN 2 ELSE 1 END, d.id"""
    )


def open_flag_count():
    return _one("SELECT COUNT(*) AS n FROM flags WHERE status = 'open'")["n"]


def feed_rows():
    """Everything the Home feed is built from, read fresh each time (services/feed.py turns it into items).

    A database from before the feed tables simply has no meetings, emails or saved item state.
    """
    rows = {
        "flags": _all("""SELECT f.id, f.deal_id, d.name AS deal_name, f.unit_number, f.rule, f.field, f.actual_value,
                                f.threshold, f.message, f.created_at
                         FROM flags f JOIN deals d ON d.id = f.deal_id WHERE f.status = 'open' ORDER BY f.id"""),
        "review_deals": _all("SELECT id AS deal_id, name AS deal_name, updated_at FROM deals "
                             "WHERE status = 'Needs Review' ORDER BY id"),
        "documents": _all("""SELECT x.id, x.deal_id, d.name AS deal_name, x.filename, x.status, x.source, x.received_at
                             FROM documents x JOIN deals d ON d.id = x.deal_id
                             WHERE x.status IN ('Received', 'Needs password') ORDER BY x.id"""),
        "drafts": _all("""SELECT x.id, x.deal_id, d.name AS deal_name, x.created_at FROM drafts x
                          JOIN deals d ON d.id = x.deal_id
                          WHERE x.status = 'Generated, not sent'
                            AND x.id = (SELECT MAX(y.id) FROM drafts y WHERE y.deal_id = x.deal_id) ORDER BY x.id"""),
        "research": _all("""SELECT x.deal_id, d.name AS deal_name, COUNT(*) AS waiting, MAX(x.id) AS newest,
                                   MAX(x.fetched_at) AS fetched_at
                            FROM research_findings x JOIN deals d ON d.id = x.deal_id
                            WHERE x.status = 'new' AND x.simulated = 0 GROUP BY x.deal_id ORDER BY x.deal_id"""),
    }
    try:
        rows["meetings"] = _all("""SELECT m.*, d.name AS deal_name FROM meetings m LEFT JOIN deals d ON d.id = m.deal_id
                                   ORDER BY m.starts_at, m.id""")
        rows["emails"] = _all("""SELECT e.*, d.name AS deal_name FROM emails e LEFT JOIN deals d ON d.id = e.deal_id
                                 WHERE e.status = 'new' ORDER BY e.received_at DESC, e.id""")
        rows["state"] = {row["item_key"]: row for row in _all("SELECT * FROM notification_state")}
    except sqlite3.OperationalError:
        rows.update(meetings=[], emails=[], state={})
    for email in rows["emails"]:
        email["attachment_names"] = json.loads(email["attachment_names"] or "[]")
    return rows


def deal_choices():
    """(id, name) for every deal, for pickers."""
    return [(row["id"], row["name"]) for row in _all("SELECT id, name FROM deals ORDER BY name")]
