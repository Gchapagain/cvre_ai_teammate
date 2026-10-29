"""The New deal dialog: start a deal from uploaded files, or from a description the AI drafts from.

Gemini is only called when the person presses a button here. The AI never saves a deal:
a deal is created only when the person presses Create deal.
"""

import logging

import streamlit as st

from app import nav
from app.views import voice
from services import deals, gemini, new_deal

log = logging.getLogger(__name__)

DIALOG = "new_deal"
UPLOAD, DESCRIBE = "Upload files", "Describe it to the AI"
QUOTA_MESSAGE = ("The AI's daily quota is used up, so it can't draft this right now. {detail} "
                 "Nothing was saved. You can still fill in the form yourself.")
BUSY_MESSAGE = "The AI is busy or rate-limited at the moment. Try again in a minute, or fill in the form yourself."
OTHER_MESSAGE = "The AI couldn't draft this just now. {detail} You can still fill in the form yourself."


def _open():
    for key in ("nd_draft", "nd_draft_message"):
        st.session_state.pop(key, None)
    nav.open_dialog(DIALOG)


def _finish(message, kind="success"):
    """Close the dialog and show the result at the top of the dashboard."""
    st.session_state.flash = {"kind": kind, "message": message}
    nav.close_dialog()
    nav.go_all_deals()
    st.rerun()


def upload_summary(name, result):
    """One plain message describing what happened to each uploaded file."""
    lines = [f"Created '{name.strip()}'."] + [f"{f['filename']}: {f['message']}" for f in result["files"]]
    return "  \n".join(lines), ("success" if result["read"] else "warning")


def _upload_form():
    name = st.text_input("Deal name", key="nd_name")
    left, right = st.columns(2)
    property_type = left.selectbox("Property type", deals.PROPERTY_TYPES, index=None, key="nd_type",
                                   placeholder="Choose a type")
    location = right.text_input("Location", key="nd_location")
    files = st.file_uploader("Rent roll and T-12 files (xlsx or csv)", type=["xlsx", "csv"],
                             accept_multiple_files=True, max_upload_size=20, key="nd_files")
    st.caption("Sample data only: do not upload real client files. Reading a rent roll uses one AI request. "
               "T-12 files are saved but not read yet.")
    if st.button("Create deal and read files", key="nd_create_upload", type="primary", icon=":material/upload_file:"):
        if not name.strip():
            st.error("Give the deal a name.")
        elif not files:
            st.error("Add at least one file, or use 'Describe it to the AI' to start without files.")
        else:
            with st.status("Creating the deal...", expanded=True) as status:
                result = new_deal.create_from_uploads(
                    name, property_type, location, [(f.name, f.getvalue()) for f in files], progress=status.write)
            _finish(*upload_summary(name, result))


def _draft(description):
    """Ask the AI for a draft. Problems become a message; the form still opens for manual entry."""
    st.session_state.nd_draft_message = None
    try:
        draft = new_deal.draft_from_description(description)
    except ValueError as exc:
        st.session_state.nd_draft_message = str(exc)
        return
    except gemini.GeminiQuotaError as exc:
        draft, message = new_deal.DealDraft(), QUOTA_MESSAGE.format(detail=exc)
    except gemini.GeminiBusyError:
        draft, message = new_deal.DealDraft(), BUSY_MESSAGE
    except gemini.RateLimited as exc:  # our own limit, not Google's
        draft, message = new_deal.DealDraft(), f"{exc} You can still fill in the form yourself."
    except gemini.GeminiError as exc:
        draft, message = new_deal.DealDraft(), OTHER_MESSAGE.format(detail=exc)
    except Exception:
        log.exception("Drafting a deal failed")
        draft, message = new_deal.DealDraft(), OTHER_MESSAGE.format(detail="Something unexpected went wrong.")
    else:
        message = ("The AI left out: " + "; ".join(draft.removed) + ".") if draft.removed else None
    st.session_state.nd_draft = draft
    st.session_state.nd_draft_message = message
    st.session_state.nd_draft_number = st.session_state.get("nd_draft_number", 0) + 1


def _draft_form(draft):
    """The draft as an editable form. Nothing is saved until Create deal is pressed."""
    number = st.session_state.get("nd_draft_number", 0)  # a new draft gets fresh fields
    with st.form(f"nd_form_{number}", border=True):
        st.markdown("**Draft: check every field.** Blank means the AI was not told. "
                    "Nothing is saved until you press Create deal.")
        name = st.text_input("Deal name", value=draft.name, key=f"ndf_name_{number}")
        left, right = st.columns(2)
        types = deals.PROPERTY_TYPES
        property_type = left.selectbox("Property type", types, placeholder="Choose a type", key=f"ndf_type_{number}",
                                       index=types.index(draft.property_type) if draft.property_type else None)
        location = right.text_input("Location", value=draft.location, key=f"ndf_location_{number}")
        notes = st.text_area("Other facts (saved as a note on the deal)", value="\n".join(draft.facts),
                             key=f"ndf_notes_{number}")
        if st.form_submit_button("Create deal", type="primary", icon=":material/check:"):
            if not name.strip():
                st.error("Give the deal a name.")
            else:
                new_deal.create_from_draft(name, property_type, location, notes)
                _finish(f"Created '{name.strip()}'. It has no documents yet.")


def _describe_form():
    if "nd_description_spoken" in st.session_state:  # a checked transcript, added before the box is drawn
        typed = st.session_state.get("nd_description", "").strip()
        st.session_state.nd_description = (typed + "\n" if typed else "") + st.session_state.pop("nd_description_spoken")
    description = st.text_area("What do you know about the deal?", key="nd_description", height=110,
                               placeholder="For example: a 40,000 sf warehouse in Fort Worth with three tenants...")
    st.caption("The AI turns this into a draft for you to check. It uses one AI request and saves nothing.")
    if st.button("Draft with AI", key="nd_draft_button", icon=":material/auto_awesome:"):
        with st.spinner("Drafting..."):
            _draft(description)
    spoken = voice.render("nd", use_label="Use as my description")
    if spoken:
        st.session_state.nd_description_spoken = spoken
        st.rerun()
    if st.session_state.get("nd_draft_message"):
        st.warning(st.session_state.nd_draft_message)
    if st.session_state.get("nd_draft") is not None:
        _draft_form(st.session_state.nd_draft)


@st.dialog("New deal", width="large", icon=":material/add_circle:", on_dismiss=nav.close_dialog)
def _dialog():
    mode = st.segmented_control("How do you want to start?", [UPLOAD, DESCRIBE], default=UPLOAD, key="nd_mode")
    if mode == DESCRIBE:
        _describe_form()
    else:
        _upload_form()


def button():
    st.button("New deal", key="new_deal", type="primary", icon=":material/add:", on_click=_open)


def render_dialog():
    if nav.dialog_is_open(DIALOG):
        _dialog()
