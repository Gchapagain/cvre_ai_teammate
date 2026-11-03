"""SQLite schema and connection helpers for CBRE AI Teammate."""

import os
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def project_path(path):
    """A path from the settings or the database, made absolute from the project folder if it is relative."""
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


# CBRE_DB_PATH points the app at another database: tools/screenshots.py uses a throwaway one, and the
# deployed app on Streamlit Cloud uses the committed sample_data/demo.db (set in the app's Secrets).
DB_PATH = project_path(os.getenv("CBRE_DB_PATH") or "cbre_ai_teammate.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    full_name     TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('Broker')),  -- brokers are the only user type
    password_hash TEXT,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    title         TEXT,  -- for the OM's contacts page (Settings)
    phone         TEXT
);

CREATE TABLE IF NOT EXISTS deals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    property_type TEXT,
    submarket     TEXT,
    address       TEXT,
    status        TEXT NOT NULL DEFAULT 'New',
    owner_user_id INTEGER REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_by   TEXT,  -- the person who approved the deal, or NULL
    approved_at   TEXT,
    photo_path    TEXT   -- a person's own photo of the property; NULL shows the illustration for its type
);

-- source: where the file came from (Upload or Email).
-- status: Received means the file has arrived but has not been read yet.
-- used_for: what the AI used the file for (for example Rent roll, T-12).
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id     INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    doc_type    TEXT,
    file_path   TEXT,
    source      TEXT NOT NULL DEFAULT 'Upload',
    status      TEXT NOT NULL
                CHECK (status IN ('Received', 'Read', 'Reference only', 'Needs password')),
    used_for    TEXT,
    uploaded_by INTEGER REFERENCES users(id),
    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rent_roll_units (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id      INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    document_id  INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    unit_number  TEXT NOT NULL,
    tenant_name  TEXT,
    square_feet  REAL,
    lease_start  TEXT,
    lease_end    TEXT,
    monthly_rent REAL,
    annual_rent  REAL,
    rent_per_sf  REAL,
    lease_type   TEXT,
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS t12_line_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id     INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    category    TEXT NOT NULL CHECK (category IN ('Income', 'Expense', 'Total')),
    line_item   TEXT NOT NULL,
    period      TEXT NOT NULL,
    amount      REAL,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Validation flags. A flag points at data, it never changes or hides it.
-- actual_value and threshold are text so they can hold a number, a date, or a
-- bad value exactly as it was found.
CREATE TABLE IF NOT EXISTS flags (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id           INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    rent_roll_unit_id INTEGER REFERENCES rent_roll_units(id) ON DELETE CASCADE,
    unit_number       TEXT,
    rule              TEXT NOT NULL,
    field             TEXT,
    actual_value      TEXT,
    threshold         TEXT,
    message           TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- What a person decided. open: not reviewed yet. confirmed: a person says the value is right.
    -- corrected: the value was changed and the rule no longer fires. A flag row is never deleted.
    status            TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'confirmed', 'corrected')),
    resolved_by       TEXT,
    resolved_at       TEXT,
    resolution_reason TEXT,
    resolution_note   TEXT
);

CREATE TABLE IF NOT EXISTS valuation_outputs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id     INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    metric      TEXT NOT NULL,
    value       REAL,
    unit        TEXT,
    assumptions TEXT,
    created_by  INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Draft pricing narratives. The AI writes the first version; only a person can approve one.
-- edited is 1 once a person has changed the text.
CREATE TABLE IF NOT EXISTS drafts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id    INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    text       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'Generated, not sent'
               CHECK (status IN ('Generated, not sent', 'Flagged for producer', 'Approved')),
    edited     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Market research findings for a deal. Advisory only: nothing is used until a person accepts it.
