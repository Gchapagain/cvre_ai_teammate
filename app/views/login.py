"""Login: step 1 pick a role, step 2 sign in. The sign-in buttons stay locked until a role is chosen."""

import streamlit as st

from app import queries

ROLES = ["Agent", "Analyst", "Administrator"]


def _sign_in(role):
    st.session_state.user = queries.demo_user(role)
    st.session_state.page = "dashboard"


def render():
    st.title("CBRE AI Teammate")
    st.caption("The AI drafts, flags and cites. A person always approves.")

    st.subheader("Step 1: Choose your role")
    role = st.radio("Role", ROLES, index=None, key="login_role", label_visibility="collapsed")

    st.subheader("Step 2: Sign in")
    st.info("Demo login. No real Google or Microsoft sign-in happens yet: "
            "either button signs you in as a made-up demo user for the role you chose.")
    if role is None:
        st.caption("Choose a role above to unlock sign-in.")
    for provider in ("Google", "Microsoft"):
        st.button(f"Sign in with {provider} (demo)", key=f"sign_in_{provider.lower()}",
                  disabled=role is None, on_click=_sign_in, args=(role,), width="stretch")
