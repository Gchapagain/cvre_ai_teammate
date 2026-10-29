"""CBRE AI Teammate. Start with:  .venv/bin/streamlit run streamlit_app.py

Viewing only reads the database. The app never runs seed.py and never deletes data.
"""

import os
from html import escape

import streamlit as st

from app import fresh


def _use_cloud_secrets():
    """On Streamlit Cloud, settings live in the app's Secrets instead of .env. Copy the plain text ones
    into the environment (never overriding one that is already set), before anything reads them."""
    try:
        secrets = dict(st.secrets)
    except Exception:  # no secrets file: running locally with .env
        return
    for name, value in secrets.items():
        if isinstance(value, str):
            os.environ.setdefault(name, value)


_use_cloud_secrets()
fresh.ensure()  # must run before the imports below: see app/fresh.py

from app import nav, queries, style  # noqa: E402
from services import gemini  # noqa: E402
import db  # noqa: E402
from app.views import assistant, connections_page, dashboard, deal, home, login, new_deal  # noqa: E402

st.set_page_config(page_title="CBRE AI Teammate", layout="wide")
style.apply()


def _sign_out():
    st.session_state.clear()


def _top_bar(user):
    """The full-width bar across the top: brand, Home, All deals and Connections on the left; user, role and
    sign out on the right."""
    with st.container(key="topbar", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        with st.container(key="topbar_nav", horizontal=True, vertical_alignment="center", width="content"):
            st.button("CBRE AI Teammate", key="nav_home", type="tertiary", on_click=nav.go_home)
            st.button("Home", key="nav_home_link", type="tertiary", on_click=nav.go_home)
            st.button("All deals", key="nav_all_deals", type="tertiary", on_click=nav.go_all_deals)
            st.button("Connections", key="nav_connections", type="tertiary", on_click=nav.open_connections)
        with st.container(key="topbar_user", horizontal=True, vertical_alignment="center", width="content"):
            unread = home.unread_count()
            st.button(str(unread), key="nav_bell", icon=":material/notifications:", type="tertiary", on_click=nav.go_home,
                      help=f"{unread} unread on Home" if unread else "Nothing unread on Home")
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
if queries.schema_version() < db.SCHEMA_VERSION:
    db.init_db()  # a database from an older version: add the new tables and columns (never touches the rows)

user = st.session_state.get("user")
if user is None:
    login.render()
else:
    _top_bar(user)
    if st.session_state.get("page") == "deal":
        deal.render()
    elif st.session_state.get("page") == "connections":
        connections_page.render()
    elif st.session_state.get("page") == "dashboard":
        dashboard.render()
    else:
        home.render()
    assistant.render()
    new_deal.render_dialog()
