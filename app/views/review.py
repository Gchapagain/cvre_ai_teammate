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
from app.views import correction_panel, data_tab, editing, notes, timeline
from app.views import flags as flag_cards
from services import connections, corrections, drafting, extraction, gemini, metrics, research
from services.connections.base import TIER_LABELS

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


FLAG_WORDS = {"open": "Flagged", "confirmed": "Confirmed", "corrected": "Corrected"}
EDITED_CELL_STYLE = "background-color: #fbf3d6; color: #5c4a08; font-weight: 600"


def units_table(units, flags, edited=None):
    """The rent roll as a table. Flag says in words whether a unit has an open or resolved flag;
    Edited names any field a person changed (the original value is shown when you click the cell)."""
    edited = edited or {}
    status = {}
    for flag in flags:  # an open flag outranks a resolved one
        current = status.get(flag["rent_roll_unit_id"])
        if current != "open":
            status[flag["rent_roll_unit_id"]] = "open" if flag["status"] == "open" else current or flag["status"]
    table = pd.DataFrame([{label: unit[field] for field, label in COLUMNS.items()} for unit in units])
    table.insert(1, "Flag", [FLAG_WORDS.get(status.get(unit["id"]), "") for unit in units])
    table["Edited"] = [", ".join(COLUMNS[f] for (unit_id, f) in edited if unit_id == unit["id"] and f in COLUMNS)
                       for unit in units]
    return table


def _styled(table, units=(), edited=None):
    edited = edited or {}
    ids = [unit["id"] for unit in units]
    columns = {label: field for field, label in COLUMNS.items()}

    def highlight(row):
        unit_id = ids[row.name] if row.name < len(ids) else None
        return [EDITED_CELL_STYLE if (unit_id, columns.get(column)) in edited
                else FLAG_ROW_STYLE if row["Flag"] == "Flagged" else "" for column in row.index]
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


def _selected_cell(event):
    """(row index, column label) of the clicked cell, or None."""
    selection = getattr(event, "selection", None) or (event or {}).get("selection", {})
    cells = selection.get("cells", []) if isinstance(selection, dict) else getattr(selection, "cells", [])
    if not cells:
        return None
    cell = cells[0]
    row, column = (cell.get("row"), cell.get("column")) if isinstance(cell, dict) else (cell[0], cell[1])
    return row, column


def _cell_editor(deal, units, edited, cell, locked):
    row, column = cell
    if row is None or row >= len(units):
        return
    unit = units[row]
    field = {label: field for field, label in COLUMNS.items()}.get(column)
    st.markdown(f"**Unit {unit['unit_number']} · {column}**")
    info = edited.get((unit["id"], field))
    if info:
        style.html(f'<div class="original">Edited. Original extracted value: <b>{escape(editing.show(info["original"]))}</b> · '
                   f'changed by {escape(info["user"])}, {escape(metrics.time_ago(info["when"]) or info["when"])} · '
                   f'{escape(info["source"])} · why: {escape(info["reason"])}</div>')
    if field in corrections.EDITABLE:
        editing.render(deal, unit, f"cell_{unit['id']}_{field}", fields=[field], locked=locked)
    elif field == "rent_per_sf":
        st.caption("Rent / SF is worked out from annual rent and SF. Change one of those and it is recomputed for you.")
    else:
        st.caption("Click a value such as SF, rent, a lease date, the tenant or the lease type to change it.")


def _extracted_fields(deal, units, flags, documents, locked):
    line, complete = units_read_line(units, documents)
    edited = corrections.originals(deal["id"])
    with _card("fields", "Extracted fields", line):
        if not complete:
            st.warning("The number of units read does not match the rows in the source file. Check the document.")
        event = st.dataframe(_styled(units_table(units, flags, edited), units, edited), hide_index=True, width="stretch",
                             column_config={"Flag": st.column_config.TextColumn(width=90)},
                             on_select="rerun", selection_mode="single-cell", key="fields_table")
        names = ", ".join(doc["filename"] for doc in rent_roll_documents(documents))
        changed = f" {len(edited)} value{'s' if len(edited) != 1 else ''} changed by a person (gold cells)." if edited else ""
        st.caption(f"From this deal: {names}. Shown as extracted unless edited.{changed} Click a cell to change it or see its original value.")
        cell = _selected_cell(event)
        if cell:
            _cell_editor(deal, units, edited, cell, locked)


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


