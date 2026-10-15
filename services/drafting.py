"""Drafting service: Gemini writes a short pricing narrative from one deal's saved numbers.

The draft is only ever a starting point. It is saved as "Generated, not sent", a code
check compares every number in it with the deal's data, and only a person can approve it.
"""

import json
import sqlite3
from datetime import date

from google.genai import types

import db
from services import gemini, metrics, qa

STATUS_GENERATED = "Generated, not sent"
STATUS_FLAGGED = "Flagged for producer"
STATUS_APPROVED = "Approved"

PROMPT = """You are drafting a short pricing narrative for a commercial real estate broker to edit.

Rules:
- Write one or two short paragraphs in plain business English. No headings, no lists.
- Use ONLY the DEAL FACTS below. Never state a figure that is not written there. Do not estimate,
  round differently, or bring in outside knowledge, market opinions or a value conclusion.
- Do not state a price, cap rate or occupancy: the facts do not contain them.
- If any unit is flagged, say plainly that the flagged units need confirmation before the figures are used.
- Accepted market research may be mentioned only as written, and described as sourced, not verified.

DEAL FACTS
{facts}
"""


class DraftNotVerified(Exception):
    """The draft contains a number that is not in the deal data, so it cannot be approved as it stands."""


def _accepted_findings(conn, deal_id):
    rows = conn.execute(
        "SELECT topic, summary, sources FROM research_findings WHERE deal_id = ? AND status = 'accepted' "
        "AND simulated = 0 ORDER BY id",
        (deal_id,),
    ).fetchall()
    lines = []
    for row in rows:
        lines.append(f"{row['topic']}: {row['summary']}")
        for source in json.loads(row["sources"]):
            figure = source.get("figure") or "no figure stated"
            lines.append(f"  - {source.get('name')} (Tier {source.get('tier')}, {source.get('date') or 'date not stated'}): {figure}")
    return lines


def _accepted_recommendations(conn, deal_id):
    try:
        rows = conn.execute("SELECT title, next_step FROM recommendations WHERE deal_id = ? AND status = 'accepted' ORDER BY id",
                            (deal_id,)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [f"{row['title']}. Next step: {row['next_step']}" for row in rows]


def deal_facts(deal_id, db_path=None, today=None):
    """Everything the narrative may draw on, as text: saved rows, calculated figures and accepted research."""
    today = today or date.today()
    data = qa.load_deal_data(deal_id, db_path)
    lines = [qa.build_context(data), "\nCalculated figures:"]
    lines += [f"{label}: {value}" for label, value, _ in metrics.snapshot(data["units"], data["flags"], data["t12"], today)]
    lines.append("\nKey takeaways (calculated):")
    lines += metrics.takeaways(data["units"], data["flags"], today) or ["None"]
    conn = db.get_connection(db_path)
    try:
        findings = _accepted_findings(conn, deal_id)
        recommendations = _accepted_recommendations(conn, deal_id)
    finally:
        conn.close()
    lines.append("\nAccepted market research (sourced, not verified):")
    lines += findings or ["None accepted"]
    lines.append("\nAccepted recommendations:")
    lines += recommendations or ["None accepted"]
    return "\n".join(lines), data


def unmatched_numbers(text, deal_id, db_path=None, today=None):
    """Numbers in the text that are not in the deal's data or accepted research. Empty means all match."""
    facts, _ = deal_facts(deal_id, db_path, today)
    return qa.unmatched_numbers(text, facts)


def show_numbers(numbers):
    """Numbers as a person would write them: 19,000,000 and 6.5, not 1.9e+07."""
    return ", ".join(f"{n:,.2f}".rstrip("0").rstrip(".") for n in numbers)


def flag_sentence(flags):
    units = ", ".join(sorted({str(f["unit_number"]) for f in flags if f["unit_number"]}))
    return f"Flagged units ({units}) need confirmation before these figures are used."


def with_flag_sentence(text, flags):
    """Make sure a draft for a deal with flags says so, even if the AI left it out."""
    if not flags or "confirm" in text.lower():
        return text
    return f"{text.rstrip()}\n\n{flag_sentence(flags)}"


def _write(db_path, sql, params):
    db.init_db(db_path)
    conn = db.get_connection(db_path)
    try:
        with conn:
            return conn.execute(sql, params).lastrowid
    finally:
        conn.close()


def generate_draft(deal_id, client=None, db_path=None, model=None, record_to=None, replay_from=None, today=None):
    """Write and save a new draft for a deal. Uses one Gemini request. Returns the draft ID.

    replay_from: use the Gemini reply saved in this file instead of calling the API.
    record_to: after a live call, save Gemini's reply to this file.
    """
    facts, data = deal_facts(deal_id, db_path, today)
    if not data["units"]:
        raise ValueError("This deal has no extracted numbers yet, so there is nothing to draft from.")
    prompt = PROMPT.format(facts=facts)
    if replay_from:
        text = gemini.load_recording(replay_from, prompt)
    else:
        text = gemini.generate(client or gemini.get_client(), prompt, types.GenerateContentConfig(temperature=0), model)
        if record_to:
            gemini.save_recording(record_to, prompt, text, model)
    text = with_flag_sentence(text.strip(), data["flags"])
    return _write(db_path, "INSERT INTO drafts (deal_id, text) VALUES (?, ?)", (deal_id, text))


def get_draft(draft_id, db_path=None):
    conn = db.get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def save_edit(draft_id, text, db_path=None):
    """Save a person's changes. An edited draft goes back to 'Generated, not sent' until approved again."""
    text = (text or "").strip()
    if not text:
        raise ValueError("The draft is empty.")
    _write(db_path, "UPDATE drafts SET text = ?, edited = 1, status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
           (text, STATUS_GENERATED, draft_id))


def flag_for_producer(draft_id, db_path=None):
    _write(db_path, "UPDATE drafts SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (STATUS_FLAGGED, draft_id))


def approve(draft_id, db_path=None, today=None):
    """A person approves the draft. Refused while it contains a number that is not in the deal data."""
    draft = get_draft(draft_id, db_path)
    missing = unmatched_numbers(draft["text"], draft["deal_id"], db_path, today)
    if missing:
        raise DraftNotVerified("These figures are not in the deal data: " + show_numbers(missing))
    _write(db_path, "UPDATE drafts SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (STATUS_APPROVED, draft_id))