-- sources is a JSON list of {name, url, tier, date, figure, metric}.
CREATE TABLE IF NOT EXISTS research_findings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id    INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    topic      TEXT NOT NULL,
    summary    TEXT NOT NULL,
    sources    TEXT NOT NULL DEFAULT '[]',
    skipped    INTEGER NOT NULL DEFAULT 0,
    status     TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'accepted', 'dismissed')),
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Which connection found it (see services/connections). Simulated findings come from demo
    -- connections: they are shown with a SIMULATED chip and can never be accepted or counted.
    connection_id TEXT NOT NULL DEFAULT 'web_search_tavily',
    simulated  INTEGER NOT NULL DEFAULT 0
);

-- Recommendations for a deal. kind 'rule' is calculated in code from the deal's data (rule_key
-- identifies which rule and unit, so a person's Accept / Dismiss sticks). kind 'ai' is written by
-- the AI from real research findings and checked in code. evidence is a JSON list of sources.
CREATE TABLE IF NOT EXISTS recommendations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id    INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('rule', 'ai')),
    rule_key   TEXT,
    title      TEXT NOT NULL,
    priority   TEXT NOT NULL CHECK (priority IN ('High', 'Medium', 'Low')),
    why        TEXT NOT NULL,
    next_step  TEXT NOT NULL,
    evidence   TEXT NOT NULL DEFAULT '[]',
    status     TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'accepted', 'dismissed')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (deal_id, rule_key)
);

-- Every change a person made to an extracted value. old_value and new_value are JSON, so a number
-- stays a number. The first edit of a field holds the original extracted value. Undo sets
-- reverted_at; rows are never deleted. Edits saved together share a batch_id (for example a rent
-- change and the rent/SF recomputed from it), and are undone together.
CREATE TABLE IF NOT EXISTS edits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id     INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    unit_id     INTEGER REFERENCES rent_roll_units(id) ON DELETE SET NULL,
    unit_number TEXT,
    field       TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT,
    reason      TEXT NOT NULL,
    source      TEXT NOT NULL CHECK (source IN ('Manual', 'AI-assisted')),
    user        TEXT NOT NULL,
    batch_id    TEXT NOT NULL,
    derived     INTEGER NOT NULL DEFAULT 0,  -- 1 when the value was recomputed from another change
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reverted_at TEXT
);

-- The deal's activity timeline: edits, undos, confirmations, approvals and reopenings.
-- A reopening's reason is kept here (the reopen log).
CREATE TABLE IF NOT EXISTS deal_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id    INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('edit', 'undo', 'confirmed', 'approved', 'reopened')),
    user       TEXT NOT NULL,
    reason     TEXT,
    detail     TEXT,
    source     TEXT,
    batch_id   TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- One row per AI request made from the app, for the rate limits in services/ai_limits.py.
-- Meetings shown on Home. Times are the broker's local wall-clock time ('YYYY-MM-DD HH:MM:SS').
-- source Sample rows are made up for the demo and are dated on SAMPLE_ANCHOR_DAY: Home shifts them to
-- the same position relative to today, so the demo always has meetings. brief is the AI prep brief
-- (written only when a person clicks Prep brief), brief_at when it was written.
CREATE TABLE IF NOT EXISTS meetings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id     INTEGER REFERENCES deals(id) ON DELETE SET NULL,
    title       TEXT NOT NULL,
    client_name TEXT,
    starts_at   TEXT NOT NULL,
    ends_at     TEXT,
    location    TEXT,
    notes       TEXT,
    source      TEXT NOT NULL DEFAULT 'Manual'
                CHECK (source IN ('Manual', 'Sample', 'Google Calendar', 'Outlook Calendar')),
    brief       TEXT,
    brief_at    TEXT,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Emails shown on Home. No real inbox is connected yet: every row so far is source Sample.
