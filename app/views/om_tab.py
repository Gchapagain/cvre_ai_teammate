"""The deal's OM tab: how complete the Offering Memorandum is, the guided interview, the slides, photos,
pricing and assumptions, client questions and the export. Showing it never writes; only a person's clicks do.

Gemini is used only on these buttons, one request each: Let the AI read my answer, Draft all text,
Propose assumptions, Make it friendlier, Read the reply, Read the document; Sort my photos uses one per
8 photos. Everything else (questions, the client message, numbers, placing photos, exports) is code only.
"""

import logging
from html import escape
from pathlib import Path

import streamlit as st

from app import nav, om_status, queries, style
from app.views import om_work
from services import gemini, om_engine, om_export, om_interview, om_slots

log = logging.getLogger(__name__)

STATUS_LABELS = {"empty": "Missing", "auto-filled": "Auto-filled", "ai-draft": "AI draft · check it",
                 "broker-provided": "From you", "approved": "Approved"}
STATUS_PILLS = {"empty": "flag", "auto-filled": "needs-review", "ai-draft": "needs-review",
                "broker-provided": "needs-review", "approved": "approved"}
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
SOURCE_LABELS = {"document_field": "From the deal's documents", "calculated": "Calculated", "broker_input": "Broker input",
                 "broker_photo": "Broker photo", "ai_text": "AI draft", "research": "Research", "fixed": "Fixed wording",
                 "client_reply": "Client reply", "client_document": "Client document"}
VIEWS = ["Checklist", "Slides", "Photos", "Pricing", "Client", "Export"]
DOT = {"green": "🟢", "amber": "🟠", "red": "🔴"}


def _user():
    return (st.session_state.get("user") or {}).get("full_name", "Broker")


def _email():
    return (st.session_state.get("user") or {}).get("email")


def _key(slot_id):
    return slot_id.replace(".", "_")


def ai_error(exc):
    """A plain sentence for any problem reaching the AI."""
    if isinstance(exc, gemini.GeminiQuotaError):
        return f"The AI's daily quota is used up. {exc} You can still type everything yourself."
    if isinstance(exc, gemini.GeminiBusyError):
        return "The AI is busy or rate-limited at the moment. Try again in a minute."
    if isinstance(exc, gemini.RateLimited):
        return str(exc)
    if isinstance(exc, gemini.GeminiError):
        return f"The AI couldn't do this just now. {exc}"
    log.exception("OM AI action failed", exc_info=exc)
    return "The AI couldn't do this just now. Nothing was changed."


def flash(kind, text):
    st.session_state.om_flash = (kind, text)


def _show_flash():
    message = st.session_state.pop("om_flash", None)
    if message:
        getattr(st, message[0])(message[1])


# ---------- header ----------

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


def time_line(deal_id):
    minutes, sessions = om_engine.time_spent(queries.om_events(deal_id))
    if not sessions:
        return "OM time so far: nothing yet."
    return (f"OM time so far: about {minutes} min over {sessions} session{'s' if sessions != 1 else ''} "
            "(worked out from your clicks on this tab; not a time-saved figure).")


# ---------- checklist ----------

def slides_text(item):
    if not item.slides:
        return "Optional slide, added only when this is filled"
    return f"Slide{'s' if len(item.slides) > 1 else ''} {', '.join(str(n) for n in item.slides)}"


def _how(slot_state):
    calc = slot_state.calc
    if calc is None or not calc.formula:
        return
    label = "How is this calculated?" if slot_state.source.get("kind") == "calculated" else "Where does this come from?"
    with st.expander(label):
        st.markdown(f"**{calc.formula}**")
        for step in calc.steps:
            st.markdown(f"- {step}")


