"""One decision card per flag: fix the value or confirm it is right. Resolved flags stay visible."""

from html import escape

import streamlit as st

from app import style
from app.views import editing
from services import corrections, metrics


def _open(flag_id, panel):
    st.session_state.open_panel = (flag_id, panel)


def _confirm(flag_id, key):
    reason, note = st.session_state.get(f"{key}_reason"), st.session_state.get(f"{key}_note", "")
    try:
        corrections.confirm_flag(flag_id, reason, note, st.session_state.user["full_name"])
    except (corrections.Locked, ValueError) as exc:
        st.session_state.edit_result = {"kind": "warning", "text": str(exc)}
        return
    st.session_state.edit_result = {"kind": "success", "text": "Confirmed. The flag stays visible, marked as reviewed. No data was changed."}
    st.session_state.pop("open_panel", None)


def _numbers(flag):
    actual = f'<span class="num">{escape(str(flag["actual_value"]))}</span>' if flag["actual_value"] is not None else "empty"
    return f'<div class="flag-numbers">Value: {actual} · Limit: <span class="num">{escape(str(flag["threshold"]))}</span></div>'


def _resolved(flag):
    who, when = flag["resolved_by"] or "System", (flag["resolved_at"] or "")[:10]
    if flag["status"] == "confirmed":
        line = f"Reviewed: confirmed by {who}, {when}"
        detail = f'{flag["resolution_reason"]}: {flag["resolution_note"]}'
    else:
        line = f"Reviewed: corrected by {who}, {when}"
        detail = flag["resolution_reason"] or ""
    with st.container(border=True, key=f"flagcard_{flag['status']}_{flag['id']}"):
        style.html(f'<div class="flag-head"><span class="flag-title">Unit {escape(flag["unit_number"] or "(no ID)")} · '
                   f'{escape(metrics.rule_name(flag["rule"]))}</span><span class="pill approved">{escape(line)}</span></div>'
                   f'<div class="flag-message">{escape(flag["message"])}</div><div class="flag-detail">{escape(detail)}</div>')


def _confirm_panel(flag, locked):
    key = f"confirm_{flag['id']}"
    st.pills("Why is it correct?", corrections.CONFIRM_REASONS, key=f"{key}_reason", disabled=locked)
    st.text_area("Short note (required)", key=f"{key}_note", height=68, disabled=locked,
                 placeholder="For example: checked the signed lease; the higher rent is a lab fit-out premium.")
    ready = bool(st.session_state.get(f"{key}_reason")) and bool(st.session_state.get(f"{key}_note", "").strip())
    actions = st.container(horizontal=True)
    actions.button("Confirm", key=f"{key}_go", type="primary", icon=":material/verified:", disabled=locked or not ready,
                   on_click=_confirm, args=(flag["id"], key))
    actions.button("Cancel", key=f"{key}_cancel", on_click=lambda: st.session_state.pop("open_panel", None))
    st.caption("Confirming never changes the data. The flag stays visible, marked as reviewed.")


def _fix_panel(deal, flag, units, locked, ai_panel=None):
    unit = next((u for u in units if u["id"] == flag["rent_roll_unit_id"]), None)
    if unit is None:
        st.warning("The unit for this flag is no longer in the rent roll.")
        return
    if ai_panel:
        ai_panel(deal, flag, unit, locked)
    st.markdown("**Or change the values yourself**")
    editing.render(deal, unit, f"fix_{flag['id']}", locked=locked)


def render(deal, flags, units, locked, ai_panel=None):
    open_flags = [f for f in flags if f["status"] == "open"]
    resolved = [f for f in flags if f["status"] != "open"]
    if not flags:
        style.html(style.banner("clear", "No anomalies found", footer="Every validation rule passed for this rent roll."))
        return
    if open_flags:
        count = len(open_flags)
        style.section_title(f"{count} flag{'s' if count != 1 else ''} to resolve")
    else:
        style.html(style.banner("clear", "Every flag is resolved", footer="Resolved flags stay listed below, with who decided and why."))
    panel = st.session_state.get("open_panel")
    for flag in open_flags:
        with st.container(border=True, key=f"flagcard_open_{flag['id']}"):
            style.html(f'<div class="flag-head"><span class="flag-title">Unit {escape(flag["unit_number"] or "(no ID)")} · '
                       f'{escape(metrics.rule_name(flag["rule"]))}</span><span class="pill flag">Open</span></div>'
                       f'<div class="flag-message">{escape(flag["message"])}</div>{_numbers(flag)}'
                       f'<div class="flag-detail">Rule: {escape(flag["rule"])}</div>')
            choices = st.container(horizontal=True, key=f"flag_choices_{flag['id']}")
            choices.button("This is wrong - fix it", key=f"fix_btn_{flag['id']}", icon=":material/build:", disabled=locked,
                           on_click=_open, args=(flag["id"], "fix"))
            choices.button("This is correct - confirm it", key=f"confirm_btn_{flag['id']}", icon=":material/verified:",
                           disabled=locked, on_click=_open, args=(flag["id"], "confirm"))
            if panel == (flag["id"], "fix"):
                _fix_panel(deal, flag, units, locked, ai_panel)
            elif panel == (flag["id"], "confirm"):
                _confirm_panel(flag, locked)
    if resolved:
        style.section_title(f"Resolved ({len(resolved)})")
        for flag in resolved:
            _resolved(flag)
    if locked:
        st.caption("This deal is approved, so flags and values are locked. Reopen it to make changes.")
