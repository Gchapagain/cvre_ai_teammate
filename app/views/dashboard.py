"""Deals dashboard: four stat cards, then one card per deal. Clicking a card opens the deal."""

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


def _deal_card(deal):
    with st.container(border=True, key=f"deal_card_{deal['id']}"):
        # The name is the button. CSS in app/style.py stretches its click area over the whole card.
        st.button(deal["name"], key=f"open_deal_{deal['id']}", type="tertiary",
                  on_click=_open_deal, args=(deal["id"],))
        flags = deal["flag_count"]
        flag_pill = style.pill(f"{flags} anomal{'y' if flags == 1 else 'ies'}", "flag") if flags else ""
        units = f"{deal['unit_count']} units" if deal["unit_count"] else "No numbers yet"
        style.html(
            f'<div class="deal-meta">{escape(deal["property_type"] or "")} · '
            f'{escape(deal["submarket"] or "")} · {units}</div>'
            f'{style.pill(deal["status"])} {flag_pill}'
        )


def render():
    st.header("Deals")
    _stat_cards()
    st.caption("Click a deal to open it.")
    for deal in queries.list_deals():
        _deal_card(deal)
    st.caption("Sample data only. Every name and number here is made up.")
