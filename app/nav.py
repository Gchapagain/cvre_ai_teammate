"""Moving between pages. Pages are kept in st.session_state, not in the URL."""

import streamlit as st


def go_home():
    """Go to the main dashboard showing every deal, with any stat-card filter cleared."""
    st.session_state.page = "dashboard"
    st.session_state.deal_filter = None


def open_deal(deal_id):
    st.session_state.deal_id = deal_id
    st.session_state.page = "deal"
