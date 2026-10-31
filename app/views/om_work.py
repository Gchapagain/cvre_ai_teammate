"""The OM tab's working views: photos, pricing and assumptions, and client questions.

Every change happens on a person's click. AI buttons say how many requests they use.
"""

from html import escape

import streamlit as st

from app import queries, style
from services import om_assets, om_calc, om_interview, om_slots

KINDS = list(om_assets.KIND_NAMES)


def _tab():
    from app.views import om_tab  # here: om_tab imports this module
    return om_tab


# ---------- photos ----------

def photo_answer(deal_id, slot_state, user):
    """In the interview: upload photos straight onto this photo slot."""
    slot = slot_state.slot
    kinds = list(slot.photo_kinds)
    kind = st.selectbox("What do the photos show?", kinds, format_func=om_assets.KIND_NAMES.get, key=f"om_qphoto_kind_{slot.id}")
    files = st.file_uploader(f"Upload {slot.count} photo{'s' if slot.count != 1 else ''} (PNG, JPEG or WebP)",
                             type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True, key=f"om_qphoto_{slot.id}")
    st.caption("Photos come from you or the client. The AI cannot make aerials, maps or site plans.")
    if st.button("Add to this slide", key="om_qphoto_save", type="primary", disabled=not files):
        saved, problems = om_assets.add_photos(deal_id, [(f.name, f.getvalue()) for f in files], user, kind=kind,
                                               slot_id=slot.id)
        _tab().flash("warning" if problems else "success",
                     f"{len(saved)} photo(s) added." + (" " + " ".join(problems) if problems else ""))
        st.rerun()


