"""SQLite schema and connection helpers for CBRE AI Teammate."""

import os
import sqlite3
from pathlib import Path

# CBRE_DB_PATH lets tools (for example tools/screenshots.py) run the app against a throwaway database.
DB_PATH = Path(os.getenv("CBRE_DB_PATH") or Path(__file__).resolve().parent / "cbre_ai_teammate.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    full_name     TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('Agent', 'Analyst', 'Administrator')),
    password_hash TEXT,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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

CREATE INDEX IF NOT EXISTS idx_deal_notes_deal       ON deal_notes(deal_id);
CREATE INDEX IF NOT EXISTS idx_flags_deal            ON flags(deal_id);
CREATE INDEX IF NOT EXISTS idx_valuation_deal        ON valuation_outputs(deal_id);
CREATE INDEX IF NOT EXISTS idx_drafts_deal           ON drafts(deal_id);
CREATE INDEX IF NOT EXISTS idx_findings_deal         ON research_findings(deal_id);
CREATE INDEX IF NOT EXISTS idx_research_jobs_deal    ON research_jobs(deal_id);
CREATE INDEX IF NOT EXISTS idx_research_sources_job  ON research_sources(job_id);
CREATE INDEX IF NOT EXISTS idx_research_briefs_job   ON research_briefs(job_id);
"""


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


def init_db(db_path=None):
    """Create all tables if they do not exist yet, and add any columns a newer version needs."""
    conn = get_connection(db_path)
    try:
        _retire_old_drafts_table(conn)
        _add_missing_columns(conn)
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database ready at {DB_PATH}")
