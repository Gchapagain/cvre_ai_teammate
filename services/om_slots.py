"""The OM Builder's writes, each made only when a person clicks: slot values, approvals, assumptions and
the time log. Values are checked against the slot's validation rules before they are saved.
"""

import json
import re
from datetime import datetime

import db
from services import om_calc, om_template

STATUSES = ("empty", "auto-filled", "ai-draft", "broker-provided", "approved")


class InvalidValue(ValueError):
    """A value that does not fit the slot, with a plain explanation."""


def _connect(db_path):
    db.init_db(db_path)  # also adds any table a database from an older version is missing
    return db.get_connection(db_path)


def _number(text):
    cleaned = re.sub(r"[,$\s]", "", str(text))
    multiplier = 1
    if cleaned.lower().endswith("m"):
        cleaned, multiplier = cleaned[:-1], 1_000_000
    elif cleaned.lower().endswith("k"):
        cleaned, multiplier = cleaned[:-1], 1_000
    try:
        return float(cleaned) * multiplier
    except ValueError:
        return None


def validate(slot, raw):
    """The value to store for what a person typed, or InvalidValue with what is wrong."""
    rules = slot.validation or {}
    kind = rules.get("kind", "text")
    text = raw.strip() if isinstance(raw, str) else raw
    if text in (None, "", []):
        raise InvalidValue(f"{slot.label} is empty.")
    if kind == "bullets":
        items = text if isinstance(text, list) else [l.strip(" -•\t") for l in str(text).splitlines() if l.strip(" -•\t")]
        if len(items) < rules.get("min_items", 1):
            raise InvalidValue(f"{slot.label} needs at least {rules.get('min_items', 1)} points, one per line.")
        return items
    if kind in ("currency", "integer"):
        number = _number(text)
        if number is None:
            raise InvalidValue(f"{slot.label} must be a number, for example 12,500,000.")
        if kind == "integer" and number != int(number):
            raise InvalidValue(f"{slot.label} must be a whole number.")
        if number < rules.get("min", 0) or ("max" in rules and number > rules["max"]):
            raise InvalidValue(f"{slot.label} of {number:,.0f} is outside the expected range.")
        return int(number) if kind == "integer" else round(number, 2)
    if kind == "acres":
        number = _number(re.sub(r"(?i)\s*(acres?|ac)\.?$", "", str(text)))
        if number is None or number <= 0 or number > 10000:
            raise InvalidValue("Land size should be a number of acres, for example 9.4.")
        return f"{number:g} acres"
    if kind == "year_built":
        years = [int(y) for y in re.findall(r"\b(1[89]\d\d|20\d\d)\b", str(text))]
        if not years or any(y > datetime.now().year for y in years):
            raise InvalidValue("Give the year built (and renovated, if any), for example 1998 / 2019.")
        return " / ".join(str(y) for y in years[:2])
    if kind == "city_state":
        match = re.fullmatch(r"\s*([A-Za-z .'-]+),\s*([A-Za-z]{2})\s*", str(text))
        if not match:
            raise InvalidValue("Write it as City, ST (for example: Fort Worth, TX).")
        return f"{match.group(1).strip()}, {match.group(2).upper()}"
    if len(str(text)) < rules.get("min_length", 1):
        raise InvalidValue(f"{slot.label} is too short.")
    return str(text)


def _upsert(conn, deal_id, slot_id, value, status, source, user):
    conn.execute(
        """INSERT INTO om_slots (deal_id, slot_id, value, status, source, updated_by, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(deal_id, slot_id) DO UPDATE SET value = excluded.value, status = excluded.status,
               source = excluded.source, updated_by = excluded.updated_by, updated_at = CURRENT_TIMESTAMP""",
        (deal_id, slot_id, json.dumps(value), status, json.dumps(source), user))


def log(conn, deal_id, action, detail=None, user=None):
    conn.execute("INSERT INTO om_events (deal_id, action, detail, user) VALUES (?, ?, ?, ?)", (deal_id, action, detail, user))


def set_value(deal_id, slot_id, raw, user, status="broker-provided", source=None, db_path=None, template=None):
    """Save a value a person (or the AI, as ai-draft) gave for a slot. Returns the stored value."""
    if status not in ("broker-provided", "ai-draft"):
        raise ValueError("A new value is either broker-provided or an AI draft; approving is a separate step.")
    slot = (template or om_template.load()).slots[slot_id]
    if slot.fixed:
        raise ValueError(f"{slot.label} is fixed wording and cannot be changed here.")
    value = validate(slot, raw)
    conn = _connect(db_path)
    try:
        with conn:
            _upsert(conn, deal_id, slot_id, value, status,
                    source or {"kind": "broker_input", "detail": f"Typed by {user}"}, user)
            log(conn, deal_id, "set", slot_id, user)
    finally:
        conn.close()
    return value


