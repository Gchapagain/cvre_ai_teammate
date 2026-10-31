"""Sample OM progress for the demo deals, used by seed.py. Every answer here is made up and says so.

- Brindlewick (the approved sample deal): every OM item filled and approved, so it is 100% and the
  client-ready export works. It gets a made-up T-12 so the cash flow can be calculated.
- Fallowmere: about half approved (property facts, rent roll, some photos); the text, price, assumptions
  and some photos are left for the demo.
- Quillhaven: the name and type only (under 15%): its rent roll has not been read yet.
Photos are drawn sample illustrations (services/om_assets.draw_sample) saved under om_assets/sample/
(git-ignored) and labelled "Sample illustration"; the app draws any missing one again.
"""

from pathlib import Path

import db
from services import om_assets, om_engine, om_facts, om_slots

USER = "Avery Sample"
SAMPLE_SOURCE = {"kind": "broker_input", "detail": "Sample answer, made up for the demo"}
ASSET_DIR = om_assets.ASSET_DIR / "sample"

# Brindlewick's made-up T-12, annual totals only: (category, line item, amount).
BRINDLEWICK_T12 = [
    ("Income", "Base Rental Income", 255600.0), ("Income", "CAM Reimbursements", 39600.0),
    ("Income", "Other Income", 2400.0), ("Total", "Total Income", 297600.0),
    ("Expense", "Property Taxes", 21780.0), ("Expense", "Insurance", 7920.0),
    ("Expense", "Repairs & Maintenance", 9900.0), ("Expense", "Utilities", 4950.0),
    ("Expense", "Management Fee", 8928.0), ("Total", "Total Expenses", 53478.0),
    ("Total", "Net Operating Income", 244122.0),
]

BRINDLEWICK_ANSWERS = {
    "property.address": "18 Old Harrow Lane (fictional)",
    "property.city_state": "Brindlewick, OH",
    "property.buildings": "1",
    "property.land_size": "1.1 acres",
    "property.year_built": "1987 / 2016",
    "offering.narrative": ("SAMPLE text, made up for the demo. A fictional five-unit retail row, fully leased to local "
                           "shops on NNN leases, with staggered lease ends and a single building that is simple to run."),
    "highlights.upside": ["SAMPLE: leases end in different years, so rents can be reset over time",
                          "SAMPLE: NNN leases pass most costs through to tenants"],
    "highlights.location_building": ["SAMPLE: a walkable high street (fictional)", "SAMPLE: one building with a 2016 refresh"],
    "highlights.rare": ["SAMPLE: a fully leased small retail row rarely comes to market (made up for the demo)"],
    "location.narrative": ("SAMPLE text, made up for the demo. Old Harrow Lane is a fictional high street with cafes, "
                           "a library and steady foot traffic. No real place or research is described here."),
    "financial.sale_price": "3,950,000",
}
BRINDLEWICK_ASSUMPTIONS = {"market_rent_psf": "26.50", "escalation_pct": "3", "occupancy_by_year": "100, 100, 95, 95, 95",
                           "expense_growth_pct": "3", "vacancy_pct": "5", "management_fee_pct": "3"}

FALLOWMERE_ANSWERS = {
    "property.address": "4100 Fictional Logistics Way",
    "property.city_state": "Fort Worth, TX",
    "property.buildings": "3",
    "property.land_size": "11.2 acres",
    "property.year_built": "2004 / 2019",
}
# Fallowmere items approved in the demo (about half of the 29 required).
FALLOWMERE_APPROVED = {"property.name", "property.address", "property.city_state", "property.type", "property.buildings",
                       "property.total_sf", "property.avg_unit_size", "property.land_size", "property.year_built",
                       "property.leased_pct", "tenant.rent_roll", "contacts.list", "photo.hero", "photo.offering",
                       "photo.highlights_aerial", "photo.features"}
QUILLHAVEN_APPROVED = {"property.name", "property.type"}


def _photo_plan(slot_ids, template):
    """[(slot_id, kind)] for every photo the given slots need, using each slot's first kind."""
    plan = []
    for slot_id in slot_ids:
        slot = template.slots[slot_id]
        plan += [(slot_id, slot.photo_kinds[0])] * slot.count
    return plan


def add_sample_photos(conn, deal_id, plan):
    for position, (slot_id, kind) in enumerate(plan, start=1):
        path = ASSET_DIR / f"deal_{deal_id}" / f"{slot_id.replace('.', '_')}_{position}.png"
        om_assets.draw_sample(kind, path, position)
        conn.execute("INSERT INTO om_assets (deal_id, file_path, kind, caption, slot_id, position, sample) "
                     "VALUES (?, ?, ?, ?, ?, ?, 1)",
                     (deal_id, om_assets.stored_path(path), kind, f"Sample illustration ({kind})", slot_id, position))


def _approve(deal_id, path, only=None):
    conn = db.get_connection(path)
    try:
        state = om_engine.build(om_facts.load(conn, deal_id))
    finally:
        conn.close()
    waiting = [s for s in state.waiting() if only is None or s.slot.id in only]
    om_slots.approve(deal_id, waiting, USER, path)
    return state


def seed_om(path, deal_ids):
    from services import om_template
    template = om_template.load()
    brindlewick, fallowmere, quillhaven = deal_ids["brindlewick"], deal_ids["fallowmere"], deal_ids["quillhaven"]
    conn = db.get_connection(path)
    try:
        with conn:
            doc = conn.execute("INSERT INTO documents (deal_id, filename, doc_type, source, status, used_for) "
                               "VALUES (?, 'brindlewick_t12.xlsx', 'T-12', 'Sample data', 'Read', 'T-12')",
                               (brindlewick,)).lastrowid
            conn.executemany("INSERT INTO t12_line_items (deal_id, document_id, category, line_item, period, amount) "
                             "VALUES (?, ?, ?, ?, 'Total', ?)",
                             [(brindlewick, doc, category, item, amount) for category, item, amount in BRINDLEWICK_T12])
            photo_slots = [s.id for s in template.slots.values() if s.type == "photo" and s.required]
            add_sample_photos(conn, brindlewick, _photo_plan(photo_slots, template))
            add_sample_photos(conn, fallowmere, _photo_plan(
                ["photo.hero", "photo.offering", "photo.highlights_aerial", "photo.features"], template))
    finally:
        conn.close()
    for slot_id, value in BRINDLEWICK_ANSWERS.items():
        om_slots.set_value(brindlewick, slot_id, value, USER, source=SAMPLE_SOURCE, db_path=path)
    for key, value in BRINDLEWICK_ASSUMPTIONS.items():
        om_slots.set_assumption(brindlewick, key, value, USER, source=SAMPLE_SOURCE, db_path=path)
    for slot_id, value in FALLOWMERE_ANSWERS.items():
        om_slots.set_value(fallowmere, slot_id, value, USER, source=SAMPLE_SOURCE, db_path=path)
    _approve(brindlewick, path)
    _approve(fallowmere, path, FALLOWMERE_APPROVED)
    _approve(quillhaven, path, QUILLHAVEN_APPROVED)


def percent(path, deal_id):
    conn = db.get_connection(Path(path))
    try:
        return om_engine.build(om_facts.load(conn, deal_id)).percent
    finally:
        conn.close()
