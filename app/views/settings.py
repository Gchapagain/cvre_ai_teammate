"""Settings: the broker's profile (title and phone for the OM contacts page) and their own logo for the cover.

Opened from the user name in the top bar. Saving is the only write; the logo file is git-ignored.
"""

import streamlit as st

from app import queries, style
from services import branding, om_slots


def render():
    user = st.session_state.get("user") or {}
    profile = queries.profile(user.get("email")) or {}
    st.header("Settings")
    left, right = st.columns(2, gap="large")
    with left, st.container(key="settings_profile"):
        style.section_title("Your profile")
        st.caption("Shown on the OM's Investment Contacts page. Sample data only: use made-up details for the demo.")
        st.text_input("Name", profile.get("full_name", ""), disabled=True, help="The demo login's name.")
        st.text_input("Email", profile.get("email", ""), disabled=True)
        title = st.text_input("Title", profile.get("title") or "", key="settings_title", placeholder="for example Senior Vice President")
        phone = st.text_input("Phone", profile.get("phone") or "", key="settings_phone", placeholder="(555) 010-0142")
        if st.button("Save profile", key="settings_save", type="primary", icon=":material/save:"):
            om_slots.save_profile(profile.get("email"), title, phone)
            st.success("Profile saved.")
    with right, st.container(key="settings_logo"):
        style.section_title("Your logo")
        st.caption("Optional. Shown small on the OM cover. A PNG, JPEG or WebP up to 5 MB, kept on this server only "
                   "and never in the code. Use a logo you have the right to use.")
        current = branding.logo_path(profile.get("email"))
        if current:
            st.image(str(current), width=220)
            if st.button("Remove logo", key="settings_logo_remove", icon=":material/delete:"):
                branding.remove_logo(profile.get("email"))
                st.rerun()
        else:
            st.caption("No logo: the cover uses a plain text heading.")
        upload = st.file_uploader("Logo", type=["png", "jpg", "jpeg", "webp"], key=f"settings_logo_{st.session_state.get('logo_round', 0)}")
        if st.button("Save logo", key="settings_logo_save", disabled=upload is None):
            try:
                branding.save_logo(profile.get("email"), upload.name, upload.getvalue())
            except ValueError as error:
                st.error(str(error))
            else:
                st.session_state.logo_round = st.session_state.get("logo_round", 0) + 1
                st.rerun()
