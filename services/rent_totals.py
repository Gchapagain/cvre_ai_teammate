"""Read the totals a rent roll states about itself (its "Total" row), so validation can check the unit
rents add up to them. Plain code, no AI. A file without a total row simply has no stated totals.
"""

from pathlib import Path

import pandas as pd

HEADER_WORDS = {"total_sf": ("sf", "square feet", "sq ft", "rsf"),
                "total_monthly_rent": ("monthly",),
                "total_annual_rent": ("annual",)}


def _number(value):
    try:
        number = float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # NaN is not a number


def _columns(header):
    """Which column holds each total, matched by words in the header row."""
    found = {}
    for index, cell in enumerate(header):
        text = str(cell or "").strip().lower()
        for key, words in HEADER_WORDS.items():
            if key not in found and any(word == text or word in text.split(" ") or text.startswith(word) for word in words):
                if key == "total_sf" and ("/" in text or "rent" in text):
                    continue  # "Rent / SF" is a rate, not the size
                found[key] = index
    return found


def read_stated_totals(path):
    """{total_sf, total_monthly_rent, total_annual_rent} from the first sheet's Total row, or None."""
    path = Path(path)
    try:
        frame = pd.read_csv(path, header=None) if path.suffix.lower() == ".csv" else pd.read_excel(path, header=None)
    except Exception:
        return None
    rows = frame.where(frame.notna(), None).values.tolist()
    header_index = next((i for i, row in enumerate(rows)
                         if any(str(c or "").strip().lower() in ("sf", "square feet", "unit") for c in row)), None)
    if header_index is None:
        return None
    columns = _columns(rows[header_index])
    for row in rows[header_index + 1:]:
        if str(row[0] or "").strip().lower().startswith("total"):
            totals = {key: _number(row[index]) for key, index in columns.items()}
            return totals if any(v is not None for v in totals.values()) else None
    return None


def save(conn, deal_id, document_id, totals):
    """Record stated totals for a deal's rent roll. Nothing is saved when there are none."""
    if not totals:
        return
    conn.execute("INSERT INTO rent_roll_totals (deal_id, document_id, total_sf, total_monthly_rent, total_annual_rent) "
                 "VALUES (?, ?, ?, ?, ?)",
                 (deal_id, document_id, totals.get("total_sf"), totals.get("total_monthly_rent"), totals.get("total_annual_rent")))
