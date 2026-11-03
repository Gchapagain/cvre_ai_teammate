"""The OM tab's working views: pricing and assumptions, and client questions. (Photos are on each slide.)

Every change happens on a person's click. AI buttons say how many requests they use.
"""

from html import escape

import streamlit as st

from app import queries, style
from services import om_calc, om_interview, om_slots


def _tab():
    from app.views import om_tab  # here: om_tab imports this module
    return om_tab


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
        st.dataframe({"Line": list(table)} | {h: [row[i] for row in table.values()] for i, h in enumerate(header)},
                     hide_index=True, width="stretch", column_config={"Line": st.column_config.TextColumn(pinned=True)})
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
            _tab().flash("success", "Price saved. Approve it on the Investment Price Overview slide when you are sure.")
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
