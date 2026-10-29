"""Deal workspace: a header card, then the Review, Documents, Data and Ask AI tabs."""

from html import escape

import streamlit as st

from app import images, nav, queries, style
from app.views import ask_ai, data_tab, recommendations_tab, review
from services import deals, metrics

# The last tab is styled as the gold AI tab in app/style.py.
ASK_AI_TAB = ":material/auto_awesome: Ask AI"


def tab_labels(document_count):
    """The four tabs. Documents carries a count badge."""
    return ["Review", f"Documents :gray-badge[{document_count}]", "Data", "Recommendations", ASK_AI_TAB]


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
    picture, is_photo = images.picture(deal)
    with st.container(border=True, key="deal_header"):
        style.html(
            f'<div class="deal-top"><div class="deal-id"><img class="deal-thumb" src="{picture}" '
            f'alt="{"Photo" if is_photo else "Illustration"} of the property"><div>'
            f'<div class="deal-title">{escape(deal["name"])}{chips}</div>'
            f'<div class="deal-meta">{escape(header_line(deal, units, documents))}</div></div></div>'
            f'<div>{style.pill(deal["status"])}</div></div>'
        )
        _change_photo(deal, is_photo)


def _change_photo(deal, is_photo):
    """A small upload that swaps the illustration for a real photo of the property. Saved only on Save."""
    with st.popover("Change photo", icon=":material/photo_camera:", key="change_photo"):
        st.caption("A PNG, JPEG or WebP picture up to 5 MB. Sample data only: use a photo you are free to share."
                   + ("" if is_photo else " Until then, Home shows an illustration for the property type."))
        round_ = st.session_state.get("photo_round", 0)  # a new key after each save empties the uploader
        upload = st.file_uploader("Property photo", type=["png", "jpg", "jpeg", "webp"], key=f"photo_upload_{round_}")
        if st.button("Save photo", key="save_photo", type="primary", disabled=upload is None):
            try:
                deals.set_photo(deal["id"], upload.name, upload.getvalue())
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state.photo_round = round_ + 1
                st.rerun()


def render():
    deal = queries.get_deal(st.session_state.get("deal_id"))
    with st.container(key="breadcrumb", horizontal=True, vertical_alignment="center"):
        st.button("All deals", key="back_to_deals", type="tertiary", on_click=nav.go_all_deals)
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
    review_tab, documents_tab, data, recommendations, ask_ai_tab = st.tabs(labels, key="deal_tabs", on_change="rerun")
    with review_tab:
        review.render(deal)
    with documents_tab:
        st.info("Documents: coming in a later step.")
    with data:
        data_tab.render(deal)
    with recommendations:
        recommendations_tab.render(deal)
    with ask_ai_tab:
        ask_ai.render(deal)
    _scroll_to_flag(st.session_state.pop("focus_flag", None))


def _scroll_to_flag(flag_id):
    """Coming from a Home flag: bring that flag's decision card into view and outline it for a moment."""
    if flag_id is None:
        return
    st.html(f"""<script>
    setTimeout(function () {{
      const card = document.querySelector(".st-key-flagcard_open_{int(flag_id)}");
      if (!card) return;
      card.scrollIntoView({{behavior: "smooth", block: "center"}});
      card.classList.add("flag-focus");
      setTimeout(function () {{ card.classList.remove("flag-focus"); }}, 2500);
    }}, 400);
    </script>""", unsafe_allow_javascript=True)
