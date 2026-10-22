"""Validation service: plain Python rules that check a deal's rent roll numbers.

No AI is involved. Every problem becomes a flag that is saved for the app to
show. Validation never deletes, changes or hides the data, and never raises
because the data is bad.
"""

import math
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

import db

RENT_MULTIPLE = 2.0

RULE_RENT_OUTLIER = "rent_per_sf_above_2x_average"
RULE_MISSING = "missing_value"
RULE_NON_NUMERIC = "non_numeric_value"
RULE_ZERO_OR_NEGATIVE = "zero_or_negative_value"
RULE_INVALID_DATE = "invalid_date"
RULE_LEASE_DATES = "lease_end_before_start"
RULE_DUPLICATE = "duplicate_unit_id"
RENT_ROLL_RULES = (
    RULE_RENT_OUTLIER, RULE_MISSING, RULE_NON_NUMERIC, RULE_ZERO_OR_NEGATIVE,
    RULE_INVALID_DATE, RULE_LEASE_DATES, RULE_DUPLICATE,
)

NUMERIC_FIELDS = {
    "square_feet": "square footage",
    "monthly_rent": "monthly rent",
    "annual_rent": "annual rent",
    "rent_per_sf": "rent/SF",
}
DATE_FIELDS = {"lease_start": "lease start date", "lease_end": "lease end date"}


@dataclass(frozen=True)
class Flag:
    unit_number: str | None
    rule: str
    field: str | None
    actual_value: str | None
    threshold: str | None
    message: str
    rent_roll_unit_id: int | None = None