def _missing(state):
    items = state.missing()
    style.section_title(f"Missing ({len(items)})")
    if not items:
        style.html('<div class="om-empty">Nothing is missing.</div>')
        return
    rows = []
    for item in items:
        need = f'<div class="om-need">Still needs: {escape("; ".join(item.needs))}</div>' if item.needs else ""
        slides = slides_text(item)
        rows.append(
            f'<div class="om-item {"required" if item.slot.required else "optional"}">'
            f'<div class="om-item-head"><span class="om-item-what">{escape(item.slot.label)}</span>'
            f'{style.pill("Required" if item.slot.required else "Optional", "flag" if item.slot.required else "other")}'
            f'<span class="om-priority {item.slot.priority}">{item.slot.priority.title()} priority</span></div>'
            f'<div class="om-item-why">{escape(item.slot.why)}</div>{need}'
            f'<div class="om-item-meta">{slides} · Who can answer: {escape(om_engine.who_can_answer(item))}</div></div>')
    style.html("".join(rows))


def _editable(item):
    return item.slot.type in ("text", "bullets") and not (item.slot.auto or "").startswith("calc.")


def _edit_value(deal_id, item):
    with st.popover("Change", icon=":material/edit:", key=f"om_change_{_key(item.slot.id)}"):
        current = "\n".join(item.value) if isinstance(item.value, list) else str(item.value or "")
        hint = "One point per line." if item.slot.type == "bullets" else None
        text = st.text_area(item.slot.label, current, key=f"om_change_text_{_key(item.slot.id)}", help=hint)
        if st.button("Save", key=f"om_change_save_{_key(item.slot.id)}", type="primary"):
            try:
                om_slots.set_value(deal_id, item.slot.id, text, _user())
            except om_slots.InvalidValue as error:
                st.error(str(error))
            else:
                flash("success", f"{item.slot.label} saved. It waits for your approval.")
                st.rerun()


def _waiting(state, deal_id):
    items = state.waiting()
    style.section_title(f"Waiting for your approval ({len(items)})")
    if not items:
        style.html('<div class="om-empty">Nothing is waiting for approval.</div>')
        return
    for item in items:
        with st.container(key=f"om_wait_{_key(item.slot.id)}"):
            note = f'<div class="om-need">{escape(item.note)}</div>' if item.note else ""
            value = item.display if item.slot.type != "table" else f"{item.display} (table)"
            style.html(f'<div class="om-item-head"><span class="om-item-what">{escape(item.slot.label)}</span>'
                       f'{style.pill(STATUS_LABELS[item.status], STATUS_PILLS[item.status])}</div>'
                       f'<div class="om-value">{escape(str(value))}</div>'
                       f'<div class="om-source">{escape(source_text(item))}</div>{note}')
            _how(item)
            with st.container(horizontal=True):
                if st.button("Approve", key=f"om_approve_{_key(item.slot.id)}", icon=":material/check:"):
                    om_slots.approve(deal_id, [item], _user())
                    st.rerun()
                if _editable(item):
                    _edit_value(deal_id, item)


def _approve_sections(state, deal_id):
    """One expander per section with items waiting: a summary, then one confirm click approves them all."""
    sections = [(section, [s for s in state.waiting() if s.section == section["id"]]) for section in state.template.sections]
    sections = [(section, items) for section, items in sections if items]
    if not sections:
        return
    style.section_title("Approve a section")
    for section, items in sections:
        with st.expander(f"{section['number']} {section['title']}: approve {len(items)} item{'s' if len(items) != 1 else ''}"):
            for item in items:
                style.html(f'<div class="om-approved"><b>{escape(item.slot.label)}</b>: {escape(item.display[:300])}'
                           f'<div class="om-source">{escape(source_text(item))}</div></div>')
            st.caption("Check every value above. Approving makes them count toward completion; you can take an approval back.")
            if st.button(f"Approve these {len(items)}", key=f"om_approve_section_{section['id']}", type="primary",
                         icon=":material/done_all:"):
                om_slots.approve(deal_id, items, _user())
                flash("success", f"{section['title']}: {len(items)} item{'s' if len(items) != 1 else ''} approved.")
                st.rerun()


