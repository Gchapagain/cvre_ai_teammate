"""The Review tab: everything a broker needs for one deal on one screen.

Left column: anomalies, extracted fields, draft narrative, market research.
Right column: deal snapshot, key takeaways, where it all came from.
Every figure on this tab is calculated in services/metrics.py from saved rows.
"""

import logging
from datetime import date
from html import escape

import pandas as pd
import streamlit as st

from app import exports, icons, queries, style
from app.views import data_tab, notes
from services import drafting, extraction, gemini, metrics

log = logging.getLogger(__name__)

COLUMNS = {
    "unit_number": "Unit", "tenant_name": "Tenant", "square_feet": "SF",
    "lease_start": "Lease start", "lease_end": "Lease end", "monthly_rent": "Monthly rent",
    "annual_rent": "Annual rent", "rent_per_sf": "Rent / SF", "lease_type": "Lease type",
}
FLAG_ROW_STYLE = "background-color: #fbe1df; color: #5e130d; font-weight: 600"
EXCEL_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _number(decimals):
    """Format numbers for display, but show anything else exactly as stored."""
    def show(value):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f"{value:,.{decimals}f}"
        return "" if value is None else str(value)
    return show


def units_table(units, flags):
    """The rent roll as a table with a Flag column. Flagged rows are marked in words, not only colour."""
    flagged_ids = {flag["rent_roll_unit_id"] for flag in flags}
    table = pd.DataFrame([{label: unit[field] for field, label in COLUMNS.items()} for unit in units])
    table.insert(1, "Flag", ["Flagged" if unit["id"] in flagged_ids else "" for unit in units])
    return table


def _styled(table):
    highlight = lambda row: [FLAG_ROW_STYLE if row["Flag"] else ""] * len(row)
    return table.style.apply(highlight, axis=1).format(
        {"SF": _number(0), "Monthly rent": _number(2), "Annual rent": _number(2), "Rent / SF": _number(2)}
    )


def rent_roll_documents(documents):
    return [doc for doc in documents if doc["used_for"] == "Rent roll"]


def units_read_line(units, documents):
    """'12 of 12 units read' when the source file can be counted, otherwise just what was read."""
    sources = rent_roll_documents(documents)
    expected = extraction.count_unit_rows(sources[0]["file_path"]) if sources and sources[0]["file_path"] else None
    if expected is None:
        return f"{len(units)} units read", True
    return f"{len(units)} of {expected} units read", len(units) == expected


def _card(key, title, caption=""):
    card = st.container(border=True, key=f"card_{key}")
    note = f'<span class="card-note">{escape(caption)}</span>' if caption else ""
    card.markdown(f'<div class="card-title">{escape(title)}{note}</div>', unsafe_allow_html=True)
    return card


def _anomaly_banner(flags):
    if flags:
        count = len(flags)
        style.html(style.banner(
            "flagged", f"{count} anomal{'y' if count == 1 else 'ies'} found",
            [flag["message"] for flag in flags],
            "Flagged, not hidden: the numbers below are shown exactly as extracted. A person decides what to do.",
        ))
    else:
        style.html(style.banner("clear", "No anomalies found", footer="Every validation rule passed for this rent roll."))


def _extracted_fields(units, flags, documents):
    line, complete = units_read_line(units, documents)
    with _card("fields", "Extracted fields", line):
        if not complete:
            st.warning("The number of units read does not match the rows in the source file. Check the document.")
        st.dataframe(_styled(units_table(units, flags)), hide_index=True, width="stretch",
                     column_config={"Flag": st.column_config.TextColumn(width=90)})
        names = ", ".join(doc["filename"] for doc in rent_roll_documents(documents))
        st.caption(f"From this deal: {names}. Shown exactly as extracted.")


def _generate(deal_id):
    """Ask the AI for a draft. Problems become a message on the card; nothing else changes."""
    try:
        drafting.generate_draft(deal_id)
        message = None
    except gemini.GeminiQuotaError as exc:
        message = f"The AI's daily quota is used up, so it can't draft right now. {exc} Nothing was saved."
    except gemini.GeminiBusyError:
        message = "The AI is busy or rate-limited at the moment. Try again in a minute. Nothing was saved."
    except gemini.GeminiError as exc:
        message = f"The AI couldn't write a draft just now. {exc} Nothing was saved."
    except Exception:
        log.exception("Drafting failed")
        message = "The AI couldn't write a draft just now. Something unexpected went wrong. Nothing was saved."
    st.session_state.draft_message = message
    st.session_state.draft_editing = False


def _start_editing():
    st.session_state.draft_editing = True


def _save_edit(draft_id, key):
    text = st.session_state.get(key, "")
    if text.strip():
        drafting.save_edit(draft_id, text)
        st.session_state.draft_editing = False


def _approve(draft_id):
    try:
        drafting.approve(draft_id)
    except drafting.DraftNotVerified as exc:
        st.session_state.draft_message = f"Not approved. {exc}"


def _download(actions, deal, units, flags, draft):
    """Download the draft once there is one; until then, the rent roll with its flags."""
    stem = exports.slug(deal["name"])
    if draft:
        actions.download_button("Download", data_tab.draft_text(deal, draft), f"{stem}_draft_narrative.txt", "text/plain",
                                key="review_download", icon=":material/download:",
                                help=f"Downloads {stem}_draft_narrative.txt: the draft with its status on the first line.")
    else:
        table = exports.rent_roll_table(units, flags)
        actions.download_button("Download", exports.to_excel(table, "Rent roll"), f"{stem}_rent_roll.xlsx", EXCEL_TYPE,
                                key="review_download", icon=":material/download:",
                                help=f"Downloads {stem}_rent_roll.xlsx: the rent roll with its flags.")


