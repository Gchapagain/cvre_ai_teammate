"""Deals dashboard: stat cards, then deal cards with the ones needing attention first."""

from html import escape

import streamlit as st

from app import queries, style


def _open_deal(deal_id):
    st.session_state.deal_id = deal_id
    st.session_state.page = "deal"


def _stat_cards():
    stats = queries.dashboard_stats()
    cards = [
        style.stat_card("Active deals", stats["active_deals"], "Not yet approved"),
        style.stat_card("Needs review", stats["needs_review"], "Waiting for a person"),
        style.stat_card("Time saved", "Not measured yet", "Real timings arrive with the accuracy report", is_text=True),
        style.stat_card("Anomalies", stats["anomalies"], "Flagged, never hidden"),
    ]
    style.html(f'<div class="stat-grid">{"".join(cards)}</div>')


def card_kind(deal):
    """Which accent a deal card gets: red for an anomaly, amber for review, none otherwise."""
    if deal["flag_count"]:
        return "flagged"
    return "review" if deal["status"] == "Needs Review" else "plain"


def _deal_card(deal):
    with st.container(border=True, key=f"deal_card_{card_kind(deal)}_{deal['id']}"):
        # The name is the button. CSS in app/style.py stretches its click area over the whole card.
        st.button(deal["name"], key=f"open_deal_{deal['id']}", type="tertiary",
                  on_click=_open_deal, args=(deal["id"],))
        flags = deal["flag_count"]
        flag_pill = style.pill(f"{flags} anomal{'y' if flags == 1 else 'ies'}", "flag") if flags else ""
        units = f"{deal['unit_count']} units" if deal["unit_count"] else "No numbers yet"
        style.html(
            f'<div class="deal-meta">{escape(deal["property_type"] or "")} · '
            f'{escape(deal["submarket"] or "")} · {units}</div>'
            f'{style.pill(deal["status"])}{flag_pill}'
        )


def _deal_group(title, deals):
    if deals:
        style.section_title(f"{title} ({len(deals)})")
        for deal in deals:
            _deal_card(deal)


def render():
    st.header("Deals")
    _stat_cards()
    deals = queries.list_deals()
    _deal_group("Needs your attention", [d for d in deals if queries.needs_attention(d)])
    _deal_group("Other deals", [d for d in deals if not queries.needs_attention(d)])
    st.caption("Click a deal to open it. Sample data only: every name and number here is made up.")