def _is_missing(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _is_number(value):
    # bool is a kind of int in Python, and NaN/infinity are floats, so rule both out.
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _parse_date(value):
    """Return a date for a date object or a YYYY-MM-DD string, otherwise None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _show(value):
    """The value as text for the flag record, exactly as found."""
    return None if value is None else str(value)


def _unit_id(unit):
    return None if _is_missing(unit.get("unit_number")) else str(unit["unit_number"]).strip()


def _name(unit):
    unit_id = _unit_id(unit)
    return f"Unit {unit_id}" if unit_id else "A unit with no ID"


def _flag(unit, rule, field, actual, threshold, message):
    return Flag(_unit_id(unit), rule, field, _show(actual), threshold, message, unit.get("id"))


def check_unit_id(unit):
    if _unit_id(unit) is None:
        return [_flag(unit, RULE_MISSING, "unit_number", unit.get("unit_number"), "required",
                      "A unit has no unit ID.")]
    return []


def check_numbers(unit):
    """Flag numeric fields that are missing, not a number, or zero or negative."""
    flags = []
    for field, label in NUMERIC_FIELDS.items():
        value = unit.get(field)
        if _is_missing(value):
            flags.append(_flag(unit, RULE_MISSING, field, value, "required",
                               f"{_name(unit)} has no {label}."))
        elif not _is_number(value):
            flags.append(_flag(unit, RULE_NON_NUMERIC, field, value, "a number",
                               f"{_name(unit)} {label} is '{value}', which is not a number."))
        elif value <= 0:
            flags.append(_flag(unit, RULE_ZERO_OR_NEGATIVE, field, value, "greater than 0",
                               f"{_name(unit)} {label} is {value:,.2f}. It should be greater than zero."))
    return flags


def check_dates(unit):
    """Flag lease dates that are missing, unreadable, or end before they start."""
    flags = []
    for field, label in DATE_FIELDS.items():
        value = unit.get(field)
        if _is_missing(value):
            flags.append(_flag(unit, RULE_MISSING, field, value, "required",
                               f"{_name(unit)} has no {label}."))
        elif _parse_date(value) is None:
            flags.append(_flag(unit, RULE_INVALID_DATE, field, value, "a date (YYYY-MM-DD)",
                               f"{_name(unit)} {label} is '{value}', which is not a valid date."))
    start, end = _parse_date(unit.get("lease_start")), _parse_date(unit.get("lease_end"))
    if start and end and end < start:
        flags.append(_flag(unit, RULE_LEASE_DATES, "lease_end", end, f"on or after {start}",
                           f"{_name(unit)} lease ends on {end}, before it starts on {start}."))
    return flags


def check_duplicates(units):
    """Flag every row whose unit ID appears more than once."""
    counts = Counter(_unit_id(u) for u in units if _unit_id(u))
    return [
        _flag(unit, RULE_DUPLICATE, "unit_number", _unit_id(unit), "appears once",
              f"{_name(unit)} appears {counts[_unit_id(unit)]} times in the rent roll.")
        for unit in units if counts[_unit_id(unit)] > 1
    ]


def _usable_for_average(unit):
    return (_is_number(unit.get("square_feet")) and unit["square_feet"] > 0
            and _is_number(unit.get("annual_rent")) and unit["annual_rent"] > 0)


def check_rent_outliers(units):
    """Flag units whose rent/SF is more than 2x the average of the OTHER units.

    The unit being tested is left out of its own average. If it were included,
    an outlier would pull the average up and partly hide itself; in a building
    with two same-size units nothing could ever be above 2x. With one unit there
    is nothing to compare against, so nothing is flagged.

    The average is total annual rent / total SF of the other units, not a simple
    mean of their rent/SF. Units with unusable SF or rent are left out of it.
    Exactly 2.0x is not flagged, only above.
    """
    flags = []
    for index, unit in enumerate(units):
        rent_per_sf = unit.get("rent_per_sf")
        others = [u for i, u in enumerate(units) if i != index and _usable_for_average(u)]
        if not _is_number(rent_per_sf) or not others:
            continue
        average = sum(u["annual_rent"] for u in others) / sum(u["square_feet"] for u in others)
        limit = RENT_MULTIPLE * average
        if rent_per_sf > limit:
            flags.append(_flag(
                unit, RULE_RENT_OUTLIER, "rent_per_sf", rent_per_sf, f"{limit:.2f}",
                f"{_name(unit)} rent/SF is ${rent_per_sf:,.2f}, which is {rent_per_sf / average:.2f}x the "
                f"average of the other {len(others)} unit(s) (${average:,.2f}). The limit is 2x (${limit:,.2f}).",
            ))
    return flags


def validate_units(units):
    """Run every rule on a list of unit dicts and return the flags. The units are not changed."""
    flags = []
    for unit in units:
        flags += check_unit_id(unit) + check_numbers(unit) + check_dates(unit)
    return flags + check_duplicates(units) + check_rent_outliers(units)


def load_units(conn, deal_id):
    rows = conn.execute("SELECT * FROM rent_roll_units WHERE deal_id = ? ORDER BY id", (deal_id,))
    return [dict(row) for row in rows]


def flag_key(flag):
    """What makes two flags 'the same problem': the unit row (or its ID), the rule and the field."""
    get = flag.get if isinstance(flag, dict) else lambda name: getattr(flag, name)
    return (get("rent_roll_unit_id") or get("unit_number"), get("rule"), get("field"))


def save_flags(conn, deal_id, flags, user=None):
    """Merge newly found flags with the saved ones, keeping what people decided. Nothing is deleted.

    - A problem that still fires keeps its row. If it was confirmed and the value is unchanged it stays
      confirmed; if the value changed it is reopened for a fresh look.
    - A problem that no longer fires is marked corrected (kept in history, shown as resolved).
    - A problem with no open or confirmed row is added as a new open flag.
    """
    placeholders = ", ".join("?" for _ in RENT_ROLL_RULES)
    saved = [dict(row) for row in conn.execute(
        f"SELECT * FROM flags WHERE deal_id = ? AND rule IN ({placeholders}) ORDER BY id", (deal_id, *RENT_ROLL_RULES))]
    active = {}
    for row in saved:
        if row["status"] != "corrected":
            active.setdefault(flag_key(row), row)
    for flag in flags:
        row = active.pop(flag_key(flag), None)
        if row is None:
            conn.execute(
                """INSERT INTO flags (deal_id, rent_roll_unit_id, unit_number, rule, field, actual_value, threshold, message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (deal_id, flag.rent_roll_unit_id, flag.unit_number, flag.rule, flag.field, flag.actual_value,
                 flag.threshold, flag.message))
            continue
        reopen = row["status"] == "confirmed" and row["actual_value"] != flag.actual_value
        conn.execute(
            """UPDATE flags SET actual_value = ?, threshold = ?, message = ?, unit_number = ?,
                   status = CASE WHEN ? THEN 'open' ELSE status END,
                   resolved_by = CASE WHEN ? THEN NULL ELSE resolved_by END,
                   resolved_at = CASE WHEN ? THEN NULL ELSE resolved_at END,
                   resolution_reason = CASE WHEN ? THEN NULL ELSE resolution_reason END,
                   resolution_note = CASE WHEN ? THEN NULL ELSE resolution_note END
               WHERE id = ?""",
            (flag.actual_value, flag.threshold, flag.message, flag.unit_number, reopen, reopen, reopen, reopen, reopen, row["id"]))
    for row in active.values():  # no longer fires
        conn.execute(
            """UPDATE flags SET status = 'corrected', resolved_by = ?, resolved_at = CURRENT_TIMESTAMP,
                   resolution_reason = 'The value was changed and the rule no longer fires.' WHERE id = ?""",
            (user or "System", row["id"]))


def validate_deal(deal_id, db_path=None, user=None):
    """Check a deal's saved rent roll, merge the flags with what people decided, and return the problems found now."""
    db.init_db(db_path)
    conn = db.get_connection(db_path)
    try:
        flags = validate_units(load_units(conn, deal_id))
        with conn:
            save_flags(conn, deal_id, flags, user)
    finally:
        conn.close()
    return flags
