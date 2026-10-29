"""Meeting prep briefs: one Gemini request, only when a person clicks Prep brief.

The brief is written from the meeting's deal only: its saved numbers, open flags and anything waiting
for a person. Code then checks every number in it against that same data; a brief with a number that
cannot be found is labelled "Not verified" and the numbers are listed. The brief is saved on the meeting.
"""

import json
from datetime import datetime

from google.genai import types

import db
from services import drafting, gemini, notifications, qa

PROMPT = """MEETING PREP BRIEF. Write a short prep brief for a commercial real estate broker before a meeting.

Rules:
- Use ONLY the MEETING and DEAL FACTS below. No outside knowledge, no market opinions, no guesses.
- Copy any figure exactly as written below. Never estimate, round differently, average or combine figures.
- Do not state a price, value, cap rate or occupancy.
- 3 to 6 short lines, each starting with "- ": the key numbers, every open flag, and anything waiting for the broker.
- Return JSON: {{"brief": "<the lines, separated by newlines>"}}

MEETING
{meeting}

DEAL FACTS
{facts}

WAITING FOR THE BROKER
{waiting}
"""


def _waiting_lines(conn, deal_id):
    lines = [f"Document {r['filename']}: {r['status']}" for r in conn.execute(
        "SELECT filename, status FROM documents WHERE deal_id = ? AND status IN ('Received', 'Needs password')", (deal_id,))]
    drafts = conn.execute("SELECT COUNT(*) FROM drafts WHERE deal_id = ? AND status = 'Generated, not sent'",
                          (deal_id,)).fetchone()[0]
    if drafts:
        lines.append("A draft narrative is waiting for approval")
    findings = conn.execute("SELECT COUNT(*) FROM research_findings WHERE deal_id = ? AND status = 'new' AND simulated = 0",
                            (deal_id,)).fetchone()[0]
    if findings:
        lines.append(f"Research findings waiting to be accepted or dismissed: {findings}")
    return lines or ["Nothing"]


def context(meeting_id, db_path=None):
    """(prompt, facts text the numbers are checked against) for a meeting. Raises if it has no deal."""
    conn = db.get_connection(db_path)
    try:
        meeting = conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        if meeting is None:
            raise ValueError("That meeting could not be found.")
        if meeting["deal_id"] is None:
            raise ValueError("This meeting is not linked to a deal, so there is nothing to brief from.")
        waiting = "\n".join(_waiting_lines(conn, meeting["deal_id"]))
    finally:
        conn.close()
    facts, _ = drafting.deal_facts(meeting["deal_id"], db_path)
    about = f"{meeting['title']} with {meeting['client_name'] or 'the client'}"
    prompt = PROMPT.format(meeting=about, facts=facts, waiting=waiting)
    return prompt, f"{facts}\n{waiting}"


def generate_brief(meeting_id, client=None, db_path=None, now=None):
    """Write, check and save a prep brief. Uses one Gemini request. Returns {text, unverified}."""
    prompt, checked_against = context(meeting_id, db_path)
    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json")
    reply = gemini.generate(client or gemini.get_client(), prompt, config)
    try:
        text = str(json.loads(reply)["brief"]).strip()
    except (ValueError, KeyError, TypeError):
        raise gemini.GeminiError("The AI's reply could not be read. Nothing was saved.") from None
    if not text:
        raise gemini.GeminiError("The AI returned an empty brief. Nothing was saved.")
    brief = {"text": text, "unverified": qa.unmatched_numbers(text, checked_against)}
    notifications.save_brief(meeting_id, brief, now or datetime.now(), db_path)
    return brief