def approve(deal_id, states, user, db_path=None):
    """Approve the current value of each given slot state (services/om_engine.SlotState). One person's click.

    The value approved is stored with its source, so a calculated value that later changes stops counting
    as approved. Empty slots are skipped and returned.
    """
    skipped = []
    conn = _connect(db_path)
    try:
        with conn:
            for state in states:
                if state.status == "empty" or state.slot.fixed:
                    skipped.append(state.slot.id)
                    continue
                source = dict(state.source, approved_by=user, approved_at=datetime.now().strftime("%Y-%m-%d %H:%M"))
                _upsert(conn, deal_id, state.slot.id, state.value, "approved", source, user)
                log(conn, deal_id, "approve", state.slot.id, user)
    finally:
        conn.close()
    return skipped


def unapprove(deal_id, slot_id, user, db_path=None):
    """Take an approval back: a typed or AI value goes back to waiting; a calculated one simply loses its row."""
    conn = _connect(db_path)
    try:
        with conn:
            row = conn.execute("SELECT * FROM om_slots WHERE deal_id = ? AND slot_id = ?", (deal_id, slot_id)).fetchone()
            if row is None:
                return
            source = json.loads(row["source"] or "{}")
            if source.get("kind") in ("calculated", "document_field", "broker_photo"):
                conn.execute("DELETE FROM om_slots WHERE id = ?", (row["id"],))
            else:
                waiting = "ai-draft" if source.get("kind") == "ai_text" else "broker-provided"
                conn.execute("UPDATE om_slots SET status = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                             (waiting, user, row["id"]))
            log(conn, deal_id, "unapprove", slot_id, user)
    finally:
        conn.close()


def clear(deal_id, slot_id, user, db_path=None):
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM om_slots WHERE deal_id = ? AND slot_id = ?", (deal_id, slot_id))
            log(conn, deal_id, "clear", slot_id, user)
    finally:
        conn.close()


# ---- Assumptions ----

def validate_assumption(key, raw):
    label, kind, _ = om_calc.ASSUMPTIONS[key]
    if kind == "percent_list":
        values = [_number(part) for part in re.split(r"[,;\s]+", str(raw).replace("%", "")) if part]
        if len(values) != om_calc.YEARS or any(v is None or not 0 <= v <= 100 for v in values):
            raise InvalidValue(f"{label}: give five percentages between 0 and 100, for example 85, 90, 95, 95, 95.")
        return values
    number = _number(str(raw).replace("%", ""))
    if number is None or number < 0 or (kind == "percent" and number > 100):
        raise InvalidValue(f"{label} must be a number{' between 0 and 100' if kind == 'percent' else ''}.")
    return number


def set_assumption(deal_id, key, raw, user, status="approved", source=None, db_path=None):
    """Save an assumption. A person's own entry is approved by their click; the AI may only add 'proposed'."""
    if status not in ("proposed", "approved"):
        raise ValueError("An assumption is proposed or approved.")
    value = validate_assumption(key, raw)
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute(
                """INSERT INTO om_assumptions (deal_id, key, value, source, status, updated_by, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(deal_id, key) DO UPDATE SET value = excluded.value, source = excluded.source,
                       status = excluded.status, updated_by = excluded.updated_by, updated_at = CURRENT_TIMESTAMP""",
                (deal_id, key, json.dumps(value), json.dumps(source or {"kind": "broker_input", "detail": f"Entered by {user}"}),
                 status, user))
            log(conn, deal_id, f"assumption_{status}", key, user)
    finally:
        conn.close()
    return value


def approve_assumption(deal_id, key, user, db_path=None):
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute("UPDATE om_assumptions SET status = 'approved', updated_by = ?, updated_at = CURRENT_TIMESTAMP "
                         "WHERE deal_id = ? AND key = ?", (user, deal_id, key))
            log(conn, deal_id, "assumption_approved", key, user)
    finally:
        conn.close()


def save_profile(email, title, phone, db_path=None):
    """The broker's title and phone for the OM contacts page."""
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute("UPDATE users SET title = ?, phone = ? WHERE email = ?",
                         ((title or "").strip() or None, (phone or "").strip() or None, email))
    finally:
        conn.close()
