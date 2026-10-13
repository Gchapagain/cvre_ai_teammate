"""Deals dashboard: stat cards that filter the list, then deal cards with the ones needing attention first."""

from html import escape

import streamlit as st

from app import nav, queries, style

# Stat cards that filter the deal list: key -> (name shown above the list, which deals match).
FILTERS = {
    "active": ("Active deals", lambda deal: deal["status"] != "Approved"),
    "review": ("Needs Review", lambda deal: deal["status"] == "Needs Review"),
    "anomalies": ("Anomalies", lambda deal: deal["flag_count"] > 0),
}
TIME_SAVED = "time"


def _select(name):
    """Clicking a card selects it; clicking the selected card again clears it."""
    st.session_state.deal_filter = None if st.session_state.get("deal_filter") == name else name


def filter_deals(deals, name):
    """The deals a stat card shows. Anything that is not a filter (None, Time saved) shows them all."""
    if name not in FILTERS:
        return list(deals)
    return [deal for deal in deals if FILTERS[name][1](deal)]


def _stat_card(column, name, label, value, note, is_text=False):
    selected = st.session_state.get("deal_filter") == name
    with column:
        with st.container(border=True, key=f"statcard_{'on_' if selected else ''}{name}"):
            # The label is the button. CSS in app/style.py stretches its click area over the whole card.
            st.button(label, key=f"statbtn_{name}", type="tertiary", on_click=_select, args=(name,))
            style.html(f'<div class="stat-value{" text" if is_text else ""}">{escape(str(value))}</div>'
                       f'<div class="stat-note">{escape(note)}</div>')


def _stat_cards():
    stats = queries.dashboard_stats()
    columns = st.columns(4)
    _stat_card(columns[0], "active", "Active deals", stats["active_deals"], "Not yet approved")
    _stat_card(columns[1], "review", "Needs review", stats["needs_review"], "Waiting for a person")
    _stat_card(columns[2], TIME_SAVED, "Time saved", "Not measured yet", "Click to see how it will be measured", is_text=True)
    _stat_card(columns[3], "anomalies", "Anomalies", stats["anomalies"], "Flagged, never hidden")


def _time_saved_panel():
    with st.container(border=True, key="time_saved_panel"):
        st.markdown("**Time saved is not measured yet.**")
        st.markdown(
            "No number is shown because none has been measured, and this app does not show assumed figures.\n\n"
            "The plan for the accuracy report (roadmap Step 9):\n"
            "- time each deal from document received to draft ready, using the timings the app already logs;\n"
            "- compare that with how long the same prep takes by hand. That baseline has to come from the "
            "team or CBRE, and none has been collected yet."
        )
        st.button("Close", key="close_time_saved", on_click=nav.go_home)


def card_kind(deal):
    """Which accent a deal card gets: red for an anomaly, amber for review, none otherwise."""
    if deal["flag_count"]:
        return "flagged"
    return "review" if deal["status"] == "Needs Review" else "plain"


def _deal_card(deal):
    with st.container(border=True, key=f"deal_card_{card_kind(deal)}_{deal['id']}"):
        # The name is the button. CSS in app/style.py stretches its click area over the whole card.
        st.button(deal["name"], key=f"open_deal_{deal['id']}", type="tertiary",
                  on_click=nav.open_deal, args=(deal["id"],))
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


def _filtered_list(deals, name):
    shown = filter_deals(deals, name)
    with st.container(key="filter_bar", horizontal=True, vertical_alignment="center"):
        st.markdown(f'<div class="showing">Showing: {escape(FILTERS[name][0])} ({len(shown)})</div>',
                    unsafe_allow_html=True, width="content")
        st.button("Clear", key="clear_filter", icon=":material/close:", on_click=nav.go_home)
    if not shown:
        st.info("No deals match this filter.")
    for deal in shown:
        _deal_card(deal)


def render():
    st.header("All deals")
    _stat_cards()
    deals = queries.list_deals()
    selected = st.session_state.get("deal_filter")
    if selected in FILTERS:
        _filtered_list(deals, selected)
    else:
        if selected == TIME_SAVED:
            _time_saved_panel()
        _deal_group("Needs your attention", [d for d in deals if queries.needs_attention(d)])
        _deal_group("Other deals", [d for d in deals if not queries.needs_attention(d)])
    st.caption("Click a stat card to filter, or a deal to open it. Sample data only: every name and number here is made up.")