def photos(state, deal, user):
    deal_id = deal["id"]
    rows = om_assets.assets(deal_id)
    om_assets.ensure_sample_files(rows)
    needs = om_assets.needs_summary(state)
    left, right = st.columns([1, 1.4], gap="large")
    with left:
        style.section_title("Still needed")
        if needs:
            style.html("".join(f'<div class="om-need">{escape(line)}</div>' for line in needs))
        else:
            st.success("Every required photo slot is filled.")
        style.section_title("Add photos")
        files = st.file_uploader("Photos (PNG, JPEG or WebP, up to 15 MB each)", type=["png", "jpg", "jpeg", "webp"],
                                 accept_multiple_files=True, key=f"om_photos_upload_{st.session_state.get('om_upload_round', 0)}")
        st.caption("Use photos you are free to share. They are resized and stored on this server only. "
                   "The AI cannot make aerials, maps or site plans: please upload them.")
        if st.button("Add photos", key="om_photos_add", type="primary", icon=":material/upload:", disabled=not files):
            saved, problems = om_assets.add_photos(deal_id, [(f.name, f.getvalue()) for f in files], user)
            st.session_state.om_upload_round = st.session_state.get("om_upload_round", 0) + 1
            _tab().flash("warning" if problems else "success",
                         f"{len(saved)} photo(s) added. Sort them, then place them." + (" " + " ".join(problems) if problems else ""))
            st.rerun()
        unsorted = [a for a in rows if not a["kind"]]
        if unsorted:
            requests = -(-len(unsorted) // om_assets.BATCH)
            style.html(f'<span class="ai-label">AI · {requests} request{"s" if requests != 1 else ""}</span>')
            if st.button(f"Sort my photos ({len(unsorted)})", key="om_photos_sort", icon=":material/auto_awesome:",
                         help="The AI looks at each photo and proposes what it shows. Nothing changes until you click Apply."):
                with st.spinner("Looking at the photos..."):
                    try:
                        st.session_state.om_sort = om_assets.sort_photos(deal_id)[0]
                    except Exception as exc:
                        st.error(_tab().ai_error(exc))
        _sort_proposals(deal_id, rows, user)
        if st.button("Place photos on the slides", key="om_photos_place", icon=":material/dashboard_customize:",
                     help="Fills empty photo slots with photos of the right kind (no AI)."):
            placed = om_assets.auto_place(deal_id, user)
            _tab().flash("success" if placed else "info",
                         f"{placed} photo(s) placed." if placed else "Nothing to place: sort photos first, or every slot is full.")
            st.rerun()
    with right:
        style.section_title(f"Photos ({len(rows)})")
        if not rows:
            st.caption("No photos yet.")
        columns = st.columns(3)
        for i, asset in enumerate(rows):
            with columns[i % 3]:
                _photo_card(deal_id, asset, state, user)


def _sort_proposals(deal_id, rows, user):
    proposals = st.session_state.get("om_sort")
    if not proposals:
        return
    names = {a["id"]: a.get("caption") or f"Photo {a['id']}" for a in rows}
    with st.container(key="om_sort_box"):
        style.html('<span class="ai-label">AI proposal: check before applying</span>')
        for p in proposals:
            st.markdown(f"- **{escape(names.get(p['asset_id'], str(p['asset_id'])))}**: {om_assets.KIND_NAMES[p['kind']]}"
                        f" ({escape(p['description'])})")
        with st.container(horizontal=True):
            if st.button("Apply", key="om_sort_apply", type="primary"):
                om_assets.apply_kinds(deal_id, proposals, user)
                st.session_state.pop("om_sort")
                st.rerun()
            if st.button("Cancel", key="om_sort_cancel"):
                st.session_state.pop("om_sort")
                st.rerun()


def _photo_card(deal_id, asset, state, user):
    path = om_assets.full_path(asset["file_path"])
    with st.container(key=f"om_photo_{asset['id']}"):
        if path.exists():
            st.image(str(path))
        place = state.slots[asset["slot_id"]].slot.label if asset["slot_id"] in state.slots else "Not placed"
        kind = om_assets.KIND_NAMES.get(asset["kind"], "Not sorted")
        sample = " · Sample illustration" if asset.get("sample") else ""
        st.caption(f"{kind} · {place}{sample}")
        with st.popover("Edit", icon=":material/tune:", key=f"om_photo_edit_{asset['id']}"):
            new_kind = st.selectbox("Shows", KINDS, index=KINDS.index(asset["kind"]) if asset["kind"] in KINDS else 0,
                                    format_func=om_assets.KIND_NAMES.get, key=f"om_photo_kind_{asset['id']}")
            slots = [None] + [s.slot.id for s in state.slots.values() if s.slot.type == "photo" and new_kind in s.slot.photo_kinds]
            current = asset["slot_id"] if asset["slot_id"] in slots else None
            target = st.selectbox("Slide", slots, index=slots.index(current),
                                  format_func=lambda s: "Not placed" if s is None else state.slots[s].slot.label,
                                  key=f"om_photo_slot_{asset['id']}")
            with st.container(horizontal=True):
                if st.button("Save", key=f"om_photo_save_{asset['id']}", type="primary"):
                    try:
                        if new_kind != asset["kind"]:
                            om_assets.set_kind(deal_id, asset["id"], new_kind, user)
                        if target != asset["slot_id"]:
                            om_assets.place(deal_id, asset["id"], target, user)
                    except ValueError as error:
                        st.error(str(error))
                    else:
                        st.rerun()
                if st.button("Remove", key=f"om_photo_remove_{asset['id']}"):
                    om_assets.remove(deal_id, asset["id"], user)
                    st.rerun()


# ---------- pricing and assumptions ----------

def pricing(state, deal, user, email):
    deal_id = deal["id"]
    facts = queries.om_facts(deal_id, email)
    left, right = st.columns([1, 1.3], gap="large")
    with left:
        _price(deal_id, state, user)
    with right:
        _assumptions(deal_id, facts, user)
    flow = state.slots.get("financial.cash_flow")
    if flow is not None and flow.calc is not None and flow.calc.ready:
        style.section_title("Cash flow from approved assumptions")
        header = ["In-place"] + [f"Year {n}" for n in range(1, om_calc.YEARS + 1)]
        table = {label: [f"{v:.1f}%" if label.endswith("%") else om_calc.money(v) for v in values]
                 for label, values in flow.calc.value}
        st.dataframe({"": list(table)} | {h: [row[i] for row in table.values()] for i, h in enumerate(header)},
                     hide_index=True, width="stretch")
    elif flow is not None:
        st.caption("Cash flow: still needs " + "; ".join(flow.needs))


def _price(deal_id, state, user):
    style.section_title("Asking price")
    slot_state = state.slots["financial.sale_price"]
    st.caption("Only you set the price. The AI never does. Price per SF and cap rates are calculated from it.")
    if slot_state.status != "empty":
        st.markdown(f"Current: **{om_calc.money(slot_state.value)}** · {_tab().STATUS_LABELS[slot_state.status]}")
    for row in queries.bov_values(deal_id)[:1]:
        st.info(f"From BOV, please confirm: {om_calc.money(row['value'])} ({row['metric']}). It is only a suggestion.")
        if st.button("Use the BOV value", key="om_price_bov"):
            st.session_state.om_price_text = f"{row['value']:,.0f}"
            st.rerun()
    text = st.text_input("Asking price", key="om_price_text", placeholder="for example 14,250,000 or $14.25M")
    if st.button("Save price", key="om_price_save", type="primary", disabled=not text.strip()):
        try:
            om_slots.set_value(deal_id, "financial.sale_price", text, user,
                               source={"kind": "broker_input", "detail": f"Entered by {user}"})
        except om_slots.InvalidValue as error:
            st.error(str(error))
        else:
            _tab().flash("success", "Price saved. Approve it on the Checklist when you are sure.")
            st.rerun()


def _assumption_value(key, value):
    kind = om_calc.ASSUMPTIONS[key][1]
    if kind == "percent_list":
        return ", ".join(f"{v:g}%" for v in value)
    return om_calc.money(value, True) if kind == "currency" else f"{value:g}%"


def _assumptions(deal_id, facts, user):
    from services import om_drafting
    style.section_title("Cash-flow assumptions")
    st.caption("The cash flow uses approved assumptions only. AI proposals are marked and count only once you approve them.")
    saved = facts.get("assumptions", {})
    missing = [k for k in om_calc.ASSUMPTIONS if saved.get(k, {}).get("status") != "approved"]
    if missing:
        style.html('<span class="ai-label">AI · 1 request</span>')
        if st.button("Propose assumptions", key="om_assume_ai", icon=":material/auto_awesome:",
                     help="The AI proposes the ones not approved yet, with a reason each. You approve or change each one."):
            with st.spinner("Proposing..."):
                try:
                    result = om_drafting.propose_assumptions(deal_id, facts, user)
                except Exception as exc:
                    _tab().flash("error", _tab().ai_error(exc))
                else:
                    _tab().flash("info", (f"Proposed: {', '.join(result['saved'])}." if result["saved"] else "Nothing proposed.")
                                 + (" " + " ".join(result["dropped"]) if result["dropped"] else ""))
            st.rerun()
    for key, (label, kind, help_text) in om_calc.ASSUMPTIONS.items():
        row = saved.get(key)
        with st.container(key=f"om_assumption_{key}"):
            if row:
                status = "Approved" if row["status"] == "approved" else "AI proposal" if row["source"].get("kind") == "ai_proposal" else "Proposed"
                pill = style.pill(status, "approved" if row["status"] == "approved" else "needs-review")
                style.html(f'<div class="om-item-head"><span class="om-item-what">{escape(label)}</span>{pill}</div>'
                           f'<div class="om-value">{escape(_assumption_value(key, row["value"]))}</div>'
                           f'<div class="om-source">{escape(row["source"].get("detail", ""))}</div>')
            else:
                style.html(f'<div class="om-item-head"><span class="om-item-what">{escape(label)}</span>'
                           f'{style.pill("Not set", "flag")}</div><div class="om-source">{escape(help_text)}</div>')
            with st.container(horizontal=True):
                if row and row["status"] == "proposed" and st.button("Approve", key=f"om_assume_ok_{key}", icon=":material/check:"):
                    om_slots.approve_assumption(deal_id, key, user)
                    st.rerun()
                with st.popover("Set it myself", key=f"om_assume_set_{key}"):
                    hint = "Five percentages, for example 90, 95, 95, 95, 95" if kind == "percent_list" else help_text
                    value = st.text_input(label, key=f"om_assume_text_{key}", help=hint)
                    if st.button("Save and approve", key=f"om_assume_save_{key}", type="primary", disabled=not value.strip()):
                        try:
                            om_slots.set_assumption(deal_id, key, value, user)
                        except om_slots.InvalidValue as error:
                            st.error(str(error))
                        else:
                            st.rerun()


# ---------- client questions ----------

def client(state, deal, user):
    deal_id = deal["id"]
    left, right = st.columns([1.2, 1], gap="large")
    with left:
        _client_message(state, deal, user)
    with right:
        _client_reply(state, deal_id, user)
        _client_document(state, deal_id, user)
        _open_questions(deal_id, state)


def _client_message(state, deal, user):
    style.section_title("Ask the client")
    askable = [s for s in state.missing() if s.slot.client_question and "client" in s.slot.answer_by]
    if not askable:
        st.caption("Nothing missing is something the client can answer.")
        return
    basket = st.session_state.get(f"om_client_basket_{deal['id']}") or [s.slot.id for s in askable if s.slot.required]
    ids = [s.slot.id for s in askable]
    chosen = st.multiselect("Questions to include", ids, default=[i for i in basket if i in ids],
                            format_func=lambda i: state.slots[i].slot.label, key=f"om_client_pick_{deal['id']}")
    client_name = st.text_input("Client's first name (optional)", key="om_client_name")
    items = [state.slots[i] for i in chosen]
    name = state.slots["property.name"].display or deal["name"]
    message = om_interview.client_message(name, items, user, client_name.strip() or None)
    friendly = st.session_state.get("om_friendly")
    if friendly and friendly[0] == message:
        message = friendly[1]
        style.html('<span class="ai-label">Reworded by AI · questions and numbers checked</span>')
    if not message:
        st.caption("Pick at least one question.")
        return
    st.caption("Copy the message and send it from your own email. The app never sends anything to a client.")
    st.code(message, language=None, wrap_lines=True)
    with st.container(horizontal=True):
        if st.button("Make it friendlier", key="om_client_ai", icon=":material/auto_awesome:", help="1 AI request."):
            try:
                original = om_interview.client_message(name, items, user, client_name.strip() or None)
                st.session_state.om_friendly = (original, om_interview.friendlier(original))
            except Exception as exc:
                st.error(_tab().ai_error(exc))
            else:
                st.rerun()
        if st.button("I sent it", key="om_client_sent", type="primary", icon=":material/mark_email_read:",
                     help="Records which questions went to the client, so their reply can be matched."):
            om_interview.save_client_questions(deal["id"], items, message, user)
            st.session_state.pop(f"om_client_basket_{deal['id']}", None)
            _tab().flash("success", f"{len(items)} question(s) recorded as asked.")
            st.rerun()


def _proposal_cards(deal_id, key, origin, user):
    checked = st.session_state.get(key)
    if not checked:
        return
    style.html('<span class="ai-label">AI proposals: nothing is saved until you click Apply</span>')
    for i, p in enumerate(list(checked.proposals)):
        with st.container(key=f"{key}_card_{i}"):
            style.html(f'<div class="om-item-head"><span class="om-item-what">{escape(p["label"])}</span></div>'
                       f'<div class="om-source">Before: {escape(str(p["before"]))}</div>'
                       f'<div class="om-value">After: {escape(p["after"])}</div>'
                       + (f'<div class="om-source">From: "{escape(p["quote"])}"</div>' if p["quote"] else ""))
            edited = st.text_input("Edit before applying", p["after"], key=f"{key}_edit_{i}", label_visibility="collapsed")
            with st.container(horizontal=True):
                if st.button("Apply", key=f"{key}_apply_{i}", type="primary"):
                    proposal = dict(p, value=edited if edited != p["after"] else p["value"])
                    try:
                        om_interview.apply(deal_id, proposal, user, origin)
                    except om_slots.InvalidValue as error:
                        st.error(str(error))
                    else:
                        checked.proposals.remove(p)
                        st.rerun()
                if st.button("Cancel", key=f"{key}_cancel_{i}"):
                    checked.proposals.remove(p)
                    st.rerun()
    for line in checked.rejected + [f"Unclear: {u}" for u in checked.unclear]:
        st.caption(line)
    if not checked.proposals and st.button("Done", key=f"{key}_done"):
        st.session_state.pop(key)
        st.rerun()


def _client_reply(state, deal_id, user):
    style.section_title("Paste the client's reply")
    reply = st.text_area("Client's reply", key="om_reply_text", height=140, label_visibility="collapsed",
                         placeholder="Paste the client's email here")
    if st.button("Read the reply", key="om_reply_read", icon=":material/auto_awesome:", disabled=not reply.strip(),
                 help="1 AI request. Proposes values for open items; each is checked and waits for your Apply."):
        try:
            st.session_state.om_reply = om_interview.read_reply(state, reply)
        except Exception as exc:
            st.error(_tab().ai_error(exc))
    _proposal_cards(deal_id, "om_reply", "client_reply", user)


def _client_document(state, deal_id, user):
    style.section_title("Upload a document from the client")
    upload = st.file_uploader("Document (PDF, TXT, CSV or MD)", type=["pdf", "txt", "csv", "md", "docx", "xlsx"],
                              key="om_doc_upload")
    if st.button("Read the document", key="om_doc_read", icon=":material/auto_awesome:", disabled=upload is None,
                 help="1 AI request. A locked or scanned file is explained, not guessed."):
        try:
            text = om_interview.document_text(upload.name, upload.getvalue())
        except ValueError as error:
            st.warning(str(error))
        else:
            try:
                st.session_state.om_doc = om_interview.read_reply(state, text)
            except Exception as exc:
                st.error(_tab().ai_error(exc))
    _proposal_cards(deal_id, "om_doc", "client_document", user)


def _open_questions(deal_id, state):
    asked = [q for q in queries.om_questions(deal_id) if q["audience"] == "client"]
    if not asked:
        return
    with st.expander(f"Questions asked of the client ({len(asked)})"):
        for q in asked:
            label = state.slots[q["slot_id"]].slot.label if q["slot_id"] in state.slots else q["slot_id"]
            st.markdown(f"- {escape(label)}: {q['status']} (asked {q['created_at']} UTC)")
