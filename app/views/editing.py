"""The edit form used everywhere a person changes a value: pick values, give a reason, see the
before/after (including recomputed fields), then save. Nothing is saved before Save is clicked."""

import streamlit as st

from html import escape

from app import style
from services import corrections


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def show(value):
    return corrections._show(value)


def preview_table(changes):
    rows = "".join(
        f'<tr class="{"derived" if c["derived"] else ""}"><td>{c["label"]}</td><td>{escape(show(c["old"]))}</td>'
        f'<td>{escape(show(c["new"]))}</td><td>{escape(c["how"] or "Your change")}</td></tr>'
        for c in changes)
    return ('<table class="preview"><thead><tr><th>Field</th><th>Before</th><th>After</th><th>Why it changes</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>")


def _clear(key):
    """Forget the form's inputs and close it (including a cell picked in the Extracted fields table)."""
    for name in list(st.session_state):
        if name.startswith(f"{key}_"):
            del st.session_state[name]
    st.session_state["fields_table"] = {"selection": {"rows": [], "columns": [], "cells": []}}


def _save(deal, unit, key, changes, reason, source):
    user = st.session_state.user["full_name"]
    try:
        result = corrections.apply(deal["id"], unit["id"], changes, reason, user, source)
    except (corrections.Locked, ValueError) as exc:
        st.session_state.edit_result = {"kind": "warning", "text": str(exc)}
        return
    lines = [f"Flag cleared: {m}" for m in result["cleared"]] + [f"Still flagged: {m}" for m in result["still"]]
    lines += [f"New flag: {m}" for m in result["new"]]
    kind = "warning" if result["still"] or result["new"] else "success"
    st.session_state.edit_result = {"kind": kind, "text": "  \n".join(["Saved."] + lines) if lines else "Saved. No flags on this unit."}
    _clear(key)
    st.session_state.pop("open_panel", None)
    st.session_state.pop("cell_edit", None)


def render(deal, unit, key, fields=None, locked=False, source=corrections.MANUAL, prefill=None, reason_prefill=""):
    """The edit form for one unit. fields limits which fields are shown (default: all editable ones)."""
    fields = fields or list(corrections.EDITABLE)
    prefill = prefill or {}
    values = {}
    columns = st.columns(min(len(fields), 3))
    for index, field in enumerate(fields):
        label = corrections.EDITABLE[field][0]
        default = _text(prefill.get(field, unit.get(field)))
        values[field] = columns[index % len(columns)].text_input(label, value=default, key=f"{key}_{field}", disabled=locked)
    reason = st.text_area("Why are you changing it? (required)", value=reason_prefill, key=f"{key}_reason", height=68, disabled=locked,
                          placeholder="For example: the lease abstract shows 3,200 SF at $5,421.33 a month.")
    changes, errors = corrections.plan(unit, values)
    for error in errors:
        st.error(error)
    if changes and not errors:
        st.markdown("**Before and after** (nothing is saved until you click Save)")
        style.html(preview_table(changes))
        if any(c["derived"] for c in changes):
            st.caption("Recomputed rows are worked out in code from your change, and are saved and undone with it.")
    can_save = bool(changes) and not errors and bool(reason.strip()) and not locked
    if changes and not reason.strip():
        st.caption("Add a reason to save.")
    actions = st.container(horizontal=True)
    actions.button("Save changes", key=f"{key}_save", type="primary", icon=":material/save:", disabled=not can_save,
                   on_click=_save, args=(deal, unit, key, changes, reason, source))
    actions.button("Cancel", key=f"{key}_cancel", on_click=_cancel, args=(key,))
    return changes


def _cancel(key):
    _clear(key)
    st.session_state.pop("open_panel", None)
    st.session_state.pop("cell_edit", None)
