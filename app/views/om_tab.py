"""The deal's OM tab: how complete the Offering Memorandum is, what is missing, what is waiting for a
person's approval, and how every number was calculated. Showing it never writes; Approve does.
"""

from html import escape
from pathlib import Path

import streamlit as st

from app import om_status, queries, style
from services import om_engine, om_export, om_slots

STATUS_LABELS = {"empty": "Missing", "auto-filled": "Auto-filled", "ai-draft": "AI draft",
                 "broker-provided": "From you", "approved": "Approved"}
STATUS_PILLS = {"empty": "flag", "auto-filled": "needs-review", "ai-draft": "needs-review",
                "broker-provided": "needs-review", "approved": "approved"}
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
SOURCE_LABELS = {"document_field": "From the deal's documents", "calculated": "Calculated", "broker_input": "Broker input",
                 "broker_photo": "Broker photo", "ai_text": "AI draft", "research": "Research", "fixed": "Fixed wording"}


def _user():
    return (st.session_state.get("user") or {}).get("full_name", "Broker")


def completion_bar_html(state):
    """Two-tone bar: approved (solid) and filled but waiting for approval (light), one segment per section."""
    approved, waiting, done, filled, total = state.completion()
    segments = []
    for section in state.template.sections:
        s_approved, s_waiting, s_done, s_filled, s_total = state.completion(section["id"])
        segments.append(
            f'<div class="om-seg" title="{escape(section["title"])}: {s_done} of {s_total} approved, {s_filled} waiting">'
            f'<div class="om-seg-track"><span class="om-fill approved {state.colour}" style="width:{s_approved}%"></span>'
            f'<span class="om-fill waiting" style="width:{s_waiting}%"></span></div>'
            f'<div class="om-seg-label">{escape(section["number"])} {escape(section["title"])}<b>{s_approved}%</b></div></div>')
    return (f'<div class="om-head"><div class="om-percent {state.colour}">{approved}%</div>'
            f'<div class="om-head-text"><div class="om-head-title">Offering memorandum</div>'
            f'<div class="om-head-note">{done} of {total} required items approved · {filled} filled and waiting for your approval · '
            f'{len(state.required_missing())} missing</div></div></div>'
            f'<div class="om-bar">{"".join(segments)}</div>'
            '<div class="om-legend"><span><i class="solid"></i>Approved</span><span><i class="light"></i>Filled, waiting for approval</span>'
            '<span><i class="none"></i>Missing</span></div>')


def source_text(slot_state):
    source = slot_state.source or {}
    label = SOURCE_LABELS.get(source.get("kind"), "")
    detail = source.get("detail", "")
    if source.get("approved_by"):
        detail = f"{detail} · approved by {source['approved_by']}, {source.get('approved_at', '')}".strip(" ·")
    return f"{label}: {detail}" if label and detail else label or detail


def _missing(state):
    items = state.missing()
    style.section_title(f"Missing ({len(items)})")
    if not items:
        style.html('<div class="om-empty">Nothing is missing.</div>')
        return
    rows = []
    for item in items:
        need = f'<div class="om-need">Still needs: {escape("; ".join(item.needs))}</div>' if item.needs else ""
        slides = ", ".join(str(n) for n in item.slides)
        rows.append(
            f'<div class="om-item {"required" if item.slot.required else "optional"}">'
            f'<div class="om-item-head"><span class="om-item-what">{escape(item.slot.label)}</span>'
            f'{style.pill("Required" if item.slot.required else "Optional", "flag" if item.slot.required else "other")}'
            f'<span class="om-priority {item.slot.priority}">{item.slot.priority.title()} priority</span></div>'
            f'<div class="om-item-why">{escape(item.slot.why)}</div>{need}'
            f'<div class="om-item-meta">Slide {slides} · Who can answer: {escape(om_engine.who_can_answer(item))}</div></div>')
    style.html("".join(rows))


def _how(slot_state):
    calc = slot_state.calc
    if calc is None or not calc.formula:
        return
    label = "How is this calculated?" if slot_state.source.get("kind") == "calculated" else "Where does this come from?"
    with st.expander(label):
        st.markdown(f"**{calc.formula}**")
        for step in calc.steps:
            st.markdown(f"- {step}")