TOPIC_ORDER = list(research.TOPICS) + ["Population and income"]
OUTCOME_TEXT = {"ok": "{count} finding(s)", "cached": "used results from the last 24 hours",
                "unavailable": "Source unavailable: {message}", "not set up": "Not set up: {message}"}


def _run(deal, force):
    """Run every switched-on source, showing each one's progress. One failing never stops the others."""
    with st.status("Running research...", expanded=True) as status:
        try:
            results = connections.run_research(deal, force=force, progress=lambda name, message: status.write(f"{name}: {message}"))
        except ValueError as exc:
            st.session_state.research_message = str(exc)
            status.update(label="Research could not run", state="error")
            return
        status.update(label="Research finished", state="complete")
    st.session_state.research_message = None
    st.session_state[f"research_results_{deal['id']}"] = results
    st.rerun()


def _source_row(source):
    figure = escape(source["figure"]) if source.get("figure") else '<span class="none">no figure stated</span>'
    name = (f'<a href="{escape(source["url"], quote=True)}" target="_blank" rel="noopener">{escape(source["name"])}</a>'
            if source.get("url") else f'<span class="src-name">{escape(source["name"])}</span>')
    tier = f'<span class="pill tier{source["tier"]}">Tier {source["tier"]}</span>' if source.get("tier") else "<span></span>"
    unchecked = ('<div class="unchecked">Figure as stated in the search answer; the page\'s own text was not available to check it.</div>'
                 if source.get("checked") is False and source.get("figure") else "")
    return (f'<div class="source">{tier}{name}<span class="when">{escape(source.get("date") or "date not stated")}</span>'
            f'<span class="figure">{figure}</span></div>{unchecked}')


def _finding(finding, names):
    status = {"new": "", "accepted": style.pill("Accepted", "approved"), "dismissed": style.pill("Dismissed", "other")}[finding["status"]]
    simulated = finding["simulated"]
    with st.container(border=True, key=f"finding_{'simulated' if simulated else finding['status']}_{finding['id']}"):
        chips = f'<span class="chip">{escape(names.get(finding["connection_id"], finding["connection_id"]))}</span>'
        chips += '<span class="chip simulated">SIMULATED</span>' if simulated else ""
        style.html(f'<div class="finding-head">{chips}{status}</div>'
                   f'<div class="finding-summary">{escape(finding["summary"])}</div>'
                   + "".join(_source_row(source) for source in finding["sources"]))
        if finding["skipped"]:
            count = finding["skipped"]
            st.caption(f"{count} source{'' if count == 1 else 's'} skipped (not on the trusted list).")
        if not finding["sources"]:
            return
        actions = st.container(horizontal=True)
        actions.button("Accept", key=f"accept_finding_{finding['id']}", icon=":material/check:",
                       disabled=simulated or finding["status"] == "accepted", on_click=research.set_status,
                       args=(finding["id"], "accepted"),
                       help="Simulated sample data can never be accepted." if simulated else None)
        actions.button("Dismiss", key=f"dismiss_finding_{finding['id']}", icon=":material/close:",
                       disabled=finding["status"] == "dismissed", on_click=research.set_status,
                       args=(finding["id"], "dismissed"))


def _topic(topic, findings, names):
    live = [dict(source, simulated=bool(f["simulated"])) for f in findings if f["status"] != "dismissed" for source in f["sources"]]
    disagree = research.disagreements(live)
    tag = '<span class="pill flag">Sources disagree</span>' if disagree else ""
    style.html(f'<div class="finding-topic"><span>{escape(topic)}</span>{tag}</div>')
    if disagree:
        st.caption("The sources give different figures for " + ", ".join(disagree)
                   + ". Each figure is shown with its source; they have not been combined.")
    for finding in findings:
        _finding(finding, names)


def _results_line(results):
    lines = [f"{r['name']}: " + OUTCOME_TEXT[r["outcome"]].format(**r) for r in results]
    style.html('<ul class="run-results">' + "".join(f"<li>{escape(line)}</li>" for line in lines) + "</ul>")