-- attachment_names is a JSON list of file names. status: new, added (to a deal, as documents), dismissed.
CREATE TABLE IF NOT EXISTS emails (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id          INTEGER REFERENCES deals(id) ON DELETE SET NULL,
    sender           TEXT NOT NULL,
    subject          TEXT NOT NULL,
    preview          TEXT,
    received_at      TEXT NOT NULL,
    attachment_names TEXT NOT NULL DEFAULT '[]',
    status           TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'added', 'dismissed')),
    source           TEXT NOT NULL DEFAULT 'Sample' CHECK (source IN ('Sample', 'Gmail', 'Outlook')),
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- What a person did with a Home feed item. The feed itself is built live from the tables above and
-- the deal tables, so it is never stale; only this per-item state is stored. item_key is e.g. 'flag:12'.
CREATE TABLE IF NOT EXISTS notification_state (
    item_key      TEXT PRIMARY KEY,
    read_at       TEXT,
    snoozed_until TEXT,
    dismissed_at  TEXT
);

-- Totals as stated on a rent roll document (its "Total" row), kept so validation can check that the
-- unit rents add up to them. Not every rent roll has one.
CREATE TABLE IF NOT EXISTS rent_roll_totals (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id            INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    document_id        INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    total_sf           REAL,
    total_monthly_rent REAL,
    total_annual_rent  REAL,
    created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---- Offering Memorandum (OM) Builder. The template (slots, slides) lives in templates/om_v1.json. ----
-- om_slots: a person's value or decision for one template slot. Calculated and auto-filled values are
-- worked out live from the deal's data and are not stored, except as the snapshot a person approved.
-- value and source are JSON. status: empty, auto-filled, ai-draft, broker-provided, approved.
CREATE TABLE IF NOT EXISTS om_slots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id    INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    slot_id    TEXT NOT NULL,
    value      TEXT,
    status     TEXT NOT NULL DEFAULT 'empty'
               CHECK (status IN ('empty', 'auto-filled', 'ai-draft', 'broker-provided', 'approved')),
    source     TEXT NOT NULL DEFAULT '{}',
    updated_by TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (deal_id, slot_id)
);

-- Photos for the OM, saved under om_assets/ (git-ignored). sample = made-up illustration for the demo.
CREATE TABLE IF NOT EXISTS om_assets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id    INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    file_path  TEXT NOT NULL,
    kind       TEXT CHECK (kind IN ('aerial', 'exterior', 'interior', 'site_plan', 'map')),
    caption    TEXT,
    slot_id    TEXT,
    position   INTEGER NOT NULL DEFAULT 0,
    sample     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    original_path TEXT,                          -- the upload exactly as received, never changed
    fit        TEXT NOT NULL DEFAULT 'whole' CHECK (fit IN ('whole', 'fill'))  -- 'fill' crops, only if the broker chose it
);

-- Questions the OM Builder asked, to the broker or for the client. status: open, answered, skipped.
CREATE TABLE IF NOT EXISTS om_questions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id     INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    slot_id     TEXT,
    audience    TEXT NOT NULL CHECK (audience IN ('broker', 'client')),
    text        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'skipped')),
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    answered_at TEXT
);

-- Financial assumptions for the cash flow (market rent, escalation, lease-up, ...). value and source are
-- JSON. Only approved ones are used in any calculation; the AI may only propose.
CREATE TABLE IF NOT EXISTS om_assumptions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id    INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT '{}',
    status     TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved')),
    updated_by TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (deal_id, key)
);

-- Every OM file made. unapproved is a JSON list of required slots not approved at export time.
CREATE TABLE IF NOT EXISTS om_exports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id     INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('draft', 'final')),
    format      TEXT NOT NULL CHECK (format IN ('pptx', 'pdf')),
    completion  REAL NOT NULL,
    unapproved  TEXT NOT NULL DEFAULT '[]',
    created_by  TEXT,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    file_path   TEXT
);

-- What a person did on the OM, with a time, for "OM time so far" (no time-saved claim).
CREATE TABLE IF NOT EXISTS om_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id    INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    action     TEXT NOT NULL,
    detail     TEXT,
    user       TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_time ON ai_usage(created_at);

-- One row per connection (data source) once someone has switched it or used it.
-- A connection with no row uses its default from services/connections.
CREATE TABLE IF NOT EXISTS connections (
    id           TEXT PRIMARY KEY,
    enabled      INTEGER NOT NULL,
    last_used_at TEXT
);

