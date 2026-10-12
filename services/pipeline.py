"""Run the services for one deal in order. Each service stays in its own module."""

from collections import Counter

from services import extraction, validation


def process_deal(xlsx_path, deal_id, client=None, db_path=None, **extraction_options):
    """Extract a rent roll, then validate it. Returns a short summary.

    If extraction rejects the file it raises ExtractionError, nothing is saved,
    and validation does not run.
    """
    units_saved = extraction.extract_rent_roll(
        xlsx_path, deal_id, client=client, db_path=db_path, **extraction_options
    )
    flags = validation.validate_deal(deal_id, db_path)
    return {
        "units_saved": units_saved,
        "flags_raised": len(flags),
        "rules": dict(Counter(flag.rule for flag in flags)),
    }