def _import_box(deal):
    with st.expander(":material/upload_file: Import a market report"):
        st.caption("A CSV, Excel or PDF you exported from your own platform. Findings will cite this file. "
                   "Reading it uses 1 AI request. Locked PDFs get 'Needs password' and are never opened.")
        upload = st.file_uploader("Report file", type=["csv", "xlsx", "pdf"], key=f"import_file_{deal['id']}")
        left, right = st.columns(2)
        publisher = left.text_input("Who published it?", key=f"import_publisher_{deal['id']}", placeholder="For example: a brokerage")
        tier = right.selectbox("Publisher tier", [1, 2, 3], index=None, key=f"import_tier_{deal['id']}",
                               format_func=lambda t: f"Tier {t}: {TIER_LABELS[t]}", placeholder="Choose a tier")
        if st.button("Import report", key=f"import_go_{deal['id']}", icon=":material/upload:", disabled=upload is None):
            try:
                found = connections.import_report(deal["id"], upload.name, upload.getvalue(), publisher, tier)
                st.session_state.research_message = f"Imported {upload.name}: {len(found)} finding(s)."
            except (connections.SourceError, gemini.GeminiError) as exc:
                st.session_state.research_message = f"{upload.name} could not be imported. {exc}"
            st.rerun()


def _research(deal):
    findings = queries.deal_findings(deal["id"])
    last_run = f"Last run {metrics.time_ago(max(f['fetched_at'] for f in findings))}" if findings else "Not run yet"
    names = {a.id: a.name for a in connections.all_adapters()}
    with _card("research", "Market research", last_run):
        place = f"{deal['property_type'] or 'property'} market in {deal['submarket'] or 'this location'}"
        st.caption(f"About the {place}, not about this property (the sample property is fictional). "
                   "Advisory only: sourced, not verified. Nothing reaches the narrative until you click Accept.")
        if st.session_state.get("research_message"):
            st.warning(st.session_state.research_message)
        results = st.session_state.get(f"research_results_{deal['id']}")
        if results:
            _results_line(results)
        by_topic = {}
        for finding in findings:
            by_topic.setdefault(finding["topic"], []).append(finding)
        for topic in sorted(by_topic, key=lambda t: TOPIC_ORDER.index(t) if t in TOPIC_ORDER else len(TOPIC_ORDER)):
            _topic(topic, by_topic[topic], names)
        actions = st.container(horizontal=True, vertical_alignment="center")
        run = actions.button("Run research again" if findings else "Run research", key="research_run",
                             icon=":material/travel_explore:", help="Calls each switched-on source once (see the Connections page).")
        force = actions.checkbox("Refresh results less than 24 hours old", key="research_force")
        if run:
            _run(deal, force)
        st.caption("Runs only the sources switched on in Connections. Searches use only the property type and location, "
                   "never the deal's name, tenants or figures.")
        _import_box(deal)


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


def _accepted_recommendations(deal):
    accepted = [r for r in queries.deal_recommendations(deal["id"]) if r["status"] == "accepted"]
    if not accepted:
        return
    with _card("accepted_recs", "Accepted recommendations"):
        style.html('<ul class="takeaways">' + "".join(
            f'<li>{escape(r["title"])} <span class="kv-note">({"from the deal\'s data" if r["kind"] == "rule" else "from market research"})</span></li>'
            for r in accepted) + "</ul>")
        st.caption("Accepted on the Recommendations tab. These can feed the draft narrative.")


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
    open_flags = [f for f in flags if f["status"] == "open"]
    locked = deal["status"] == "Approved"
    result = st.session_state.pop("edit_result", None)
    if result:
        (st.success if result["kind"] == "success" else st.warning)(result["text"])
    main, side = st.columns([2, 1], gap="medium")
    with main:
        flag_cards.render(deal, flags, units, locked, correction_panel.render)
        _extracted_fields(deal, units, flags, documents, locked)
        _narrative(deal, units, open_flags)
        _research(deal)
        notes.render(deal)
    with side:
        _snapshot(units, open_flags, t12)
        timeline.render(deal, locked)
        _accepted_recommendations(deal)
        _takeaways(units, open_flags)
        _sources(units, flags, documents)
