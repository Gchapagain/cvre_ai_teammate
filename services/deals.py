"""Creating and adding to deals. These are the only writes the screens make.

Viewing never goes through here: the screens read with a read-only connection (app/queries.py).
"""

import json
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


NAME_MAX = 100
DETAILS = {"name": "Property name", "property_type": "Property type", "submarket": "Location"}
# OM slides that print the deal's name (besides every footer): renaming sends them back for approval.
NAME_SLOT = "property.name"


def check_name(name, deal_id=None, db_path=None):
    """(clean name, warning or None). Raises ValueError for a name that cannot be saved.

    Trims spaces; must not be empty; at most NAME_MAX characters. A name another deal already uses is
    only a warning: two properties can share a name.
    """
    clean = " ".join((name or "").split())
    if not clean:
        raise ValueError("Give the property a name.")
    if len(clean) > NAME_MAX:
        raise ValueError(f"Keep the name to {NAME_MAX} characters or fewer (this one has {len(clean)}).")
    conn = db.get_connection(db_path)  # a plain read: the dialog checks as the person types, so nothing is written here
    try:
        same = conn.execute("SELECT COUNT(*) FROM deals WHERE LOWER(name) = LOWER(?) AND id IS NOT ?",
                            (clean, deal_id)).fetchone()[0]
    finally:
        conn.close()
    return clean, (f"Another deal is already called '{clean}'. You can keep it, but a different name avoids mix-ups."
                   if same else None)


def _clean_details(property_type, location):
    if property_type not in (None, "") and property_type not in PROPERTY_TYPES:
        raise ValueError(f"Property type must be one of: {', '.join(PROPERTY_TYPES)}.")
    location = " ".join((location or "").split()) or None
    if location and len(location) > NAME_MAX:
        raise ValueError(f"Keep the location to {NAME_MAX} characters or fewer.")
    return property_type or None, location


def quick_create(name, property_type=None, location=None, db_path=None):
    """The "+" button: a deal with just a name (type and location optional). Returns (deal ID, warning or None)."""
    clean, warning = check_name(name, db_path=db_path)
    property_type, location = _clean_details(property_type, location)
    return create_deal(clean, property_type, location, db_path=db_path), warning


def _sync_om_name(conn, deal_id, old, new, user):
    """Keep the OM's property name in step with a rename. Returns True when an approval was taken back.

    - The OM takes the name from the deal record: an earlier approval no longer matches the new name, so
      the engine shows it as waiting again on its own (and an Undo makes it match, and approved, again).
    - The broker typed the same name into the OM: it follows the rename and waits for approval again.
    - The broker gave the OM a different name on purpose: left alone.
    """
    from services import om_slots  # imported here: om_slots pulls in the OM modules, which this module does not need
    row = conn.execute("SELECT * FROM om_slots WHERE deal_id = ? AND slot_id = ?", (deal_id, NAME_SLOT)).fetchone()
    if row is None:
        return False
    source, value = json.loads(row["source"] or "{}"), json.loads(row["value"]) if row["value"] else None
    if source.get("kind") in ("calculated", "document_field"):
        was_approved = row["status"] == "approved" and value == old
    elif value != old:
        return False
    else:
        was_approved = row["status"] == "approved"
        om_slots._upsert(conn, deal_id, NAME_SLOT, new, "broker-provided",
                         {"kind": "broker_input", "detail": f"Follows the deal's new name (renamed by {user})"}, user)
    if was_approved:
        # Logged as a person's take-back, so the AI Teammate never re-approves the new name by itself.
        om_slots.log(conn, deal_id, "unapprove", NAME_SLOT, user)
    return was_approved


