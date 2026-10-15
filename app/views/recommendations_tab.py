"""Recommendations tab: suggestions a person can accept, dismiss or add to the deal's notes.

"From the deal's data" cards are calculated in code. "From market research" cards are written by
the AI only when someone clicks Generate, and are checked in code before they are shown.
"""

import logging
import re
from datetime import date
from html import escape

import streamlit as st

from app import queries, style
from services import connections, deals, gemini, recommendations, research

log = logging.getLogger(__name__)
PRIORITY_PILLS = {"High": "flag", "Medium": "needs-review", "Low": "other"}
KIND_LABELS = {recommendations.RULE: "From the deal's data", recommendations.AI: "From market research"}


def _key(rec):
    return re.sub(r"\W", "_", rec["rule_key"]) if rec.get("rule_key") else str(rec["id"])


def _act(deal_id, rec, status):
    if rec["kind"] == recommendations.RULE:
        recommendations.set_rule_status(deal_id, rec, status)
    else:
        recommendations.set_ai_status(rec["id"], status)


def _add_note(deal_id, rec):
    deals.add_note(deal_id, recommendations.note_text(rec), "Typed")
    st.session_state.rec_message = f"Added to the deal's notes: {rec['title']}"


def _chip(evidence):
    parts = [evidence["name"]]
    parts.append(f"Tier {evidence['tier']}" if evidence.get("tier") else "")
    parts += [evidence.get("date") or "date not stated", evidence.get("connection") or ""]
    figure = f'<b>{escape(evidence["figure"])}</b>' if evidence.get("figure") else ""
    tier_class = f" tier{evidence['tier']}" if evidence.get("tier") else ""
    return (f'<span class="evidence{tier_class}">{figure}{" · " if figure else ""}'
            f'{escape(" · ".join(p for p in parts if p))}</span>')


def _card(deal_id, rec):
    status = rec.get("status", "new")
    disagree = research.disagreements(rec["evidence"])
    with st.container(border=True, key=f"rec_{rec['kind']}_{status}_{_key(rec)}"):
        decided = {"accepted": style.pill("Accepted", "approved"), "dismissed": style.pill("Dismissed", "other")}.get(status, "")
        tag = '<span class="pill flag">Sources disagree</span>' if disagree else ""
        style.html(f'<div class="rec-head"><span class="rec-title">{escape(rec["title"])}</span>'
                   f'{style.pill(rec["priority"] + " priority", PRIORITY_PILLS[rec["priority"]])}{tag}{decided}</div>'
                   f'<div class="rec-kind">{escape(KIND_LABELS[rec["kind"]])}</div>'
                   f'<div class="rec-why"><b>Why:</b> {escape(rec["why"])}</div>'
                   f'<div class="rec-evidence">{"".join(_chip(e) for e in rec["evidence"])}</div>'
                   f'<div class="rec-next"><b>Suggested next step:</b> {escape(rec["next_step"])}</div>')
        if disagree:
            st.caption("The evidence gives different figures for " + ", ".join(disagree) + ". Both are shown; they have not been combined.")
        if rec.get("rule"):
            st.caption(f"Rule: {rec['rule']}")
        actions = st.container(horizontal=True)
        actions.button("Accept", key=f"rec_accept_{_key(rec)}", icon=":material/check:", disabled=status == "accepted",
                       on_click=_act, args=(deal_id, rec, "accepted"))
        actions.button("Dismiss", key=f"rec_dismiss_{_key(rec)}", icon=":material/close:", disabled=status == "dismissed",
                       on_click=_act, args=(deal_id, rec, "dismissed"))
        actions.button("Add to deal notes", key=f"rec_note_{_key(rec)}", icon=":material/note_add:",
                       on_click=_add_note, args=(deal_id, rec))


def _generate(deal_id):
    names = {a.id: a.name for a in connections.all_adapters()}
    try:
        kept, removed = recommendations.generate_ai(deal_id, names)
        message = f"{len(kept)} suggestion{'s' if len(kept) != 1 else ''} added."
        if removed:
            message += f" {removed} suggestion{'s' if removed != 1 else ''} removed: could not be verified."
    except ValueError as exc:
        message = str(exc)
    except gemini.GeminiQuotaError as exc:
        message = f"The AI's daily quota is used up, so no suggestions were written. {exc}"
    except gemini.GeminiBusyError:
        message = "The AI is busy or rate-limited at the moment. Try again in a minute."
    except gemini.GeminiError as exc:
        message = f"The AI couldn't write suggestions just now. {exc}"
    except Exception:
        log.exception("Generating recommendations failed")
        message = "The AI couldn't write suggestions just now. Something unexpected went wrong."
    st.session_state.rec_message = message


def _left_out(deal_id):
    """Simulated findings are shown here so it is clear they were not used."""
    simulated = [f for f in queries.deal_findings(deal_id) if f["simulated"]]
    if not simulated:
        return
    with st.container(border=True, key="rec_left_out"):
        names = {a.id: a.name for a in connections.all_adapters()}
        items = "".join(f'<li><span class="chip simulated">SIMULATED</span> {escape(names.get(f["connection_id"], f["connection_id"]))}: '
                        f'{escape(f["summary"])}</li>' for f in simulated)
        style.html(f'<div class="card-title">Not used: simulated findings</div><ul class="left-out">{items}</ul>')
        st.caption("Demo sources return made-up samples. They are never sent to the AI and never become recommendations.")


def render(deal):
    deal_id = deal["id"]
    style.html(style.banner("ai", "AI suggestions. A person decides.",
                            footer="Nothing here happens on its own. Accept, dismiss or add a suggestion to the deal's notes."))
    if st.session_state.get("rec_message"):
        st.info(st.session_state.rec_message)
    saved = queries.deal_recommendations(deal_id)
    decisions = {r["rule_key"]: r["status"] for r in saved if r["kind"] == recommendations.RULE}

    style.section_title("From the deal's data")
    units = queries.deal_units(deal_id)
    rules = recommendations.rule_recommendations(units, queries.deal_flags(deal_id), queries.deal_t12(deal_id),
                                                 queries.deal_documents(deal_id), date.today())
    if not rules:
        st.caption("No rule fired for this deal's data." if units else "This deal has no extracted numbers yet.")
    for rec in rules:
        _card(deal_id, dict(rec, status=decisions.get(rec["rule_key"], "new")))
    st.caption("Calculated in code from the saved rent roll and documents. No AI is used for these.")

    style.section_title("From market research")
    for rec in [r for r in saved if r["kind"] == recommendations.AI]:
        _card(deal_id, dict(rec, rule=recommendations.AI_PRIORITY_RULE))
    st.button("Generate recommendations", key="rec_generate", icon=":material/auto_awesome:", on_click=_generate, args=(deal_id,),
              help="Uses 1 AI request. Needs at least one real research finding.")
    st.caption("Uses 1 AI request. Written only from this deal's facts and real research findings, never simulated ones. "
               "Each suggestion must cite a finding, and any suggestion with a number that cannot be found is removed.")
    _left_out(deal_id)
