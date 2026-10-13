"""The AI Teammate assistant: a floating button on every page that opens a chat about any deal or all deals."""

import streamlit as st

from app import nav, queries
from app.views import ask_ai

DIALOG = "assistant"
ALL_DEALS = "All deals"
BUTTON_LABEL = "Ask the AI Teammate"


def _open():
    # Start on the deal being viewed, or on all deals from the dashboard.
    on_deal_page = st.session_state.get("page") == "deal"
    st.session_state.assistant_scope = st.session_state.get("deal_id") if on_deal_page else ALL_DEALS
    nav.open_dialog(DIALOG)


@st.dialog("AI Teammate", width="large", icon=":material/auto_awesome:", on_dismiss=nav.close_dialog)
def _dialog():
    names = {deal["id"]: deal["name"] for deal in queries.list_deals()}
    choice = st.selectbox("Ask about", [ALL_DEALS, *names], format_func=lambda d: names.get(d, ALL_DEALS),
                          key="assistant_scope")
    deal_id = None if choice == ALL_DEALS else choice
    if deal_id is None:
        st.caption("Answers come only from the deals saved in the database, and name the deals they used. "
                   "The AI is only contacted when you send a message.")
    else:
        st.caption("Answers come only from this deal's saved data. The AI is only contacted when you send a message.")
    ask_ai.render_chat(deal_id, prefix="assistant_")


def render():
    """Draw the floating button, and the chat dialog while it is open.

    CSS in app/style.py pins the button to the bottom-right corner.
    """
    with st.container(key="fab"):
        st.button(BUTTON_LABEL, key="open_assistant", icon=":material/auto_awesome:", on_click=_open)
    if nav.dialog_is_open(DIALOG):
        _dialog()
