"""Build the downloadable files for a deal from what is saved in SQLite."""

import io
import re

import pandas as pd

RENT_ROLL_COLUMNS = {
    "unit_number": "Unit", "tenant_name": "Tenant", "square_feet": "SF",
    "lease_start": "Lease start", "lease_end": "Lease end", "monthly_rent": "Monthly rent",
    "annual_rent": "Annual rent", "rent_per_sf": "Rent / SF", "lease_type": "Lease type",
}


def slug(deal_name):
    """A short file-name-safe version of the deal name, without the sample marker."""
    name = re.sub(r"\(.*?\)", "", deal_name).strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", name).strip("_") or "deal"


def rent_roll_table(units, flags):
    """One row per unit as saved, plus the flag messages so a flag is never lost in an export."""
    reasons = {}
    for flag in flags:
        reasons.setdefault(flag["rent_roll_unit_id"], []).append(flag["message"])
    table = pd.DataFrame([{label: unit[field] for field, label in RENT_ROLL_COLUMNS.items()} for unit in units])
    table["Flag"] = ["Flagged" if unit["id"] in reasons else "" for unit in units]
    table["Flag reason"] = [" ".join(reasons.get(unit["id"], [])) for unit in units]
    return table


def t12_table(items):
    """The T-12 laid out like the statement: one row per line item, one column per period."""
    table = pd.DataFrame(items)
    wide = table.pivot(index="line_item", columns="period", values="amount")
    lines = list(dict.fromkeys(table["line_item"]))
    periods = list(dict.fromkeys(table["period"]))
    categories = table.drop_duplicates("line_item").set_index("line_item")["category"]
    wide = wide.loc[lines, periods].reset_index().rename(columns={"line_item": "Line item"})
    wide.insert(1, "Category", [categories[line] for line in lines])
    wide.columns.name = None
    return wide


def to_csv(table):
    return table.to_csv(index=False).encode("utf-8")


def to_excel(table, sheet_name):
    buffer = io.BytesIO()
    table.to_excel(buffer, index=False, sheet_name=sheet_name)
    return buffer.getvalue()
