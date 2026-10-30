"""Run the services for one deal in order. Each service stays in its own module."""

from collections import Counter

import db
from services import extraction, rent_totals, validation


def _save_stated_totals(path, deal_id, document_id, db_path):
    """Keep the rent roll's own Total row (read by code, not AI) so validation can check the sum."""
    totals = rent_totals.read_stated_totals(path)
    if not totals:
        return
    conn = db.get_connection(db_path)
    try:
        with conn:
            rent_totals.save(conn, deal_id, document_id, totals)
    finally:
        conn.close()


def process_deal(xlsx_path, deal_id, client=None, db_path=None, **extraction_options):
    """Extract a rent roll, then validate it. Returns a short summary.

    If extraction rejects the file it raises ExtractionError, nothing is saved,
    and validation does not run.
    """
    units_saved = extraction.extract_rent_roll(
        xlsx_path, deal_id, client=client, db_path=db_path, **extraction_options
    )
    _save_stated_totals(xlsx_path, deal_id, extraction_options.get("document_id"), db_path)
    flags = validation.validate_deal(deal_id, db_path)
    return {
        "units_saved": units_saved,
        "flags_raised": len(flags),
        "rules": dict(Counter(flag.rule for flag in flags)),
    }
