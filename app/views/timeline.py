"""The deal's activity timeline: every edit, undo, confirmation, approval and reopening."""

from html import escape

import streamlit as st

from app import queries, style
from services import corrections, metrics

TITLES = {"edit": "Edited", "undo": "Undone", "confirmed": "Flag confirmed", "approved": "Deal approved", "reopened": "Reopened for changes"}
ICONS = {"edit": "edit", "undo": "undo", "confirmed": "verified", "approved": "task_alt", "reopened": "lock_open"}


def _undo(batch_id):
    try:
        corrections.undo(batch_id, st.session_state.user["full_name"])
        st.session_state.edit_result = {"kind": "success", "text": "Undone. The old value is back and the deal was checked again."}
    except (corrections.Locked, ValueError) as exc:
        st.session_state.edit_result = {"kind": "warning", "text": f"Not undone. {exc}"}


def render(deal, locked):
    events = queries.deal_events(deal["id"])
    reverted = {e["batch_id"] for e in queries.deal_edits(deal["id"]) if e["reverted_at"]}
    with st.container(border=True, key="card_timeline"):
        style.html('<div class="card-title">Activity</div>')
        if not events:
            st.caption("No changes, confirmations or approvals yet.")
        for event in events:
            source = f" · {event['source']}" if event["source"] else ""
            with st.container(key=f"event_{event['id']}"):
                style.html(f'<div class="event"><div class="event-title">{escape(TITLES[event["kind"]])}</div>'
                           f'<div class="event-meta">{escape(event["user"])} · {escape(metrics.time_ago(event["created_at"]) or event["created_at"])}'
                           f'{escape(source)}</div>'
                           + (f'<div class="event-detail">{escape(event["detail"])}</div>' if event["detail"] else "")
                           + (f'<div class="event-why">Why: {escape(event["reason"])}</div>' if event["reason"] else "") + "</div>")
                if event["kind"] == "edit":
                    if event["batch_id"] in reverted:
                        style.html('<span class="pill other">Undone</span>')
                    else:
                        st.button("Undo", key=f"undo_{event['batch_id']}", icon=":material/undo:", disabled=locked,
                                  on_click=_undo, args=(event["batch_id"],),
                                  help="Locked while the deal is approved." if locked else "Puts the old values back.")