def _narrative(deal, units, flags):
    draft = queries.latest_draft(deal["id"])
    editing = bool(draft) and st.session_state.get("draft_editing", False)
    with _card("narrative", "Draft pricing narrative", draft["status"] if draft else ""):
        if st.session_state.get("draft_message"):
            st.warning(st.session_state.draft_message)
        missing = []
        if draft:
            origin = "AI-drafted, then edited by a person" if draft["edited"] else "AI-drafted"
            style.html(f'<div class="ai-label">{icons.SPARKLE}<span>{origin} - edit anything before it goes out</span></div>')
            key = f"draft_text_{draft['id']}"
            st.text_area("Draft", value=draft["text"], key=key, height=220, disabled=not editing, label_visibility="collapsed")
            missing = drafting.unmatched_numbers(draft["text"], deal["id"])
            if missing:
                st.error("This draft states figures that are not in the deal data: " + drafting.show_numbers(missing)
                         + ". Edit the draft before it can be approved.")
            else:
                st.caption("Checked: every number in this draft appears in the deal data or accepted research.")
        else:
            st.caption("No draft yet. The AI writes one only when you ask, from this deal's saved numbers "
                       "and any research you have accepted.")
        actions = st.container(key="narrative_actions", horizontal=True)
        actions.button("Generate a new draft" if draft else "Generate draft", key="draft_generate",
                       icon=":material/auto_awesome:", on_click=_generate, args=(deal["id"],),
                       help="Uses 1 AI request.")
        actions.button("Flag for producer", key="draft_flag", icon=":material/flag:", disabled=not draft or editing,
                       on_click=drafting.flag_for_producer, args=(draft["id"],) if draft else None)
        if editing:
            actions.button("Save edits", key="draft_edit", icon=":material/save:", on_click=_save_edit,
                           args=(draft["id"], f"draft_text_{draft['id']}"))
        else:
            actions.button("Edit", key="draft_edit", icon=":material/edit:", disabled=not draft, on_click=_start_editing)
        can_approve = bool(draft) and not editing and not missing and draft["status"] != drafting.STATUS_APPROVED
        actions.button("Approve", key="draft_approve", type="primary", icon=":material/check:", disabled=not can_approve,
                       on_click=_approve, args=(draft["id"],) if draft else None)
        _download(actions, deal, units, flags, draft)
        st.caption("Generating uses 1 AI request. Approving is always a person's action; nothing is sent anywhere.")


def _research():
    with _card("research", "Market research"):
        st.caption("Research has not been run for this deal. It comes in a later stage and is advisory only.")


def _snapshot(units, flags, t12):
    rows = "".join(
        f'<div class="kv"><div><div class="k">{escape(label)}</div>'
        + (f'<div class="kv-note">{escape(note)}</div>' if note else "")
        + f'</div><div class="v{" muted" if value in (metrics.NOT_AVAILABLE, metrics.NEEDS_T12, metrics.NOT_MEASURED) else ""}">'
        f'{escape(value)}</div></div>'
        for label, value, note in metrics.snapshot(units, flags, t12, date.today())
    )
    with _card("snapshot", "Deal snapshot"):
        style.html(rows)
        st.caption("Calculated from the saved rent roll. Occupancy and cap rate are not shown: "
                   "a rent roll alone cannot produce them.")


def _takeaways(units, flags):
    lines = metrics.takeaways(units, flags, date.today())
    with _card("takeaways", "Key takeaways"):
        if lines:
            style.html('<ul class="takeaways">' + "".join(f"<li>{escape(line)}</li>" for line in lines) + "</ul>")
            st.caption("Each line is calculated from the rent roll rows, not written by the AI.")
        else:
            st.caption("Nothing can be calculated from this rent roll yet.")


def _go_to_documents():
    st.session_state.deal_tabs = st.session_state.get("documents_tab_label")


def _sources(units, flags, documents):
    with _card("sources", "Where this came from"):
        lines = [f"{len(units)} rows extracted from {doc['filename']} (first sheet), source: {doc['source']}."
                 for doc in rent_roll_documents(documents)]
        lines += [f"{doc['filename']}: {doc['status']}." for doc in documents if doc["used_for"] != "Rent roll"]
        lines += [f"Flag on unit {flag['unit_number'] or '(no ID)'}: validation rule {flag['rule']} "
                  f"(actual {flag['actual_value']}, limit {flag['threshold']})." for flag in flags]
        style.html('<ul class="takeaways">' + "".join(f"<li>{escape(line)}</li>" for line in lines) + "</ul>")
        st.caption("Accuracy has not been measured yet, so no match rate is shown.")
        st.button("Open the Documents tab", key="go_documents", type="tertiary", icon=":material/arrow_forward:",
                  on_click=_go_to_documents)


def _no_numbers(documents):
    footer = ("This deal's documents have not been read yet, so there is nothing to review."
              if documents else "This deal has no documents yet, so there is nothing to review.")
    style.html(style.banner("waiting", "No numbers yet", [f"{d['filename']}: {d['status']}" for d in documents], footer))


def render(deal):
    units, documents = queries.deal_units(deal["id"]), queries.deal_documents(deal["id"])
    if not units:
        _no_numbers(documents)
        notes.render(deal)
        return
    flags, t12 = queries.deal_flags(deal["id"]), queries.deal_t12(deal["id"])
    main, side = st.columns([2, 1], gap="medium")
    with main:
        _anomaly_banner(flags)
        _extracted_fields(units, flags, documents)
        _narrative(deal, units, flags)
        _research()
        notes.render(deal)
    with side:
        _snapshot(units, flags, t12)
        _takeaways(units, flags)
        _sources(units, flags, documents)