def update_details(deal_id, changes, user, db_path=None):
    """Rename a deal or change its type or location: one person's click, never the AI.

    changes: {field: new value} for fields in DETAILS. Returns {"changed": [labels], "change_ids": [...],
    "warning": str or None, "reapprove": [slide titles]}. Each change is a row in deal_changes and an OM event.
    Files on disk are never renamed (uploads are kept by deal ID).
    """
    unknown = set(changes) - set(DETAILS)
    if unknown:
        raise ValueError(f"These cannot be changed here: {', '.join(sorted(unknown))}.")
    warning = None
    if "name" in changes:
        changes["name"], warning = check_name(changes["name"], deal_id, db_path)
    if "property_type" in changes:
        changes["property_type"] = _clean_details(changes["property_type"], None)[0]
    if "submarket" in changes:
        changes["submarket"] = _clean_details(None, changes["submarket"])[1]
    result = {"changed": [], "change_ids": [], "warning": warning, "reapprove": []}
    db.init_db(db_path)
    conn = db.get_connection(db_path)
    try:
        with conn:
            deal = conn.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
            if deal is None:
                raise ValueError("That deal could not be found.")
            for field, new in changes.items():
                if (deal[field] or None) == (new or None):
                    continue
                result["change_ids"].append(_change(conn, deal_id, field, deal[field], new, user))
                result["changed"].append(DETAILS[field])
                if field == "name" and _sync_om_name(conn, deal_id, deal[field], new, user):
                    result["reapprove"] = _name_slides()
    finally:
        conn.close()
    return result


def _change(conn, deal_id, field, old, new, user):
    from services import om_slots
    conn.execute(f"UPDATE deals SET {field} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new, deal_id))
    om_slots.log(conn, deal_id, "renamed" if field == "name" else "details", f"{DETAILS[field]}: {old or '-'} → {new or '-'}", user)
    return conn.execute("INSERT INTO deal_changes (deal_id, field, old_value, new_value, user) VALUES (?, ?, ?, ?, ?)",
                        (deal_id, field, old, new, user)).lastrowid


def _name_slides():
    from services import om_template
    return [slide.title for slide in om_template.load().slides if NAME_SLOT in slide.slots]


def undo_changes(change_ids, user, db_path=None):
    """Put back the old values of the given changes (the "Undo" after a rename). Returns the labels undone.

    A field that was changed again since is left alone, so an Undo never overwrites a newer edit.
    """
    undone = []
    db.init_db(db_path)
    conn = db.get_connection(db_path)
    try:
        with conn:
            for change_id in change_ids:
                row = conn.execute("SELECT * FROM deal_changes WHERE id = ? AND reverted_at IS NULL", (change_id,)).fetchone()
                if row is None:
                    continue
                current = conn.execute(f"SELECT {row['field']} FROM deals WHERE id = ?", (row["deal_id"],)).fetchone()[0]
                if (current or None) != (row["new_value"] or None):
                    continue
                if row["field"] == "name":
                    _sync_om_name(conn, row["deal_id"], row["new_value"], row["old_value"], user)
                _change(conn, row["deal_id"], row["field"], row["new_value"], row["old_value"], user)
                conn.execute("UPDATE deal_changes SET reverted_at = CURRENT_TIMESTAMP WHERE id = ?", (change_id,))
                undone.append(DETAILS[row["field"]])
    finally:
        conn.close()
    return undone


def set_status(deal_id, status, db_path=None):
    _write(db_path, "UPDATE deals SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, deal_id))


def _safe_name(filename):
    """The file's own name with anything that is not a plain file-name character removed."""
    name = re.sub(r"[^A-Za-z0-9._ ()-]", "_", Path(filename).name).strip(" .")
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


PHOTO_TYPES = {".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff", ".webp": b"RIFF"}
PHOTO_MAX_BYTES = 5 * 1024 * 1024


def set_photo(deal_id, filename, data, db_path=None, upload_dir=None):
    """Save a person's photo of the property and use it instead of the illustration. Returns its path.

    Only PNG, JPEG or WebP up to 5 MB, and the file must really be that kind of image.
    Earlier photos are kept on disk; the deal points at the newest.
    """
    suffix = Path(filename or "").suffix.lower()
    if suffix not in PHOTO_TYPES:
        raise ValueError("Use a PNG, JPEG or WebP picture.")
    if len(data) > PHOTO_MAX_BYTES:
        raise ValueError("The picture is larger than 5 MB.")
    if not data.startswith(PHOTO_TYPES[suffix]) or (suffix == ".webp" and data[8:12] != b"WEBP"):
        raise ValueError("That file is not a readable picture.")
    folder = Path(upload_dir or UPLOAD_DIR) / str(deal_id) / "photos"
    folder.mkdir(parents=True, exist_ok=True)
    count = 1
    while any(folder.glob(f"photo_{count}.*")):  # never overwrite an earlier photo
        count += 1
    path = folder / f"photo_{count}{suffix}"
    path.write_bytes(data)
    _write(db_path, "UPDATE deals SET photo_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (str(path), deal_id))
    return path
