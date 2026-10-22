"""The approval panel: a checklist, 'Review and approve' (locked until every flag is resolved), the
summary dialog, the approved banner and 'Reopen for changes'."""

from html import escape

import streamlit as st

from app import nav, queries, style
from app.views import editing
from services import corrections, metrics

DIALOG = "approve"


def _close():
    nav.close_dialog()


def _do_approve(deal_id):
    try:
        corrections.approve(deal_id, st.session_state.user["full_name"])
        st.session_state.edit_result = {"kind": "success", "text": "Deal approved. Values and flags are now locked."}
    except ValueError as exc:
        st.session_state.edit_result = {"kind": "warning", "text": f"Not approved. {exc}"}
    nav.close_dialog()


@st.dialog("Review and approve", width="large", on_dismiss=_close)
def _dialog(deal):
    summary = corrections.approval_summary(deal["id"])
    st.markdown(f"**{escape(deal['name'])}**")
    style.html(f'<div class="approve-counts"><span class="pill approved">{len(summary["confirmed"])} flag(s) confirmed</span>'
               f'<span class="pill approved">{len(summary["corrected"])} flag(s) corrected</span>'
               f'<span class="pill other">{len(summary["edits"])} value(s) changed</span></div>')
    for title, rows in (("Confirmed", summary["confirmed"]), ("Corrected", summary["corrected"])):
        if rows:
            st.markdown(f"**{title}**")
            style.html('<ul class="takeaways">' + "".join(
                f'<li>Unit {escape(f["unit_number"] or "(no ID)")}: {escape(metrics.rule_name(f["rule"]))} · {escape(f["resolved_by"] or "")} · '
                f'{escape(f["resolution_reason"] or "")}{(": " + escape(f["resolution_note"])) if f["resolution_note"] else ""}</li>'
                for f in rows) + "</ul>")
    if summary["edits"]:
        st.markdown("**Every change made**")
        rows = "".join(f'<tr><td>{escape(e["unit_number"] or "")}</td><td>{escape(corrections.LABELS.get(e["field"], e["field"]))}</td>'
                       f'<td>{escape(editing.show(e["old"]))}</td><td>{escape(editing.show(e["new"]))}</td>'
                       f'<td>{escape(e["user"])} · {escape(e["source"])}</td><td>{escape(e["reason"])}</td></tr>' for e in summary["edits"])
        style.html('<table class="preview"><thead><tr><th>Unit</th><th>Field</th><th>Was</th><th>Now</th><th>Who</th>'
                   f'<th>Why</th></tr></thead><tbody>{rows}</tbody></table>')
    else:
        st.caption("No values were changed.")
    st.caption("Approving records your name and the time, and locks values and flags until the deal is reopened.")
    actions = st.container(horizontal=True)
    # A button inside a dialog only reruns the dialog, so after approving, rerun the whole page to close it.
    if actions.button("Approve deal", key="approve_confirm", type="primary", icon=":material/task_alt:",
                      disabled=bool(summary["open"])):
        _do_approve(deal["id"])
        st.rerun()
    if actions.button("Cancel", key="approve_cancel"):
        _close()
        st.rerun()


def _reopen(deal_id):
    try:
        corrections.reopen(deal_id, st.session_state.get("reopen_reason", ""), st.session_state.user["full_name"])
        st.session_state.edit_result = {"kind": "success", "text": "Reopened for changes. The reason is in the Activity timeline."}
        st.session_state.pop("reopen_open", None)
    except ValueError as exc:
        st.session_state.edit_result = {"kind": "warning", "text": str(exc)}


def banner(deal):
    if deal["status"] == "Approved":
        who = deal.get("approved_by") or "a person"
        when = (deal.get("approved_at") or "")[:10]
        style.html(style.banner("clear", f"Approved by {who}" + (f" on {when}" if when else ""),
                                footer="Values, flags and undo are locked. Reopen for changes if something needs fixing."))


def panel(deal, flags):
    summary = corrections.approval_summary(deal["id"])
    resolved, total = total_resolved(summary), summary["total_flags"]
    approved = deal["status"] == "Approved"
    draft = queries.latest_draft(deal["id"])
    with st.container(border=True, key="card_approval"):
        style.html('<div class="card-title">Approval</div>')
        checks = [
            (resolved == total, f"Flags resolved: {resolved} of {total}"),
            (True, f"Edits made: {len(summary['edits'])}"),
            (bool(draft), f"Draft narrative: {draft['status'] if draft else 'no draft yet'}"),
        ]
        style.html('<ul class="checklist">' + "".join(
            f'<li class="{"done" if ok else "todo"}">{escape(text)}</li>' for ok, text in checks) + "</ul>")
        if approved:
            st.caption(f"Approved by {deal.get('approved_by') or 'a person'}. Locked.")
            if st.session_state.get("reopen_open"):
                st.text_area("Why reopen it? (required)", key="reopen_reason", height=68)
                actions = st.container(horizontal=True)
                actions.button("Reopen", key="reopen_confirm", type="primary", icon=":material/lock_open:",
                               disabled=not st.session_state.get("reopen_reason", "").strip(), on_click=_reopen, args=(deal["id"],))
                actions.button("Cancel", key="reopen_cancel", on_click=lambda: st.session_state.pop("reopen_open", None))
            else:
                st.button("Reopen for changes", key="reopen_start", icon=":material/lock_open:", width="stretch",
                          on_click=lambda: st.session_state.update(reopen_open=True))
        else:
            st.button("Review and approve", key="approve_start", type="primary", icon=":material/task_alt:", width="stretch",
                      disabled=resolved < total, on_click=nav.open_dialog, args=(DIALOG,),
                      help="Unlocks when every flag is resolved." if resolved < total else None)
            if resolved < total:
                st.caption("Locked until every flag is confirmed or corrected.")
    if nav.dialog_is_open(DIALOG) and not approved:
        _dialog(deal)


def total_resolved(summary):
    return len(summary["confirmed"]) + len(summary["corrected"])
