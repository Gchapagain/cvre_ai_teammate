"""Creating and adding to deals. These are the only writes the screens make.

Viewing never goes through here: the screens read with a read-only connection (app/queries.py).
"""

import os
import re
from pathlib import Path

import db

PROPERTY_TYPES = ["Industrial", "Office", "Retail", "Multifamily", "Flex", "Other"]
NOTE_SOURCES = ("Recording", "Typed")
# Uploaded files are kept here, outside git. CBRE_UPLOAD_DIR points tools at a throwaway folder.
UPLOAD_DIR = Path(os.getenv("CBRE_UPLOAD_DIR") or Path(__file__).resolve().parent.parent / "uploads")


def _write(db_path, sql, params):
    db.init_db(db_path)  # also adds any table a database from an older version is missing
    conn = db.get_connection(db_path)
    try:
        with conn:
            return conn.execute(sql, params).lastrowid
    finally:
        conn.close()


def create_deal(name, property_type=None, location=None, status="New", db_path=None):
    """Add a deal and return its ID. A deal must have a name; everything else may be blank."""
    name = (name or "").strip()
    if not name:
        raise ValueError("A deal needs a name.")
    return _write(db_path, "INSERT INTO deals (name, property_type, submarket, status) VALUES (?, ?, ?, ?)",
                  (name, property_type or None, (location or "").strip() or None, status))


def set_status(deal_id, status, db_path=None):
    _write(db_path, "UPDATE deals SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, deal_id))


def _safe_name(filename):
    """The file's own name with anything that is not a plain file-name character removed."""
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(filename).name).strip(" .")
    return name or "upload"


def save_upload(deal_id, filename, data, db_path=None, upload_dir=None):
    """Save an uploaded file to disk and record it as Received. Returns (document ID, path)."""
    folder = Path(upload_dir or UPLOAD_DIR) / str(deal_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = _safe_name(filename)
    path = folder / name
    count = 1
    while path.exists():  # never overwrite an earlier upload
        count += 1
        path = folder / f"{Path(name).stem} ({count}){Path(name).suffix}"
    path.write_bytes(data)
    document_id = _write(
        db_path,
        "INSERT INTO documents (deal_id, filename, file_path, source, status) VALUES (?, ?, ?, 'Upload', 'Received')",
        (deal_id, path.name, str(path)),
    )
    return document_id, path


def set_document_type(document_id, doc_type, db_path=None):
    _write(db_path, "UPDATE documents SET doc_type = ? WHERE id = ?", (doc_type, document_id))


def add_note(deal_id, text, source, db_path=None):
    """Save a note exactly as the person left it. Returns the note ID."""
    text = (text or "").strip()
    if not text:
        raise ValueError("The note is empty.")
    if source not in NOTE_SOURCES:
        raise ValueError(f"A note's source must be one of {NOTE_SOURCES}.")
    return _write(db_path, "INSERT INTO deal_notes (deal_id, text, source) VALUES (?, ?, ?)", (deal_id, text, source))
