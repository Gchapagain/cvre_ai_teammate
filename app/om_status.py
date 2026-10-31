"""The "OM xx%" badge shown on deal cards, the Home project strip and the deal header. Read-only."""

from html import escape

from app import queries
from services import om_assets, om_engine


def state(deal_id, email=None):
    facts = queries.om_facts(deal_id, email)
    om_assets.ensure_sample_files(facts["assets"])  # sample drawings are not in git: draw any that are missing
    return om_engine.build(facts)


def badge_html(om_state):
    """A small pill with the OM completion, coloured like Home progress (green only at 100%)."""
    approved, waiting, *_ = om_state.completion()
    title = f"Offering memorandum: {approved}% approved, {waiting}% filled and waiting for approval"
    return (f'<span class="om-badge {om_state.colour}" title="{escape(title)}">'
            f'<span class="om-badge-label">OM</span>{approved}%</span>')
