"""CBRE AI Teammate. Start with:  .venv/bin/streamlit run streamlit_app.py

The app only reads the database. It never runs seed.py and never deletes data.
"""

from html import escape

import streamlit as st

from app import queries, style
from app.views import dashboard, deal, login

st.set_page_config(page_title="CBRE AI Teammate", layout="wide")
style.apply()


def _sign_out():
    st.session_state.clear()


def _top_bar(user):
    style.html(
        '<div class="topbar"><div class="brand">CBRE AI Teammate</div>'
        f'<div class="who">{escape(user["full_name"])} · {escape(user["role"])} · demo login</div></div>'
    )
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
    else:
        dashboard.render()