def _approved(state, deal_id):
    items = [s for s in state.slots.values() if s.approved and not s.slot.fixed]
    if not items:
        return
    with st.expander(f"Approved ({len(items)})"):
        for item in items:
            style.html(f'<div class="om-approved"><b>{escape(item.slot.label)}</b>: {escape(item.display[:300])}'
                       f'<div class="om-source">{escape(source_text(item))}</div></div>')
            if st.button("Take approval back", key=f"om_unapprove_{_key(item.slot.id)}", type="tertiary"):
                om_slots.unapprove(deal_id, item.slot.id, _user())
                st.rerun()


def _draft_text(deal, state):
    from services import om_drafting
    with st.container(key="om_draft_box"):
        style.html('<span class="ai-label">AI · 1 request</span>')
        st.caption("Drafts The Offering, the highlights and (only from research you accepted) the location, from this deal's "
                   "data. It never touches your own text or anything approved, and every number is checked.")
        if st.button("Draft all text", key="om_draft_all", icon=":material/auto_awesome:"):
            with st.spinner("Drafting..."):
                try:
                    result = om_drafting.draft_all_text(deal["id"], queries.om_facts(deal["id"], _email()), state, _user())
                except Exception as exc:
                    flash("error", ai_error(exc))
                else:
                    lines = [f"Drafted: {', '.join(result['saved'])}." if result["saved"] else "Nothing new was drafted."]
                    lines += result["dropped"] + result["questions"]
                    if result["skipped"]:
                        lines.append(f"Left as they are (yours or approved): {', '.join(result['skipped'])}.")
                    flash("info", " ".join(lines))
            st.rerun()


def _interview(state, deal):
    """'Help me finish the OM': one question at a time, from the template (no AI unless asked)."""
    skipped = {q["slot_id"] for q in queries.om_questions(deal["id"]) if q["audience"] == "broker" and q["status"] == "skipped"}
    questions = om_interview.questions(state, skipped)
    with st.container(key="om_interview"):
        style.section_title("Help me finish the OM")
        if not questions:
            st.success("Every item has a value. Approve what is waiting, then export.")
            return
        index = min(st.session_state.get("om_q_index", 0), len(questions) - 1)
        question = questions[index]
        slot = question.slot
        style.html(f'<div class="om-q-count">Question {index + 1} of {len(questions)}'
                   f'{" · skipped earlier" if question.skipped else ""}</div>'
                   f'<div class="om-q-label">{escape(slot.label)}</div>'
                   f'<div class="om-q-text">{escape(question.text)}</div>'
                   f'<div class="om-item-meta">Why: {escape(slot.why)} · {slides_text(question.state)}</div>')
        if question.kind == "answer":
            _answer_box(deal["id"], question)
        elif question.kind == "photo":
            om_work.photo_answer(deal["id"], question.state, _user())
        elif question.kind == "pricing":
            st.info("This is set on the Pricing view: the price and the cash-flow assumptions.")
            st.button("Open Pricing", key="om_q_pricing", on_click=_go_view, args=("Pricing",))
        elif question.kind == "settings":
            st.info("Your title and phone come from your profile.")
            st.button("Open Settings", key="om_q_settings", on_click=nav.open_settings)
        else:
            st.info("This is calculated from the deal's documents. Still needs: " + "; ".join(question.state.needs))
        with st.container(horizontal=True, key="om_q_nav"):
            st.button("Previous", key="om_q_prev", disabled=index == 0, on_click=_move, args=(index - 1,),
                      icon=":material/arrow_back:")
            if question.can_ask_client:
                st.button("Ask the client", key="om_q_client", icon=":material/forward_to_inbox:",
                          on_click=_add_to_client, args=(deal["id"], slot.id))
            if st.button("Skip", key="om_q_skip", icon=":material/skip_next:"):
                om_interview.skip(deal["id"], slot.id, question.text, _user())
                _move(index)
                st.rerun()
            st.button("Next", key="om_q_next", disabled=index >= len(questions) - 1, on_click=_move, args=(index + 1,),
                      icon=":material/arrow_forward:")


