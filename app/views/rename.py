"""Renaming a deal (and editing its type and location) from a small pencil next to its name.

The pencil sits on the deal header and on the deal cards in Home and All deals. Tapping it turns the name
into a text box with Save (or Enter) and Cancel (or Esc), plus "Edit details" for the type and location.
Every change is logged in deal_changes and can be undone from the "Renamed. Undo" bar. No AI is used.
"""

from html import escape

import streamlit as st

from app import nav
from services import deals

ESC_SCRIPT = """<script>
(function () {
  const doc = window.parent.document || document;
  if (doc.cbreRenameEsc) return;
  doc.cbreRenameEsc = true;
  doc.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    const form = event.target.closest && event.target.closest('[data-testid="stForm"]');
    const cancel = form && form.querySelector('[class*="st-key-rename_cancel_"] button');
    if (cancel) { event.preventDefault(); cancel.click(); }
  });
})();
</script>"""


def _id(where, deal_id):
    return f"{where}_{deal_id}"


def is_editing(where, deal_id):
    return st.session_state.get("renaming") == _id(where, deal_id)


def _start(where, deal_id):
    st.session_state.renaming = _id(where, deal_id)


def _stop():
    st.session_state.pop("renaming", None)


def pencil(deal, where):
    """The small pencil. Its label is read out by screen readers; CSS shows only the icon."""
    st.button("Rename", key=f"rename_btn_{_id(where, deal['id'])}", icon=":material/edit:", type="tertiary",
              help="Rename this deal or edit its type and location", on_click=_start, args=(where, deal["id"]))


def form(deal, where):
    """The inline edit form that replaces the name while editing."""
    key = _id(where, deal["id"])
    with st.form(f"rename_form_{key}", border=False, enter_to_submit=True):
        name = st.text_input("Property name", deal["name"], max_chars=deals.NAME_MAX, key=f"rename_name_{key}",
                             label_visibility="collapsed")
        with st.expander("Edit details"):
            types = deals.PROPERTY_TYPES
            property_type = st.selectbox("Property type", types, key=f"rename_type_{key}", placeholder="Choose a type",
                                         index=types.index(deal["property_type"]) if deal["property_type"] in types else None)
            location = st.text_input("Location", deal["submarket"] or "", max_chars=deals.NAME_MAX, key=f"rename_location_{key}")
        with st.container(horizontal=True, key=f"rename_buttons_{key}"):
            save = st.form_submit_button("Save", icon=":material/check:", type="primary", key=f"rename_save_{key}")
            cancel = st.form_submit_button("Cancel", icon=":material/close:", key=f"rename_cancel_{key}")
    st.html(ESC_SCRIPT, unsafe_allow_javascript=True)
    if cancel:
        _stop()
        st.rerun()
    if save:
        changes = {"name": name, "property_type": property_type, "submarket": location}
        try:
            result = deals.update_details(deal["id"], changes, _user())
        except ValueError as error:
            st.error(str(error))
            return
        _stop()
        if result["changed"]:
            st.session_state.rename_undo_info = {"deal_id": deal["id"], "ids": result["change_ids"], "warning": result["warning"],
                                            "text": _summary(result, changes), "reapprove": result["reapprove"]}
        st.rerun()


def _user():
    return (st.session_state.get("user") or {}).get("full_name", "Broker")


def _summary(result, changes):
    if result["changed"] == [deals.DETAILS["name"]]:
        return f"Renamed to '{changes['name']}'."
    if deals.DETAILS["name"] in result["changed"]:
        return f"Renamed to '{changes['name']}' and saved {', '.join(c for c in result['changed'] if c != 'Property name').lower()}."
    return f"Saved {', '.join(result['changed']).lower()}."


def _undo():
    info = st.session_state.pop("rename_undo_info", None)
    if info:
        undone = deals.undo_changes(info["ids"], _user())
        st.session_state.rename_undone = ("Undone: " + ", ".join(undone).lower() + " put back." if undone else
                                          "Nothing to undo: it was changed again since.")


def _open_cover(deal_id):
    st.session_state.pop("rename_undo_info", None)
    nav.open_deal_at(deal_id, "OM")
    st.session_state.om_view = "Slides"
    st.session_state.om_slide = "cover"


def undo_bar():
    """'Renamed. Undo' after a change, until the person undoes or closes it. Shown at the top of any page."""
    done = st.session_state.pop("rename_undone", None)
    if done:
        st.info(done)
    info = st.session_state.get("rename_undo_info")
    if not info:
        return
    with st.container(key="rename_undo_bar", horizontal=True, vertical_alignment="center"):
        st.markdown(f'<div class="undo-text">{escape(info["text"])}</div>', unsafe_allow_html=True, width="content")
        st.button("Undo", key="rename_undo", icon=":material/undo:", on_click=_undo)
        st.button("Close", key="rename_undo_close", type="tertiary", icon=":material/close:",
                  on_click=lambda: st.session_state.pop("rename_undo_info", None))
    if info.get("warning"):
        st.warning(info["warning"])
    if info.get("reapprove"):
        with st.container(key="rename_reapprove", horizontal=True, vertical_alignment="center"):
            st.warning("The name changed, please re-approve the cover"
                       + (f" (it is also on: {', '.join(t for t in info['reapprove'] if t != 'Cover')})." if len(info["reapprove"]) > 1 else "."))
            st.button("Open the cover", key="rename_open_cover", on_click=_open_cover, args=(info["deal_id"],))
