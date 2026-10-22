"""Resolving flags: a person fixes a value, confirms a flagged value is right, undoes a change, or
approves the deal. Every change keeps who, when, why and the value before.

Nothing here is called by the AI on its own. AI-assisted changes arrive here only after a person
clicks Apply, and are saved the same way as manual ones, marked "AI-assisted".
"""

import json
import uuid
from datetime import date

import db
from services import validation

MANUAL, AI_ASSISTED = "Manual", "AI-assisted"
CONFIRM_REASONS = ["Special lease - verified", "Confirmed with property manager", "Source file is right", "Other"]

# Fields a person may change, with their label and type.
EDITABLE = {
    "tenant_name": ("Tenant", "text"),
    "square_feet": ("SF", "number"),
    "monthly_rent": ("Monthly rent", "number"),
    "annual_rent": ("Annual rent", "number"),
    "lease_start": ("Lease start", "date"),
    "lease_end": ("Lease end", "date"),
    "lease_type": ("Lease type", "text"),
}
LABELS = {**{field: label for field, (label, _) in EDITABLE.items()}, "rent_per_sf": "Rent / SF", "unit_number": "Unit"}


class Locked(Exception):
    """The deal is approved, so its values and flags cannot be changed until it is reopened."""


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse(field, raw):
    """Turn what a person typed into a value of the right type. Raises ValueError with a plain reason."""
    if field not in EDITABLE:
        raise ValueError(f"'{field}' cannot be edited.")
    label, kind = EDITABLE[field]
    text = str(raw).strip() if raw is not None else ""
    if not text:
        raise ValueError(f"{label} cannot be empty.")
    if kind == "number":
        try:
            value = float(text.replace(",", "").replace("$", "").strip())
        except ValueError:
            raise ValueError(f"{label} must be a number, not '{text}'.") from None
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"{label} must be a number.")
        return int(value) if field == "square_feet" and value.is_integer() else value
    if kind == "date":
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            raise ValueError(f"{label} must be a date written as YYYY-MM-DD, not '{text}'.") from None
    return text


def plan(unit, raw_changes):
    """Work out exactly what will change, including fields recomputed from the change.

    Returns (changes, errors). Each change is {field, label, old, new, derived, how}. Nothing is saved.
    Recomputing rules: a new monthly rent sets annual rent to monthly x 12; a new annual rent sets
    monthly rent to annual / 12; any change to rent or SF recomputes rent/SF as annual rent / SF.
    """
    parsed, errors = {}, []
    for field, raw in raw_changes.items():
        try:
            value = parse(field, raw)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if value != unit.get(field):
            parsed[field] = value
    changes = [{"field": f, "label": LABELS[f], "old": unit.get(f), "new": v, "derived": False, "how": ""}
               for f, v in parsed.items()]
    after = {**unit, **parsed}

    def derive(field, value, how):
        value = round(value, 2)
        if value != unit.get(field):
            after[field] = value
            changes.append({"field": field, "label": LABELS[field], "old": unit.get(field), "new": value,
                            "derived": True, "how": how})

    if "monthly_rent" in parsed and "annual_rent" not in parsed and _number(parsed["monthly_rent"]):
        derive("annual_rent", parsed["monthly_rent"] * 12, "Recomputed: annual rent = monthly rent x 12")
    elif "annual_rent" in parsed and "monthly_rent" not in parsed and _number(parsed["annual_rent"]):
        derive("monthly_rent", parsed["annual_rent"] / 12, "Recomputed: monthly rent = annual rent / 12")
    if ({"square_feet", "annual_rent", "monthly_rent"} & set(parsed) and _number(after.get("annual_rent"))
            and _number(after.get("square_feet")) and after["square_feet"] > 0):
        derive("rent_per_sf", after["annual_rent"] / after["square_feet"], "Recomputed: rent/SF = annual rent / SF")
    return changes, errors


def _rows(conn, sql, params):
    return [dict(row) for row in conn.execute(sql, params)]


def is_approved(conn, deal_id):
    return conn.execute("SELECT status FROM deals WHERE id = ?", (deal_id,)).fetchone()["status"] == "Approved"


def _open_flags(conn, unit_id):
    return {(f["rule"], f["field"]): f["message"]
            for f in _rows(conn, "SELECT rule, field, message FROM flags WHERE rent_roll_unit_id = ? AND status = 'open'", (unit_id,))}


