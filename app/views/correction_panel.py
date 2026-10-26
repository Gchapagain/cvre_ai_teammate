"""'Tell me what is wrong': the AI reads a correction in plain words and proposes changes.

Each proposal is checked in code and shown as a before/after card. Nothing is saved until the
person clicks Apply, which saves it the same audited way as a manual edit, marked AI-assisted.
"""

import logging

import streamlit as st

from app import queries, style
from app.views import editing, voice
from services import correction_ai, corrections, gemini

log = logging.getLogger(__name__)
PLACEHOLDER = ("For example: unit 110's monthly rent should be $2,400. The $5,421.33 includes a one-off fit-out charge.")


def _state(flag_id):
    return st.session_state.setdefault(f"corr_{flag_id}", {"result": None, "message": None, "text": ""})


def _understand(deal_id, flag, text):
    """Ask the AI once. Problems become a friendly message; the manual form stays available."""
    state = _state(flag["id"])
    state.update(result=None, message=None, text=text)
    try:
        state["result"] = correction_ai.understand(deal_id, text, flag)
    except ValueError as exc:
        state["message"] = str(exc)
    except gemini.GeminiQuotaError as exc:
        state["message"] = f"The AI's daily quota is used up, so it can't read your correction right now. {exc} Use the form below instead."
    except gemini.GeminiBusyError:
        state["message"] = "The AI is busy or rate-limited at the moment. Try again in a minute, or use the form below."
    except gemini.RateLimited as exc:  # our own limit, not Google's
        state["message"] = f"{exc} Use the form below instead."
    except gemini.GeminiError as exc:
        state["message"] = f"The AI couldn't read your correction just now. {exc} Use the form below instead."
    except Exception:
        log.exception("Understanding a correction failed")
        state["message"] = "The AI couldn't read your correction just now. Use the form below instead."


def _apply(deal, flag_id, proposal, text):
    user = st.session_state.user["full_name"]
    try:
        result = corrections.apply(deal["id"], proposal["unit_id"], proposal["changes"], text, user, corrections.AI_ASSISTED)
    except (corrections.Locked, ValueError) as exc:
        st.session_state.edit_result = {"kind": "warning", "text": str(exc)}
        return
    lines = [f"Flag cleared: {m}" for m in result["cleared"]] + [f"Still flagged: {m}" for m in result["still"]]
    lines += [f"New flag: {m}" for m in result["new"]]
    st.session_state.edit_result = {"kind": "warning" if result["still"] or result["new"] else "success",
                                    "text": "  \n".join(["Applied (AI-assisted)."] + lines)}
    st.session_state.pop(f"corr_{flag_id}", None)
    st.session_state.pop("open_panel", None)


def _drop(flag_id, index):
    state = _state(flag_id)
    state["result"]["proposals"].pop(index)


def _edit(flag_id, index):
    state = _state(flag_id)
    state["editing"] = state["result"]["proposals"].pop(index)


def _proposal_card(deal, flag, index, proposal, text, locked):
    with st.container(border=True, key=f"proposal_{flag['id']}_{index}"):
        style.html(f'<div class="proposal-title">Proposed change to unit {proposal["unit_number"]}</div>'
                   + editing.preview_table(proposal["changes"]))
        actions = st.container(horizontal=True)
        actions.button("Apply", key=f"ai_apply_{flag['id']}_{index}", type="primary", icon=":material/check:", disabled=locked,
                       on_click=_apply, args=(deal, flag["id"], proposal, text))
        actions.button("Edit", key=f"ai_edit_{flag['id']}_{index}", icon=":material/edit:", on_click=_edit, args=(flag["id"], index))
        actions.button("Cancel", key=f"ai_cancel_{flag['id']}_{index}", icon=":material/close:", on_click=_drop, args=(flag["id"], index))
        st.caption("Apply saves it with your words as the reason, marked AI-assisted. Nothing has been saved yet.")


def _questions(deal, flag, questions, text):
    for index, question in enumerate(questions):
        with st.container(border=True, key=f"question_{flag['id']}_{index}"):
            style.html(f'<div class="proposal-title">The AI needs to know: {style.html_escape(question)}</div>')
            answer = st.text_input("Your answer", key=f"answer_{flag['id']}_{index}")
            if st.button("Send my answer", key=f"answer_go_{flag['id']}_{index}", icon=":material/send:", disabled=not answer.strip(),
                         help="Uses 1 AI request."):
                with st.spinner("Reading your answer..."):
                    _understand(deal["id"], flag, f"{text}\nQuestion: {question}\nAnswer: {answer.strip()}")
                st.rerun()


def render(deal, flag, unit, locked):
    state = _state(flag["id"])
    text_key = f"corr_text_{flag['id']}"
    if f"corr_spoken_{flag['id']}" in st.session_state:  # a checked transcript, added before the box is drawn
        st.session_state[text_key] = st.session_state.pop(f"corr_spoken_{flag['id']}")
    st.markdown("**Tell me what is wrong**")
    text = st.text_area("Tell me what is wrong", key=text_key, height=80, placeholder=PLACEHOLDER,
                        label_visibility="collapsed", disabled=locked)
    spoken = voice.render(f"corr_{flag['id']}", use_label="Use as my correction")
    if spoken:
        st.session_state[f"corr_spoken_{flag['id']}"] = spoken
        st.rerun()
    if st.button("Understand my correction", key=f"understand_{flag['id']}", icon=":material/auto_awesome:",
                 disabled=locked or not text.strip(), help="Uses 1 AI request. Nothing is saved until you click Apply."):
        with st.spinner("Reading your correction..."):
            _understand(deal["id"], flag, text)
    st.caption("Uses 1 AI request. The AI only proposes; nothing is saved until you click Apply.")
    if state["message"]:
        st.warning(state["message"])
    result = state.get("result")
    if result:
        style.html(f'<div class="understood"><b>Here is what I understood:</b> {style.html_escape(result["interpretation"])}</div>')
        if result["dropped"]:
            count = len(result["dropped"])
            st.warning(f"{count} suggestion{'s' if count != 1 else ''} could not be applied: " + "; ".join(result["dropped"]) + ".")
        for index, proposal in enumerate(result["proposals"]):
            _proposal_card(deal, flag, index, proposal, state["text"], locked)
        _questions(deal, flag, result["questions"], state["text"])
        if not result["proposals"] and not result["questions"]:
            st.caption("No change could be proposed. Use the form below, or say it another way.")
    if state.get("editing"):
        proposal = state["editing"]
        st.markdown("**Edit the proposed change, then save**")
        target = next(u for u in queries.deal_units(deal["id"]) if u["id"] == proposal["unit_id"])
        editing.render(deal, target, f"aiedit_{flag['id']}", fields=list(proposal["values"]), locked=locked, source=corrections.AI_ASSISTED,
                       prefill=proposal["values"], reason_prefill=state["text"])
