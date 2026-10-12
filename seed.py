"""Fill the local database with sample deals. No AI is used: the Excel files are read directly.

Run:  .venv/bin/python seed.py --reset

This deletes the local database and rebuilds it, so it only runs with --reset.
Every name and number is made up.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

import db
from services import validation

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_data"
RENT_ROLL_FILE = SAMPLE_DIR / "rent_roll.xlsx"
T12_FILE = SAMPLE_DIR / "t12.xlsx"
DOCUMENT_SOURCE = "Sample data"

UNIT_FIELDS = [
    "unit_number", "tenant_name", "square_feet", "lease_start", "lease_end",
    "monthly_rent", "annual_rent", "rent_per_sf", "lease_type",
]
T12_TOTAL_LINES = {"Total Income", "Total Expenses", "Net Operating Income"}
T12_SECTIONS = {"INCOME": "Income", "EXPENSES": "Expense"}

DEMO_USERS = [
    ("demo.agent@example.com", "Demo Agent", "Agent"),
    ("demo.analyst@example.com", "Demo Analyst", "Analyst"),
    ("demo.admin@example.com", "Demo Administrator", "Administrator"),
]

# A second, clean rent roll for the Approved deal: unit, tenant, SF, annual rent per SF, start, end.
BRINDLEWICK_UNITS = [
    ("A", "Pemberly Sock Emporium", 1800, 26.00, "2023-04-01", "2028-03-31"),
    ("B", "Thistle & Fig Bakery", 1200, 28.50, "2024-02-01", "2029-01-31"),
    ("C", "Gantry Lane Books", 2400, 24.00, "2022-09-01", "2027-08-31"),
    ("D", "Odd Otter Toys", 1500, 27.00, "2025-01-01", "2030-12-31"),
    ("E", "Marrowby Tea Room", 3000, 25.50, "2021-06-01", "2031-05-31"),
]


def read_rent_roll(path):
    """Read unit rows from the sample rent roll, exactly as the file has them."""
    rows = list(load_workbook(path, data_only=True).worksheets[0].iter_rows(values_only=True))
    header = next(i for i, row in enumerate(rows) if row[0] == "Unit")
    units = []
    for row in rows[header + 1:]:
        if row[0] is None or row[0] == "Total":
            continue
        unit = dict(zip(UNIT_FIELDS, row))
        unit["lease_start"] = unit["lease_start"].date().isoformat()
        unit["lease_end"] = unit["lease_end"].date().isoformat()
        units.append(unit)
    return units


def read_t12(path):
    """Read the sample T-12 as (category, line item, period, amount) rows, one per cell."""
    rows = list(load_workbook(path, data_only=True).worksheets[0].iter_rows(values_only=True))
    header = next(i for i, row in enumerate(rows) if row[0] == "Line Item")
    periods = rows[header][1:]
    items, section = [], None
    for row in rows[header + 1:]:
        label = row[0]
        if label in T12_SECTIONS:
            section = T12_SECTIONS[label]
        elif label is not None:
            category = "Total" if label in T12_TOTAL_LINES else section
            items += [(category, label, period, amount) for period, amount in zip(periods, row[1:])]
    return items


def brindlewick_units():
    units = []
    for unit, tenant, sf, rate, start, end in BRINDLEWICK_UNITS:
        monthly = round(sf * rate / 12, 2)
        annual = round(monthly * 12, 2)
        units.append(dict(zip(UNIT_FIELDS, [unit, tenant, sf, start, end, monthly, annual, round(annual / sf, 2), "NNN"])))
    return units


def add_deal(conn, name, property_type, submarket, status):
    return conn.execute(
        "INSERT INTO deals (name, property_type, submarket, status) VALUES (?, ?, ?, ?)",
        (name, property_type, submarket, status),
    ).lastrowid


def add_document(conn, deal_id, filename, doc_type, status, used_for, file_path=None):
    return conn.execute(
        """INSERT INTO documents (deal_id, filename, doc_type, file_path, source, status, used_for)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (deal_id, filename, doc_type, file_path and str(file_path), DOCUMENT_SOURCE, status, used_for),
    ).lastrowid


def add_units(conn, deal_id, document_id, units):
    conn.executemany(
        f"INSERT INTO rent_roll_units (deal_id, document_id, {', '.join(UNIT_FIELDS)}) "
        f"VALUES (?, ?, {', '.join('?' for _ in UNIT_FIELDS)})",
        [(deal_id, document_id, *(unit[field] for field in UNIT_FIELDS)) for unit in units],
    )


def add_t12(conn, deal_id, document_id, items):
    conn.executemany(
        "INSERT INTO t12_line_items (deal_id, document_id, category, line_item, period, amount) VALUES (?, ?, ?, ?, ?, ?)",
        [(deal_id, document_id, *item) for item in items],
    )


def seed(db_path=None):
    """Delete the database at db_path and rebuild it from sample data. Returns the deal IDs."""
    path = Path(db_path or db.DB_PATH)
    path.unlink(missing_ok=True)
    db.init_db(path)
    conn = db.get_connection(path)
    try:
        with conn:
            conn.executemany("INSERT INTO users (email, full_name, role) VALUES (?, ?, ?)", DEMO_USERS)

            fallowmere = add_deal(conn, "Fallowmere Industrial Park (SAMPLE - fictional)",
                                  "Industrial", "Northmarsh (fictional)", "Needs Review")
            doc = add_document(conn, fallowmere, RENT_ROLL_FILE.name, "Rent roll", "Read", "Rent roll", RENT_ROLL_FILE)
            add_units(conn, fallowmere, doc, read_rent_roll(RENT_ROLL_FILE))
            doc = add_document(conn, fallowmere, T12_FILE.name, "T-12", "Read", "T-12", T12_FILE)
            add_t12(conn, fallowmere, doc, read_t12(T12_FILE))

            quillhaven = add_deal(conn, "Quillhaven Flex Center (SAMPLE - fictional)",
                                  "Flex", "Eastwick Bend (fictional)", "Extracting")
            add_document(conn, quillhaven, "quillhaven_rent_roll.xlsx", "Rent roll",
                         "Received", None)

            brindlewick = add_deal(conn, "Brindlewick Retail Row (SAMPLE - fictional)",
                                   "Retail", "Old Harrow Lane (fictional)", "Approved")
            doc = add_document(conn, brindlewick, "brindlewick_rent_roll.xlsx", "Rent roll", "Read", "Rent roll")
            add_units(conn, brindlewick, doc, brindlewick_units())
    finally:
        conn.close()

    deal_ids = {"fallowmere": fallowmere, "quillhaven": quillhaven, "brindlewick": brindlewick}
    for deal_id in deal_ids.values():
        validation.validate_deal(deal_id, path)
    return deal_ids


def main(argv=None, db_path=None):
    parser = argparse.ArgumentParser(description="Rebuild the local database from sample data.")
    parser.add_argument("--reset", action="store_true", help="delete the local database and rebuild it")
    args = parser.parse_args(argv)
    path = Path(db_path or db.DB_PATH)
    if not args.reset:
        print(
            "Nothing was changed.\n"
            f"seed.py deletes the local database ({path.name}) and rebuilds it from sample data.\n"
            "To go ahead, run:  .venv/bin/python seed.py --reset"
        )
        return 1
    deal_ids = seed(path)
    print(f"Rebuilt {path.name} at {datetime.now():%Y-%m-%d %H:%M} with {len(deal_ids)} sample deals.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