def _event(conn, deal_id, kind, user, reason=None, detail=None, source=None, batch_id=None):
    conn.execute("INSERT INTO deal_events (deal_id, kind, user, reason, detail, source, batch_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (deal_id, kind, user, reason, detail, source, batch_id))


def _show(value):
    if _number(value):
        return f"{value:,.2f}".rstrip("0").rstrip(".") if not float(value).is_integer() else f"{value:,.0f}"
    return "(empty)" if value in (None, "") else str(value)


def describe(changes, unit_number):
    return "; ".join(f"Unit {unit_number} {c['label']}: {_show(c['old'])} -> {_show(c['new'])}" for c in changes)


def apply(deal_id, unit_id, changes, reason, user, source=MANUAL, db_path=None):
    """Save a person's changes to one unit, log every one, and re-check the deal.

    Returns {"batch_id", "cleared": [...], "still": [...], "new": [...]} describing the unit's flags afterwards.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Say why you are making this change.")
    if not changes:
        raise ValueError("Nothing would change.")
    db.init_db(db_path)
    conn = db.get_connection(db_path)
    try:
        if is_approved(conn, deal_id):
            raise Locked("This deal is approved. Reopen it before changing anything.")
        unit = conn.execute("SELECT * FROM rent_roll_units WHERE id = ? AND deal_id = ?", (unit_id, deal_id)).fetchone()
        if unit is None:
            raise ValueError("That unit is not part of this deal.")
        before, batch_id = _open_flags(conn, unit_id), uuid.uuid4().hex
        with conn:
            for change in changes:
                conn.execute(f"UPDATE rent_roll_units SET {change['field']} = ? WHERE id = ?", (change["new"], unit_id))
                conn.execute(
                    "INSERT INTO edits (deal_id, unit_id, unit_number, field, old_value, new_value, reason, source, user, batch_id, derived) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (deal_id, unit_id, unit["unit_number"], change["field"], json.dumps(change["old"]), json.dumps(change["new"]),
                     change["how"] or reason, source, user, batch_id, int(change["derived"])))
            _event(conn, deal_id, "edit", user, reason, describe(changes, unit["unit_number"]), source, batch_id)
    finally:
        conn.close()
    validation.validate_deal(deal_id, db_path, user)
    conn = db.get_connection(db_path)
    try:
        after = _open_flags(conn, unit_id)
    finally:
        conn.close()
    return {"batch_id": batch_id, "cleared": [m for k, m in before.items() if k not in after],
            "still": [m for k, m in after.items() if k in before], "new": [m for k, m in after.items() if k not in before]}


def undo(batch_id, user, db_path=None):
    """Put back the values a save changed, log the undo, and re-check the deal."""
    conn = db.get_connection(db_path)
    try:
        rows = _rows(conn, "SELECT * FROM edits WHERE batch_id = ? ORDER BY id", (batch_id,))
        if not rows:
            raise ValueError("That change was not found.")
        deal_id = rows[0]["deal_id"]
        if is_approved(conn, deal_id):
            raise Locked("This deal is approved. Reopen it before undoing a change.")
        if rows[0]["reverted_at"]:
            raise ValueError("That change has already been undone.")
        for row in rows:
            later = conn.execute("SELECT COUNT(*) FROM edits WHERE unit_id = ? AND field = ? AND id > ? AND reverted_at IS NULL "
                                 "AND batch_id != ?", (row["unit_id"], row["field"], row["id"], batch_id)).fetchone()[0]
            if later:
                raise ValueError(f"{LABELS.get(row['field'], row['field'])} was changed again later. Undo the later change first.")
        with conn:
            for row in reversed(rows):
                conn.execute(f"UPDATE rent_roll_units SET {row['field']} = ? WHERE id = ?", (json.loads(row["old_value"]), row["unit_id"]))
            conn.execute("UPDATE edits SET reverted_at = CURRENT_TIMESTAMP WHERE batch_id = ?", (batch_id,))
            restored = "; ".join(f"Unit {r['unit_number']} {LABELS.get(r['field'], r['field'])}: back to {_show(json.loads(r['old_value']))}"
                                 for r in rows)
            _event(conn, deal_id, "undo", user, "Undo", restored, rows[0]["source"], batch_id)
    finally:
        conn.close()
    validation.validate_deal(deal_id, db_path, user)


def confirm_flag(flag_id, reason, note, user, db_path=None):
    """A person says the flagged value is right. Never changes the data; the flag stays visible."""
    if reason not in CONFIRM_REASONS:
        raise ValueError("Choose a reason.")
    note = (note or "").strip()
    if not note:
        raise ValueError("Add a short note saying how you checked it.")
    db.init_db(db_path)
    conn = db.get_connection(db_path)
    try:
        flag = conn.execute("SELECT * FROM flags WHERE id = ?", (flag_id,)).fetchone()
        if flag is None or flag["status"] != "open":
            raise ValueError("That flag is not open.")
        if is_approved(conn, flag["deal_id"]):
            raise Locked("This deal is approved. Reopen it before confirming a flag.")
        with conn:
            conn.execute("UPDATE flags SET status = 'confirmed', resolved_by = ?, resolved_at = CURRENT_TIMESTAMP, "
                         "resolution_reason = ?, resolution_note = ? WHERE id = ?", (user, reason, note, flag_id))
            _event(conn, flag["deal_id"], "confirmed", user, f"{reason}: {note}",
                   f"Unit {flag['unit_number']}: {flag['message']}", MANUAL)
    finally:
        conn.close()


def originals(deal_id, db_path=None):
    """{(unit_id, field): edit info} for every value that differs from what was extracted.

    The original is the old value of the first edit of that field; who and why come from the latest edit.
    """
    conn = db.get_connection(db_path)
    try:
        rows = _rows(conn, "SELECT * FROM edits WHERE deal_id = ? ORDER BY id", (deal_id,))
        units = {u["id"]: u for u in _rows(conn, "SELECT * FROM rent_roll_units WHERE deal_id = ?", (deal_id,))}
    finally:
        conn.close()
    found = {}
    for row in rows:
        key = (row["unit_id"], row["field"])
        info = found.setdefault(key, {"original": json.loads(row["old_value"])})
        if not row["reverted_at"]:
            info.update(user=row["user"], when=row["created_at"], reason=row["reason"], source=row["source"])
    return {key: info for key, info in found.items()
            if key[0] in units and units[key[0]].get(key[1]) != info["original"] and "user" in info}
