"""SQLite schema and connection helpers for CBRE AI Teammate."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "cbre_ai_teammate.db"

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

-- status examples: Uploaded, Extracted, Needs password, Failed
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id     INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    doc_type    TEXT,
    file_path   TEXT,
    status      TEXT NOT NULL DEFAULT 'Uploaded',
    uploaded_by INTEGER REFERENCES users(id),
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    is_flagged   INTEGER NOT NULL DEFAULT 0,
    flag_reason  TEXT,
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
    is_flagged  INTEGER NOT NULL DEFAULT 0,
    flag_reason TEXT,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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

-- Human-in-the-loop: a draft is never sent unless a person approves it.
CREATE TABLE IF NOT EXISTS drafts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id      INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    draft_type   TEXT NOT NULL,
    title        TEXT,
    body         TEXT NOT NULL,
    source_label TEXT,
    status       TEXT NOT NULL DEFAULT 'Pending review'
                 CHECK (status IN ('Pending review', 'Approved', 'Rejected')),
    created_by   INTEGER REFERENCES users(id),
    reviewed_by  INTEGER REFERENCES users(id),
    reviewed_at  TEXT,
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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

CREATE TABLE IF NOT EXISTS research_sources (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       INTEGER NOT NULL REFERENCES research_jobs(id) ON DELETE CASCADE,
    url          TEXT NOT NULL,
    title        TEXT,
    publisher    TEXT,
    tier         INTEGER CHECK (tier IN (1, 2, 3)),
    snippet      TEXT,
    retrieved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
CREATE INDEX IF NOT EXISTS idx_valuation_deal        ON valuation_outputs(deal_id);
CREATE INDEX IF NOT EXISTS idx_drafts_deal           ON drafts(deal_id);
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


def init_db(db_path=None):
    """Create all tables if they do not exist yet."""
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database ready at {DB_PATH}")