def _waiting(state, deal_id):
    items = state.waiting()
    style.section_title(f"Waiting for your approval ({len(items)})")
    if not items:
        style.html('<div class="om-empty">Nothing is waiting for approval.</div>')
        return
    for item in items:
        with st.container(key=f"om_wait_{item.slot.id.replace('.', '_')}"):
            note = f'<div class="om-need">{escape(item.note)}</div>' if item.note else ""
            value = item.display if item.slot.type != "table" else f"{item.display} (table)"
            style.html(f'<div class="om-item-head"><span class="om-item-what">{escape(item.slot.label)}</span>'
                       f'{style.pill(STATUS_LABELS[item.status], STATUS_PILLS[item.status])}</div>'
                       f'<div class="om-value">{escape(str(value))}</div>'
                       f'<div class="om-source">{escape(source_text(item))}</div>{note}')
            _how(item)
            if st.button("Approve", key=f"om_approve_{item.slot.id.replace('.', '_')}", icon=":material/check:"):
                om_slots.approve(deal_id, [item], _user())
                st.rerun()


def _approved(state):
    items = [s for s in state.slots.values() if s.approved and not s.slot.fixed]
    if not items:
        return
    with st.expander(f"Approved ({len(items)})"):
        for item in items:
            style.html(f'<div class="om-approved"><b>{escape(item.slot.label)}</b>: {escape(item.display)}'
                       f'<div class="om-source">{escape(source_text(item))}</div></div>')
            _how(item)


def _download(path, label, mime, key):
    if path and Path(path).exists():
        st.download_button(label, Path(path).read_bytes(), file_name=Path(path).name, mime=mime, key=key,
                           icon=":material/download:")


def _export(state, deal):
    style.section_title("Export")
    blockers = om_export.final_blockers(state)
    st.caption("PowerPoint is the master file; the PDF is made from it. A draft always works: it carries the DRAFT mark "
               "and a red MISSING box for anything not filled in. No AI is used (0 Gemini requests).")
    draft_col, final_col = st.columns(2)
    kind = None
    with draft_col:
        if st.button("Export draft", key="om_export_draft", icon=":material/description:", width="stretch"):
            kind = "draft"
    with final_col:
        if st.button("Export client-ready", key="om_export_final", icon=":material/verified:", width="stretch",
                     disabled=bool(blockers), type="primary"):
            kind = "final"
    if blockers:
        st.caption(f"Client-ready export unlocks at 100% approved ({len(blockers)} item{'s' if len(blockers) != 1 else ''} "
                   "still missing or waiting for approval).")
    if kind:
        with st.spinner("Building the PowerPoint and the PDF..."):
            result = om_export.export(deal["id"], queries.om_facts(deal["id"]), kind, _user())
        st.session_state[f"om_export_{deal['id']}"] = result
    result = st.session_state.get(f"om_export_{deal['id']}")
    if result:
        st.success(f"Version {result['version']} ({result['kind_label']}), "
                   f"{result['slides']} slides, {result['completion']}% approved.")
        left, right = st.columns(2)
        with left:
            _download(result["pptx"], "PowerPoint (.pptx)", PPTX_MIME, "om_dl_pptx")
        with right:
            _download(result["pdf"], "PDF", "application/pdf", "om_dl_pdf")
        if result["pdf_error"]:
            st.warning(result["pdf_error"])


def render(deal):
    state = om_status.state(deal["id"])
    style.html(completion_bar_html(state))
    count, (low, high) = len(state.slides), state.template.slide_limits
    if not low <= count <= high:
        st.warning(f"The OM would have {count} slides, outside the usual {low}-{high}.")
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        _missing(state)
    with right:
        _export(state, deal)
        _waiting(state, deal["id"])
        _approved(state)
    st.caption(f"{count} slides from the template '{state.template.name}'. Numbers are calculated in code from this deal's "
               "data; the AI never writes them. Nothing counts as complete until a person approves it.")
