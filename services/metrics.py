"""Deal figures calculated in plain Python from the saved rent roll. No AI, no estimates.

Every value here comes straight from saved rows. When something cannot be worked out,
the answer is the text "Not available" (or "Needs T-12"), never a guess.
"""

from datetime import date, datetime, timezone

NOT_AVAILABLE = "Not available"
NEEDS_T12 = "Needs T-12"
NOT_MEASURED = "Not measured yet"
DAYS_PER_MONTH = 365.25 / 12

RULE_NAMES = {
    "rent_per_sf_above_2x_average": "rent/SF is more than 2x the average of the other units",
    "missing_value": "a value is missing",
    "non_numeric_value": "a value is not a number",
    "zero_or_negative_value": "a value is zero or negative",
    "invalid_date": "a date cannot be read",
    "lease_end_before_start": "the lease ends before it starts",
    "duplicate_unit_id": "the unit ID appears more than once",
}


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _lease_end(unit):
    try:
        return date.fromisoformat(unit.get("lease_end"))
    except (TypeError, ValueError):
        return None


def _months_left(end, today):
    """Months from today to the lease end. A lease that has already ended has zero left."""
    return max((end - today).days, 0) / DAYS_PER_MONTH


def _with_sf(units):
    return [u for u in units if _is_number(u.get("square_feet")) and u["square_feet"] > 0]


def total_sf(units):
    return sum(u["square_feet"] for u in _with_sf(units))


def average_rent_per_sf(units):
    """Total annual rent / total SF, over the units that have both. None if it cannot be worked out."""
    usable = [u for u in _with_sf(units) if _is_number(u.get("annual_rent"))]
    sf = sum(u["square_feet"] for u in usable)
    return sum(u["annual_rent"] for u in usable) / sf if sf else None


def weighted_lease_term_years(units, today):
    """Remaining lease term in years, weighted by SF. None if no unit has both an end date and SF."""
    dated = [(u, _lease_end(u)) for u in _with_sf(units)]
    dated = [(u, end) for u, end in dated if end]
    sf = sum(u["square_feet"] for u, _ in dated)
    if not sf:
        return None
    return sum(u["square_feet"] * _months_left(end, today) for u, end in dated) / sf / 12


def noi_from_t12(t12):
    """Net operating income exactly as the T-12 states it, or None if there is no T-12."""
    for item in t12:
        if item["line_item"] == "Net Operating Income" and item["period"] == "Total" and _is_number(item["amount"]):
            return item["amount"]
    return None


def snapshot(units, flags, t12, today):
    """Rows for the deal snapshot as (label, value, note). Every value is calculated or says why not."""
    sf, rent, term, noi = total_sf(units), average_rent_per_sf(units), weighted_lease_term_years(units, today), noi_from_t12(t12)
    counted = len(_with_sf(units))
    sf_note = "" if counted == len(units) else f"{counted} of {len(units)} units have a usable SF"
    flagged = len({f["unit_number"] for f in flags})
    return [
        ("Total SF", f"{sf:,.0f}" if sf else NOT_AVAILABLE, sf_note),
        ("Units", str(len(units)), ""),
        ("Average rent / SF", f"${rent:,.2f}" if rent is not None else NOT_AVAILABLE, "Total annual rent / total SF"),
        ("Weighted avg lease term left", f"{term:.1f} years" if term is not None else NOT_AVAILABLE,
         f"Weighted by SF, as of {today.isoformat()}"),
        ("Flagged units", str(flagged), "Open flags. Resolved ones stay listed on the Review tab"),
        ("Net operating income", f"${noi:,.2f}" if noi is not None else NEEDS_T12,
         "As stated in the T-12" if noi is not None else ""),
        ("Time in review", NOT_MEASURED, ""),
    ]


def _largest_tenant(units):
    usable = _with_sf(units)
    if not usable:
        return []
    top, sf = max(usable, key=lambda u: u["square_feet"]), total_sf(units)
    return [f"{top.get('tenant_name') or 'Unit ' + str(top['unit_number'])} is the largest tenant: "
            f"{top['square_feet']:,.0f} SF, {top['square_feet'] / sf:.1%} of the {sf:,.0f} SF total."]


def _expiring(units, today, months):
    dated = [(u, _lease_end(u)) for u in _with_sf(units)]
    ending = [u for u, end in dated if end and end >= today and (end - today).days <= months * DAYS_PER_MONTH]
    if not any(end for _, end in dated):
        return []
    if not ending:
        return [f"No leases end in the next {months} months."]
    sf, names = sum(u["square_feet"] for u in ending), ", ".join(str(u["unit_number"]) for u in ending)
    count = len(ending)
    return [f"{count} lease{'' if count == 1 else 's'} ({sf:,.0f} SF, {sf / total_sf(units):.1%} of total SF) "
            f"end{'s' if count == 1 else ''} in the next {months} months: unit{'' if count == 1 else 's'} {names}."]


def _term_range(units, today):
    dated = [(u, _lease_end(u)) for u in units]
    dated = [(u, end) for u, end in dated if end]
    if not dated:
        return []
    already = [u for u, end in dated if end < today]
    running = [(u, end) for u, end in dated if end >= today]
    lines = []
    if already:
        lines.append(f"{len(already)} lease{'' if len(already) == 1 else 's'} already ended before {today.isoformat()}: "
                     f"unit{'' if len(already) == 1 else 's'} {', '.join(str(u['unit_number']) for u in already)}.")
    if running:
        (short, short_end), (long, long_end) = min(running, key=lambda p: p[1]), max(running, key=lambda p: p[1])
        lines.append(f"Shortest remaining term: unit {short['unit_number']}, ends {short_end.isoformat()} "
                     f"({_months_left(short_end, today):.0f} months).")
        if long is not short:
            lines.append(f"Longest remaining term: unit {long['unit_number']}, ends {long_end.isoformat()} "
                         f"({_months_left(long_end, today) / 12:.1f} years).")
    return lines


def rule_name(rule):
    return RULE_NAMES.get(rule, rule)


def _flag_lines(flags):
    return [f"Unit {f['unit_number'] or '(no ID)'} is flagged: {rule_name(f['rule'])}. Confirm it before using its figures."
            for f in flags]


def takeaways(units, flags, today):
    """Plain sentences, each one calculated from the saved rows. Anything that would be a guess is left out."""
    return (_largest_tenant(units) + _expiring(units, today, 12) + _expiring(units, today, 24)
            + _term_range(units, today) + _flag_lines(flags))


def time_ago(timestamp, now=None):
    """'3 hours ago' for a UTC timestamp saved by SQLite. Returns '' if it cannot be read."""
    try:
        then = datetime.fromisoformat(timestamp).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return ""
    seconds = max(((now or datetime.now(timezone.utc)) - then).total_seconds(), 0)
    for size, name in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            count = int(seconds // size)
            return f"{count} {name}{'' if count == 1 else 's'} ago"
    return "just now"
