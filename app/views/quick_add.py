"""The "+" button: add a property quickly with just its name, then go straight to its OM, slide 1.

Opened from the first tile of the Home project strip, the top bar (desktop and tablet) and the centre of the
phone bottom bar. One required field; type and location are optional. No AI (0 Gemini requests).
"""

import streamlit as st

from app import nav
from app.views import new_deal
from services import deals

DIALOG = "quick_add"


def open_dialog():
    for key in ("qa_name", "qa_type", "qa_location"):
        st.session_state.pop(key, None)
    nav.open_dialog(DIALOG)


def _create(name, property_type, location):
    """Create the deal, then reload the whole page on its OM (a button in a dialog otherwise reloads only the dialog)."""
    try:
        deal_id, warning = deals.quick_create(name, property_type, location)
    except ValueError as error:
        st.error(str(error))
        return
    nav.close_dialog()
    nav.open_deal_at(deal_id, "OM")
    st.session_state.om_view = "Slides"
    st.session_state.om_slide = "cover"
    st.session_state.om_flash = ("warning" if warning else "success",
                                 f"Created '{deals.check_name(name, deal_id)[0]}'. Start with slide 1, the cover."
                                 + (f" {warning}" if warning else ""))
    st.rerun()


@st.dialog("New property", icon=":material/add_home:", on_dismiss=nav.close_dialog)
def _dialog():
    name = st.text_input("Property name", key="qa_name", max_chars=deals.NAME_MAX, placeholder="For example: Larkspur Yard")
    try:
        warning = deals.check_name(name)[1] if name.strip() else None
    except ValueError:
        warning = None
    if warning:
        st.warning(warning)
    left, right = st.columns(2)
    property_type = left.selectbox("Property type (optional)", deals.PROPERTY_TYPES, index=None, key="qa_type",
                                   placeholder="Choose a type")
    location = right.text_input("Location (optional)", key="qa_location", max_chars=deals.NAME_MAX, placeholder="City, ST")
    if st.button("Create", key="qa_create", type="primary", icon=":material/check:", width="stretch"):
        _create(name, property_type, location)
    st.caption("Creates the deal straight away (status New) and opens its OM on slide 1. No AI is used.")
    if st.button("More ways to start (upload files or describe it to the AI)", key="qa_more", type="tertiary"):
        nav.close_dialog()
        new_deal._open()
        st.rerun()


def render_dialog():
    if nav.dialog_is_open(DIALOG):
        _dialog()
