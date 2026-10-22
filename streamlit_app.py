"""CBRE AI Teammate. Start with:  .venv/bin/streamlit run streamlit_app.py

The app only reads the database. It never runs seed.py and never deletes data.
"""

from html import escape

import streamlit as st

from app import fresh

fresh.ensure()  # must run before the imports below: see app/fresh.py

from app import nav, queries, style  # noqa: E402
from services import gemini  # noqa: E402
from app.views import assistant, connections_page, dashboard, deal, login, new_deal  # noqa: E402

st.set_page_config(page_title="CBRE AI Teammate", layout="wide")
style.apply()


def _sign_out():
    st.session_state.clear()


def _top_bar(user):
    """The full-width bar across the top: brand and All deals on the left; user, role and sign out on the right."""
    with st.container(key="topbar", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        with st.container(key="topbar_nav", horizontal=True, vertical_alignment="center", width="content"):
            # Both go to the main dashboard and clear any filter.
            st.button("CBRE AI Teammate", key="nav_home", type="tertiary", on_click=nav.go_home)
            st.button("All deals", key="nav_all_deals", type="tertiary", on_click=nav.go_home)
            st.button("Connections", key="nav_connections", type="tertiary", on_click=nav.open_connections)
        with st.container(key="topbar_user", horizontal=True, vertical_alignment="center", width="content"):
            if gemini.simulated():
                st.markdown('<span class="pill simulated">SIMULATED AI</span>', unsafe_allow_html=True, width="content")
            st.markdown(f'<div class="who"><span class="user-name">{escape(user["full_name"])}</span>'
                        f'<span class="role-badge">{escape(user["role"])}</span></div>',
                        unsafe_allow_html=True, width="content")
            st.button("Sign out", key="sign_out", on_click=_sign_out)


if not queries.database_ready():
    st.title("CBRE AI Teammate")
    st.warning("There is no sample data yet. Stop the app, run this in the project folder, then start it again:")
    st.code(".venv/bin/python seed.py --reset")
    st.stop()

user = st.session_state.get("user")
if user is None:
    login.render()
else:
    _top_bar(user)
    if st.session_state.get("page") == "deal":
        deal.render()
    elif st.session_state.get("page") == "connections":
        connections_page.render()
    else:
        dashboard.render()
    assistant.render()
    new_deal.render_dialog()
