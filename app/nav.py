"""Moving between pages. Pages are kept in st.session_state, not in the URL."""

import streamlit as st


def go_home():
    """Go to the main dashboard showing every deal, with any stat-card filter cleared."""
    st.session_state.page = "dashboard"
    st.session_state.deal_filter = None


def open_connections():
    st.session_state.page = "connections"


def open_deal(deal_id):
    st.session_state.deal_id = deal_id
    st.session_state.page = "deal"


def open_dialog(name):
    """Only one dialog can be open at a time, so opening one closes any other."""
    st.session_state.open_dialog = name


def close_dialog():
    st.session_state.open_dialog = None


def dialog_is_open(name):
    return st.session_state.get("open_dialog") == name
