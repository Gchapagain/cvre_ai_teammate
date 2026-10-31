"""Read everything the OM engine works from for one deal, from any open connection (read-only use).

Shared by the screens (app/queries.py, read-only connection), the chat (services/qa.py) and seed.py.
"""

import json
import sqlite3

from services import branding


def _all(conn, sql, params):
    try:
        return [dict(row) for row in conn.execute(sql, params)]
    except sqlite3.OperationalError:  # a database from before the OM Builder simply has none
        return []


def profile(conn, email=None):
    """The broker's profile for the contacts page: the given broker, or the first broker."""
    columns = "email, full_name, role, title, phone"
    try:
        if email:
            row = conn.execute(f"SELECT {columns} FROM users WHERE email = ?", (email,)).fetchone()
            if row:
                return dict(row)
        row = conn.execute(f"SELECT {columns} FROM users WHERE role = 'Broker' ORDER BY id").fetchone()
    except sqlite3.OperationalError:
        row = conn.execute("SELECT email, full_name, role FROM users WHERE role = 'Broker' ORDER BY id").fetchone()
    return dict(row) if row else None


def load(conn, deal_id, email=None):
    rows = {}
    for row in _all(conn, "SELECT * FROM om_slots WHERE deal_id = ?", (deal_id,)):
        row["value"] = json.loads(row["value"]) if row["value"] else None
        row["source"] = json.loads(row["source"] or "{}")
        rows[row["slot_id"]] = row
    assumptions = {}
    for row in _all(conn, "SELECT * FROM om_assumptions WHERE deal_id = ?", (deal_id,)):
        row["value"] = json.loads(row["value"])
        row["source"] = json.loads(row["source"] or "{}")
        assumptions[row["key"]] = row
    price = rows.get("financial.sale_price", {}).get("value")
    who = profile(conn, email)
    deal = _all(conn, "SELECT * FROM deals WHERE id = ?", (deal_id,))
    return {
        "deal": deal[0] if deal else {},
        "units": _all(conn, "SELECT * FROM rent_roll_units WHERE deal_id = ? ORDER BY id", (deal_id,)),
        "t12": _all(conn, "SELECT category, line_item, period, amount FROM t12_line_items WHERE deal_id = ? ORDER BY id",
                    (deal_id,)),
        "documents": _all(conn, "SELECT * FROM documents WHERE deal_id = ? ORDER BY id", (deal_id,)),
        "rows": rows,
        "assets": _all(conn, "SELECT * FROM om_assets WHERE deal_id = ? ORDER BY slot_id, position, id", (deal_id,)),
        "assumptions": assumptions,
        "price": price if isinstance(price, (int, float)) else None,
        "profile": who,
        "logo": branding.logo_path((who or {}).get("email")),
    }