-- query holds generic terms only (property type + submarket).
CREATE TABLE IF NOT EXISTS research_jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id       INTEGER REFERENCES deals(id) ON DELETE CASCADE,
    property_type TEXT,
    submarket     TEXT,
    query         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'Queued',
    requested_by  INTEGER REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at  TEXT
);

-- published_date is when the source says it was published (empty if it does not say).
-- retrieved_at is when we fetched it.
CREATE TABLE IF NOT EXISTS research_sources (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         INTEGER NOT NULL REFERENCES research_jobs(id) ON DELETE CASCADE,
    url            TEXT NOT NULL,
    title          TEXT,
    publisher      TEXT,
    tier           INTEGER CHECK (tier IN (1, 2, 3)),
    snippet        TEXT,
    published_date TEXT,
    retrieved_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS research_briefs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       INTEGER NOT NULL REFERENCES research_jobs(id) ON DELETE CASCADE,
    deal_id      INTEGER REFERENCES deals(id) ON DELETE CASCADE,
    summary      TEXT NOT NULL,
    source_label TEXT,
    status       TEXT NOT NULL DEFAULT 'Pending review',
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_documents_deal        ON documents(deal_id);
CREATE INDEX IF NOT EXISTS idx_rent_roll_units_deal  ON rent_roll_units(deal_id);
CREATE INDEX IF NOT EXISTS idx_t12_line_items_deal   ON t12_line_items(deal_id);
-- Notes a person saved on a deal. The text is stored exactly as the person left it.
-- Recording means it started as an AI transcript the person then checked; the audio itself is never stored.
CREATE TABLE IF NOT EXISTS deal_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id    INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    text       TEXT NOT NULL,
    source     TEXT NOT NULL CHECK (source IN ('Recording', 'Typed')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Every rename or change of a deal's details: one row per field, so Undo can put the old value back.
-- reverted_at is set when a change was undone.
CREATE TABLE IF NOT EXISTS deal_changes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id     INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    field       TEXT NOT NULL CHECK (field IN ('name', 'property_type', 'submarket')),
    old_value   TEXT,
    new_value   TEXT,
    user        TEXT,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reverted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_deal_notes_deal       ON deal_notes(deal_id);
CREATE INDEX IF NOT EXISTS idx_deal_changes_deal     ON deal_changes(deal_id);
CREATE INDEX IF NOT EXISTS idx_meetings_start        ON meetings(starts_at);
CREATE INDEX IF NOT EXISTS idx_om_slots_deal         ON om_slots(deal_id);
CREATE INDEX IF NOT EXISTS idx_om_assets_deal        ON om_assets(deal_id);
CREATE INDEX IF NOT EXISTS idx_om_events_deal        ON om_events(deal_id);
CREATE INDEX IF NOT EXISTS idx_emails_status         ON emails(status);
CREATE INDEX IF NOT EXISTS idx_edits_deal            ON edits(deal_id);
CREATE INDEX IF NOT EXISTS idx_events_deal           ON deal_events(deal_id);
CREATE INDEX IF NOT EXISTS idx_flags_deal            ON flags(deal_id);
CREATE INDEX IF NOT EXISTS idx_valuation_deal        ON valuation_outputs(deal_id);
CREATE INDEX IF NOT EXISTS idx_drafts_deal           ON drafts(deal_id);
CREATE INDEX IF NOT EXISTS idx_findings_deal         ON research_findings(deal_id);
CREATE INDEX IF NOT EXISTS idx_research_jobs_deal    ON research_jobs(deal_id);
CREATE INDEX IF NOT EXISTS idx_research_sources_job  ON research_sources(job_id);
CREATE INDEX IF NOT EXISTS idx_research_briefs_job   ON research_briefs(job_id);
"""


# Goes up by one with every schema change (new table, new column, changed constraint), and the change
# is described here. init_db stores it in the database (PRAGMA user_version) after migrating.
#   1: deals.photo_path
#   2: meetings, emails and notification_state tables (the Home feed)
#   3: OM Builder tables (om_slots, om_assets, om_questions, om_assumptions, om_exports, om_events),
#      rent_roll_totals, and users.title / users.phone for the OM's contacts page
#   4: deal_changes (renaming a deal and editing its type and location, with Undo)
#   5: om_assets.original_path (the untouched upload) and om_assets.fit ('whole' by default, 'fill' crops)
SCHEMA_VERSION = 5

# Sample meetings and emails are stored on this day; Home moves them to the same place relative to today.
SAMPLE_ANCHOR_DAY = "2000-01-03"


def schema_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def get_connection(db_path=None):
    """Open a connection with foreign keys on and dict-style rows."""
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _retire_old_drafts_table(conn):
    """An earlier version had a drafts table with different columns. Make way for the new one.

    An empty old table is dropped. One with rows is renamed and kept, never deleted.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(drafts)")}
    if not columns or "text" in columns:
        return
    conn.execute("DROP INDEX IF EXISTS idx_drafts_deal")
    if conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]:
        conn.execute("ALTER TABLE drafts RENAME TO drafts_before_review_tab")
    else:
        conn.execute("DROP TABLE drafts")


# Columns added to existing tables after they were first created: table -> [(column, definition)].
# Existing rows keep their data and get the default.
ADDED_COLUMNS = {
    "flags": [
        ("status", "TEXT NOT NULL DEFAULT 'open'"),
        ("resolved_by", "TEXT"), ("resolved_at", "TEXT"), ("resolution_reason", "TEXT"), ("resolution_note", "TEXT"),
    ],
    "deals": [("approved_by", "TEXT"), ("approved_at", "TEXT"), ("photo_path", "TEXT")],
    "users": [("title", "TEXT"), ("phone", "TEXT")],
    "om_assets": [("original_path", "TEXT"), ("fit", "TEXT NOT NULL DEFAULT 'whole' CHECK (fit IN ('whole', 'fill'))")],
    "research_findings": [
        ("connection_id", "TEXT NOT NULL DEFAULT 'web_search_tavily'"),
        ("simulated", "INTEGER NOT NULL DEFAULT 0"),
    ],
}


def _add_missing_columns(conn):
    for table, columns in ADDED_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, definition in columns:
            if existing and column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


USERS_TABLE = """
CREATE TABLE users_broker_only (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    full_name     TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('Broker')),  -- brokers are the only user type
    password_hash TEXT,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)"""
# Columns in other tables that point at a user. A user they point at is never removed.
USER_REFERENCES = [("deals", "owner_user_id"), ("documents", "uploaded_by"), ("valuation_outputs", "created_by"),
                   ("research_jobs", "requested_by")]


def _make_users_broker_only(conn):
    """An earlier version had three roles. Rebuild the users table so Broker is the only one.

    Agent users become Brokers. The other users are dropped unless something refers to them, in
    which case they are kept as Brokers so nothing points at a missing user.
    """
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'").fetchone()
    if not row or "'Analyst'" not in row["sql"]:
        return
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    referenced = " UNION ".join(f"SELECT {column} FROM {table}" for table, column in USER_REFERENCES if table in tables)
    keep = f"role = 'Agent' OR id IN ({referenced})" if referenced else "role = 'Agent'"
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")  # so the swap below does not touch the rows that point at users
    try:
        with conn:
            conn.execute(USERS_TABLE)
            conn.execute("INSERT INTO users_broker_only (id, email, full_name, role, password_hash, created_at) "
                         f"SELECT id, email, full_name, 'Broker', password_hash, created_at FROM users WHERE {keep}")
            conn.execute("DROP TABLE users")
            conn.execute("ALTER TABLE users_broker_only RENAME TO users")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def init_db(db_path=None):
    """Create all tables if they do not exist yet, add any columns a newer version needs, and record the version."""
    conn = get_connection(db_path)
    try:
        _make_users_broker_only(conn)
        _retire_old_drafts_table(conn)
        _add_missing_columns(conn)
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database ready at {DB_PATH}")
