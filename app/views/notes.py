"""Notes on a deal, shown exactly as the person saved them."""

from html import escape

import streamlit as st

from app import queries, style
from services import deals

PILL_KINDS = {"Recording": "from-deal", "Typed": "other"}


def _save_typed(deal_id, key):
    text = st.session_state.get(key, "")
    if text.strip():
        deals.add_note(deal_id, text, "Typed")
        st.session_state[key] = ""


def render(deal):
    st.subheader("Notes")
    notes = queries.deal_notes(deal["id"])
    if not notes:
        st.caption("No notes yet. Type one below, or record one from the Ask AI tab.")
    for note in notes:
        with st.container(border=True, key=f"note_{note['id']}"):
            style.html(f'<div class="note-text">{escape(note["text"])}</div>'
                       f'<div class="note-meta">{style.pill(note["source"], PILL_KINDS.get(note["source"], "other"))}'
                       f'Saved {escape(note["created_at"][:16])} UTC</div>')
    key = f"new_note_{deal['id']}"
    st.text_area("Add a note", key=key, height=80, placeholder="Type a note about this deal")
    st.button("Save note", key=f"save_note_{deal['id']}", on_click=_save_typed, args=(deal["id"], key))
