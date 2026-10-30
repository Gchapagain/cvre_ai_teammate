"""The "OM xx%" badge shown on deal cards, the Home project strip and the deal header. Read-only."""

from html import escape

from app import queries
from services import om_engine


def state(deal_id):
    return om_engine.build(queries.om_facts(deal_id))


def badge_html(om_state):
    """A small pill with the OM completion, coloured like Home progress (green only at 100%)."""
    approved, waiting, *_ = om_state.completion()
    title = f"Offering memorandum: {approved}% approved, {waiting}% filled and waiting for approval"
    return (f'<span class="om-badge {om_state.colour}" title="{escape(title)}">'
            f'<span class="om-badge-label">OM</span>{approved}%</span>')