def _move(index):
    st.session_state.om_q_index = max(0, index)
    st.session_state.pop("om_ai_answer", None)


def _go_view(view):
    st.session_state.om_view = view


def _add_to_client(deal_id, slot_id):
    basket = st.session_state.setdefault(f"om_client_basket_{deal_id}", [])
    if slot_id not in basket:
        basket.append(slot_id)
    flash("info", "Added to the client questions. Open the Client view to see the message.")


def _answer_box(deal_id, question):
    slot = question.slot
    hint = "One point per line." if slot.type == "bullets" else None
    text = st.text_area("Your answer", key=f"om_answer_{_key(slot.id)}", help=hint, height=110)
    with st.container(horizontal=True):
        if st.button("Save answer", key="om_q_save", type="primary", icon=":material/save:", disabled=not text.strip()):
            try:
                om_slots.set_value(deal_id, slot.id, text, _user())
            except om_slots.InvalidValue as error:
                st.error(str(error))
            else:
                om_interview.mark_answered(deal_id, [slot.id])
                flash("success", f"{slot.label} saved. It waits for your approval.")
                st.session_state.pop("om_ai_answer", None)
                st.rerun()
        if st.button("Let the AI read my answer", key="om_q_ai", icon=":material/auto_awesome:", disabled=not text.strip(),
                     help="1 AI request. Turns what you wrote into this item's format; nothing is saved until you click Use it."):
            try:
                st.session_state.om_ai_answer = (slot.id, om_interview.read_answer(slot, text))
            except om_slots.InvalidValue as error:
                st.warning(str(error))
            except Exception as exc:
                st.error(ai_error(exc))
    proposal = st.session_state.get("om_ai_answer")
    if proposal and proposal[0] == slot.id:
        value = proposal[1]
        with st.container(key="om_ai_answer_box"):
            style.html('<span class="ai-label">AI read your answer</span>'
                       f'<div class="om-value">{escape(om_interview.om_slots_display(value))}</div>')
            with st.container(horizontal=True):
                if st.button("Use it", key="om_ai_answer_use", type="primary"):
                    om_slots.set_value(deal_id, slot.id, value, _user(), source={
                        "kind": "broker_input", "detail": f"Your answer, put in format by the AI; {_user()} clicked Use it"})
                    om_interview.mark_answered(deal_id, [slot.id])
                    st.session_state.pop("om_ai_answer", None)
                    flash("success", f"{slot.label} saved. It waits for your approval.")
                    st.rerun()
                if st.button("Cancel", key="om_ai_answer_cancel"):
                    st.session_state.pop("om_ai_answer", None)
                    st.rerun()


def _checklist(state, deal):
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        _interview(state, deal)
        _missing(state)
    with right:
        _draft_text(deal, state)
        _approve_sections(state, deal["id"])
        _waiting(state, deal["id"])
        _approved(state, deal["id"])


# ---------- slides ----------

def _slides(state, deal):
    facts = queries.om_facts(deal["id"], _email())
    left, right = st.columns([0.9, 2], gap="large")
    selected = st.session_state.get("om_slide", state.slides[0][1].id)
    with left:
        style.section_title(f"Slides ({len(state.slides)})")
        st.caption("🟢 approved · 🟠 filled, waiting for approval · 🔴 something required is missing")
        for number, slide in state.slides:
            colour = state.slide_status(slide)
            st.button(f"{DOT[colour]} {number}. {slide.title}", key=f"om_slide_{slide.id}", type="tertiary",
                      on_click=st.session_state.update, kwargs={"om_slide": slide.id})
    slide = next((s for _, s in state.slides if s.id == selected), state.slides[0][1])
    with right:
        style.section_title(slide.title)
        _preview(state, facts, slide)
        for slot_id in slide.slots:
            item = state.slots[slot_id]
            if item.slot.fixed:
                continue
            style.html(f'<div class="om-approved"><b>{escape(item.slot.label)}</b> '
                       f'{style.pill(STATUS_LABELS[item.status], STATUS_PILLS[item.status])} '
                       f'{escape((item.display or "; ".join(item.needs))[:200])}</div>')


