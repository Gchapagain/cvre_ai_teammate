"""Deal workspace: a header card, then the Review, Documents, Data and Ask AI tabs."""

from html import escape

import streamlit as st

from app import nav, queries, style
from app.views import ask_ai, data_tab, review
from services import metrics

# The last tab is styled as the gold AI tab in app/style.py.
ASK_AI_TAB = ":material/auto_awesome: Ask AI"


def tab_labels(document_count):
    """The four tabs. Documents carries a count badge."""
    return ["Review", f"Documents :gray-badge[{document_count}]", "Data", ASK_AI_TAB]


def header_line(deal, units, documents):
    """'Industrial · Location · 12 units · 154,600 SF · Extracted 3 hours ago', using only what is saved."""
    parts = [deal["property_type"], deal["submarket"]]
    if units:
        parts.append(f"{len(units)} units")
        sf = metrics.total_sf(units)
        parts.append(f"{sf:,.0f} SF" if sf else None)
        read = [doc for doc in documents if doc["used_for"] == "Rent roll"]
        ago = metrics.time_ago(read[0]["received_at"]) if read else ""
        parts.append(f"Extracted {ago}" if ago else None)
    else:
        parts.append("No numbers yet")
    return " · ".join(part for part in parts if part)


def _header(deal, units, documents):
    chips = "".join(f'<span class="chip">from {escape(doc["filename"])}</span>'
                    for doc in documents if doc["used_for"] == "Rent roll")
    with st.container(border=True, key="deal_header"):
        style.html(
            f'<div class="deal-top"><div><div class="deal-title">{escape(deal["name"])}{chips}</div>'
            f'<div class="deal-meta">{escape(header_line(deal, units, documents))}</div></div>'
            f'<div>{style.pill(deal["status"])}</div></div>'
        )


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
    units, documents = queries.deal_units(deal["id"]), queries.deal_documents(deal["id"])
    _header(deal, units, documents)

    labels = tab_labels(len(documents))
    st.session_state.documents_tab_label = labels[1]
    # on_change="rerun" makes the tabs keep their state, which lets a link switch tabs.
    review_tab, documents_tab, data, ask_ai_tab = st.tabs(labels, key="deal_tabs", on_change="rerun")
    with review_tab:
        review.render(deal)
    with documents_tab:
        st.info("Documents: coming in a later step.")
    with data:
        data_tab.render(deal)
    with ask_ai_tab:
        ask_ai.render(deal)
