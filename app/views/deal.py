"""Deal workspace: Review, Documents, Data and Ask AI tabs. Documents is still a placeholder."""

from html import escape

import pandas as pd
import streamlit as st

from app import nav, queries, style
from app.views import ask_ai, data_tab, notes

COLUMNS = {
    "unit_number": "Unit", "tenant_name": "Tenant", "square_feet": "SF",
    "lease_start": "Lease start", "lease_end": "Lease end", "monthly_rent": "Monthly rent",
    "annual_rent": "Annual rent", "rent_per_sf": "Rent / SF", "lease_type": "Lease type",
}
# The last tab is styled as the gold AI tab in app/style.py.
TABS = ["Review", "Documents", "Data", ":material/auto_awesome: Ask AI"]
FLAG_ROW_STYLE = "background-color: #fbe1df; color: #5e130d; font-weight: 600"


def _number(decimals):
    """Format numbers for display, but show anything else exactly as stored."""
    def show(value):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f"{value:,.{decimals}f}"
        return "" if value is None else str(value)
    return show


def units_table(units, flags):
    """The rent roll as a table with a Flag column. Flagged rows are marked in words, not only colour."""
    flagged_ids = {flag["rent_roll_unit_id"] for flag in flags}
    table = pd.DataFrame([{label: unit[field] for field, label in COLUMNS.items()} for unit in units])
    table.insert(1, "Flag", ["Flagged" if unit["id"] in flagged_ids else "" for unit in units])
    return table


def _styled(table):
    highlight = lambda row: [FLAG_ROW_STYLE if row["Flag"] else ""] * len(row)
    return table.style.apply(highlight, axis=1).format(
        {"SF": _number(0), "Monthly rent": _number(2), "Annual rent": _number(2), "Rent / SF": _number(2)}
    )


def _anomaly_banner(flags):
    if flags:
        count = len(flags)
        style.html(style.banner(
            "flagged", f"{count} anomal{'y' if count == 1 else 'ies'} found",
            [flag["message"] for flag in flags],
            "Flagged, not hidden: the numbers below are shown exactly as extracted. A person decides what to do.",
        ))
    else:
        style.html(style.banner("clear", "No anomalies found", footer="Every validation rule passed for this rent roll."))


def _review_tab(deal):
    units = queries.deal_units(deal["id"])
    if not units:
        documents = queries.deal_documents(deal["id"])
        footer = ("This deal's documents have not been read yet, so there is nothing to review."
                  if documents else "This deal has no documents yet, so there is nothing to review.")
        style.html(style.banner("waiting", "No numbers yet", [f"{d['filename']}: {d['status']}" for d in documents], footer))
        return
    flags = queries.deal_flags(deal["id"])
    _anomaly_banner(flags)
    st.subheader("Extracted fields")
    st.dataframe(_styled(units_table(units, flags)), hide_index=True, width="stretch",
                 column_config={"Flag": st.column_config.TextColumn(width=90)})
    sources = [doc["filename"] for doc in queries.deal_documents(deal["id"]) if doc["used_for"] == "Rent roll"]
    st.caption(f"From this deal: {', '.join(sources)} (sample data).")


def render():
    deal = queries.get_deal(st.session_state.get("deal_id"))
    with st.container(key="breadcrumb", horizontal=True, vertical_alignment="center"):
        st.button("All deals", key="back_to_deals", type="tertiary", on_click=nav.go_home)
        name = escape(deal["name"]) if deal else "Deal not found"
        st.markdown(f'<div class="crumb"><span class="sep">›</span><span class="here">{name}</span></div>',
                    unsafe_allow_html=True, width="content")
    if deal is None:
        st.warning("That deal could not be found.")
        return
    st.header(deal["name"])
    style.html(f'<div class="deal-head"><div class="deal-meta">{escape(deal["property_type"] or "")} · '
               f'{escape(deal["submarket"] or "")}</div>{style.pill(deal["status"])}</div>')

    review, documents, data, ask_ai_tab = st.tabs(TABS)
    with review:
        _review_tab(deal)
        notes.render(deal)
    with documents:
        st.info("Documents: coming in a later step.")
    with data:
        data_tab.render(deal)
    with ask_ai_tab:
        ask_ai.render(deal)