def _preview(state, facts, slide):
    if not om_export.soffice_path():
        st.info("The slide preview needs LibreOffice, which is not installed here. The list below shows what is on the slide.")
        return
    pdf = om_export.cached_preview(state, facts)
    if pdf is None:
        if st.button("Show preview", key="om_preview_make", icon=":material/visibility:",
                     help="Draws the OM as a draft PDF (a few seconds). No AI is used."):
            with st.spinner("Drawing the slides..."):
                try:
                    om_export.preview_pdf(state, facts)
                except om_export.ExportError as error:
                    st.warning(str(error))
            st.rerun()
        st.caption("Draft preview: it shows the DRAFT mark and a red box for anything missing.")
        return
    pages = om_export.page_images(pdf, zoom=1.4)
    page = om_export.page_of(state, slide.id)
    if page < len(pages):
        st.image(str(pages[page]), caption=f"Draft preview of page {page + 1}")


# ---------- export ----------

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
            result = om_export.export(deal["id"], queries.om_facts(deal["id"], _email()), kind, _user())
        st.session_state[f"om_export_{deal['id']}"] = result
    result = st.session_state.get(f"om_export_{deal['id']}")
    if result:
        st.success(f"Version {result['version']} ({result['kind_label']}), {result['slides']} slides, "
                   f"{result['completion']}% approved.")
        left, right = st.columns(2)
        with left:
            _download(result["pptx"], "PowerPoint (.pptx)", PPTX_MIME, "om_dl_pptx")
        with right:
            _download(result["pdf"], "PDF", "application/pdf", "om_dl_pdf")
        if result["pdf_error"]:
            st.warning(result["pdf_error"])
    _history(deal["id"])


def _history(deal_id):
    exports = queries.om_exports(deal_id)
    if not exports:
        return
    with st.expander(f"Earlier exports ({len({e['version'] for e in exports})})"):
        for row in exports:
            label = (f"v{row['version']} {'client-ready' if row['kind'] == 'final' else 'draft'} · {row['format'].upper()} · "
                     f"{row['completion']:.0f}% approved · {row['created_at']} UTC")
            path = row["file_path"]
            if path and Path(path).exists():
                _download(path, label, PPTX_MIME if row["format"] == "pptx" else "application/pdf", f"om_hist_{row['id']}")
            else:
                st.caption(f"{label} (the file is no longer on this server)")


# ---------- the tab ----------

def render(deal):
    state = om_status.state(deal["id"])
    style.html(completion_bar_html(state))
    count, (low, high) = len(state.slides), state.template.slide_limits
    if not low <= count <= high:
        st.warning(f"The OM would have {count} slides, outside the usual {low}-{high}.")
    st.caption(time_line(deal["id"]))
    view = st.segmented_control("OM view", VIEWS, key="om_view", label_visibility="collapsed") or "Checklist"
    _show_flash()
    if view == "Slides":
        _slides(state, deal)
    elif view == "Photos":
        om_work.photos(state, deal, _user())
    elif view == "Pricing":
        om_work.pricing(state, deal, _user(), _email())
    elif view == "Client":
        om_work.client(state, deal, _user())
    elif view == "Export":
        _export(state, deal)
    else:
        _checklist(state, deal)
    st.caption(f"{count} slides from the template '{state.template.name}'. Numbers are calculated in code from this deal's "
               "data; the AI never writes them. Nothing counts as complete until a person approves it.")
