"""The guided interview ("Help me finish the OM") and client questions.

Driven by the template: each missing slot has a broker question, and slots a client can answer have a
client question. Building the questions and the grouped client message uses no AI (0 Gemini requests).

AI is optional and used only on a click, one request each:
- "Let the AI read my answer": turns a free-form answer into the slot's format.
- "Make it friendlier (AI)": rewrites the client message; every number and question must survive.
- "Read the client's reply" / a client document: proposes values for open slots.

The AI only proposes. Code checks each proposal (a known open slot a client may answer, a value that
passes the slot's validation, every number found in what the person pasted). Nothing is saved until a
person clicks Apply. The app never sends anything to a client: the person copies the message.
"""

import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError

from services import gemini, om_slots, qa

# Slots a person fills somewhere else on the OM tab, not by typing an answer.
ELSEWHERE = {"financial.sale_price": "pricing", "contacts.list": "settings"}
CLIENT_SOURCES = {"client_reply": "From the client's reply", "client_document": "From a client document"}
DOCUMENT_TYPES = (".pdf", ".txt", ".csv", ".md")


@dataclass
class Question:
    state: object                 # om_engine.SlotState
    text: str
    kind: str                     # "answer" (type it), "photo" (upload), "pricing", "settings", "data" (needs documents)
    can_ask_client: bool
    skipped: bool = False

    @property
    def slot(self):
        return self.state.slot


def _kind(state):
    slot = state.slot
    if slot.id in ELSEWHERE:
        return ELSEWHERE[slot.id]
    if slot.type == "photo":
        return "photo"
    if slot.auto and slot.auto.startswith("calc."):
        return "pricing" if any("assumption" in n or "sale price" in n for n in state.needs) else "data"
    return "answer"


def questions(state, skipped=()):
    """Every missing item as a question, required first; ones the person skipped go to the end."""
    out = []
    for item in state.missing():
        kind = _kind(item)
        text = item.slot.broker_question or "; ".join(f"Still needs {n}" for n in item.needs) or item.slot.why
        out.append(Question(item, text, kind, bool(item.slot.client_question) and "client" in item.slot.answer_by,
                            item.slot.id in skipped))
    out.sort(key=lambda q: q.skipped)
    return out


# ---------- the grouped client message (no AI) ----------

def client_message(property_name, items, broker_name, client_name=None):
    """One ready-to-send message with every question, grouped by topic. items: om_engine.SlotState list."""
    groups = {}
    for item in items:
        if item.slot.client_question:
            groups.setdefault(item.slot.topic or "Other", []).append(item.slot.client_question)
    if not groups:
        return ""
    lines = [f"Hi {client_name or 'there'},", "",
             f"We are preparing the offering memorandum for {property_name}. Could you help us with a few items?", ""]
    number = 0
    for topic, asks in groups.items():
        lines.append(topic)
        for ask in dict.fromkeys(asks):  # the same question once, even when several slots share it
            number += 1
            lines.append(f"{number}. {ask}")
        lines.append("")
    lines += ["Replying to this email with whatever you have is perfect; we will follow up on anything else.", "",
              "Thank you,", broker_name]
    return "\n".join(lines)


def save_client_questions(deal_id, items, message, user, db_path=None):
    """Record that these questions were prepared for the client (the person sends the message themselves)."""
    conn = om_slots._connect(db_path)
    try:
        with conn:
            for item in items:
                conn.execute("INSERT INTO om_questions (deal_id, slot_id, audience, text) VALUES (?, ?, 'client', ?)",
                             (deal_id, item.slot.id, item.slot.client_question))
            om_slots.log(conn, deal_id, "client_questions", f"{len(items)} question(s): {message[:200]}", user)
    finally:
        conn.close()


def skip(deal_id, slot_id, question, user, db_path=None):
    conn = om_slots._connect(db_path)
    try:
        with conn:
            conn.execute("INSERT INTO om_questions (deal_id, slot_id, audience, text, status) VALUES (?, ?, 'broker', ?, 'skipped')",
                         (deal_id, slot_id, question))
            om_slots.log(conn, deal_id, "skip", slot_id, user)
    finally:
        conn.close()


def mark_answered(deal_id, slot_ids, db_path=None):
    """Close open questions once their slots have a value."""
    if not slot_ids:
        return
    conn = om_slots._connect(db_path)
    try:
        with conn:
            conn.executemany("UPDATE om_questions SET status = 'answered', answered_at = CURRENT_TIMESTAMP "
                             "WHERE deal_id = ? AND slot_id = ? AND status != 'answered'",
                             [(deal_id, slot_id) for slot_id in slot_ids])
    finally:
        conn.close()


def open_questions(deal_id, db_path=None):
    conn = om_slots._connect(db_path)
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM om_questions WHERE deal_id = ? ORDER BY id", (deal_id,))]
    finally:
        conn.close()


# ---------- AI helpers (one request each, only on a click) ----------

def _ask(prompt, client):
    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json")
    reply = gemini.generate(client or gemini.get_client(), prompt, config)
    try:
        return json.loads(reply)
    except ValueError:
        raise gemini.GeminiError("The AI's reply could not be read. Nothing was changed.") from None


FRIENDLIER = """Rewrite this message from a commercial real estate broker to their client so it reads warmer and
more natural. Keep every question and its meaning, keep the numbering, keep the greeting name and the signature.
Do not add any new request, number, date, price or promise. Return JSON: {{"message": "<the rewritten message>"}}

MESSAGE
{message}"""


def friendlier(message, client=None):
    """One Gemini request. Returns the rewritten text, or raises if it dropped a question or added a number."""
    text = str(_ask(FRIENDLIER.format(message=message), client).get("message") or "").strip()
    asked = len(re.findall(r"^\s*\d+\.", message, re.M))
    if not text or len(re.findall(r"^\s*\d+\.", text, re.M)) < asked:
        raise gemini.GeminiError("The AI's version left out a question, so the original message was kept.")
    if qa.unmatched_numbers(text, message):
        raise gemini.GeminiError("The AI's version added a number that was not in the message, so the original was kept.")
    return text


READ_ANSWER = """A broker answered a question for an offering memorandum. Turn the answer into the field's format.
Field: {label}. Format: {hint}.
Use only what the broker wrote. Never add facts, numbers or words of praise they did not write.
If the answer does not contain the information, return an empty value.
Return JSON: {{"value": <string, or a list of strings for bullet points>}}

BROKER'S ANSWER
{answer}"""

HINTS = {"bullets": "a list of short bullet points", "currency": "a plain number in dollars",
         "integer": "a whole number", "acres": "a number of acres", "year_built": "year built / year renovated",
         "city_state": "City, ST", "text": "clear sentences"}


def read_answer(slot, answer, client=None):
    """One Gemini request: the answer in the slot's format, validated. Nothing is saved."""
    hint = HINTS.get((slot.validation or {}).get("kind", "text"), "clear sentences")
    value = _ask(READ_ANSWER.format(label=slot.label, hint=hint, answer=answer), client).get("value")
    if value in (None, "", []):
        raise om_slots.InvalidValue("The AI could not find this in your answer. Please type it in the box.")
    text = "\n".join(value) if isinstance(value, list) else str(value)
    if qa.unmatched_numbers(text, answer):
        raise om_slots.InvalidValue("The AI's version had a number you did not write, so it was not used.")
    return om_slots.validate(slot, value)


READ_REPLY = """A client replied to questions from their commercial real estate broker. Find answers to the OPEN ITEMS.

Rules:
- Use only what the client wrote. Copy numbers exactly. Never guess, convert units or combine figures.
- One proposal per item the reply clearly answers, with quote = the exact words from the reply you used.
- If an answer is unclear or could fit several items, do not propose it; add a short note to unclear instead.
- Return JSON: {{"proposals": [{{"slot_id": "...", "value": "...", "quote": "..."}}], "unclear": ["..."]}}

OPEN ITEMS (slot_id | what it is | format)
{items}

CLIENT'S REPLY
{reply}"""


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: str
    value: str | list[str]
    quote: str = ""


class ReplyRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposals: list[Proposal]
    unclear: list[str] = []


@dataclass
class Checked:
    """What came out of a client reply: proposals that passed every check, and what was left out and why."""
    proposals: list = field(default_factory=list)   # [{slot_id, label, before, after, value, quote}]
    rejected: list = field(default_factory=list)    # [plain reason]
    unclear: list = field(default_factory=list)


def answerable(state):
    """Open slots a client (or a client's document) may fill: typed slots, not photos, never the price."""
    return [s for s in state.missing() + state.waiting()
            if _kind(s) == "answer" and ("client" in s.slot.answer_by or "document" in s.slot.answer_by)
            and s.status != "approved"]


def read_reply(state, reply, client=None):
    """One Gemini request. Returns Checked proposals; nothing is saved."""
    open_slots = {s.slot.id: s for s in answerable(state)}
    if not open_slots:
        return Checked(rejected=["Nothing in this OM is waiting for a client answer."])
    items = "\n".join(f"{s.slot.id} | {s.slot.label} | {HINTS.get((s.slot.validation or {}).get('kind', 'text'))}"
                      for s in open_slots.values())
    raw = _ask(READ_REPLY.format(items=items, reply=reply), client)
    try:
        parsed = ReplyRead.model_validate(raw)
    except ValidationError:
        raise gemini.GeminiError("The AI's reply could not be read. Nothing was changed.") from None
    result = Checked(unclear=list(parsed.unclear))
    for proposal in parsed.proposals:
        state_ = open_slots.get(proposal.slot_id)
        if state_ is None:
            result.rejected.append(f"A proposal for '{proposal.slot_id}' was left out: it is not an open item a client can answer.")
            continue
        text = "\n".join(proposal.value) if isinstance(proposal.value, list) else proposal.value
        missing = qa.unmatched_numbers(text, reply)
        if missing:
            result.rejected.append(f"{state_.slot.label}: left out, because {', '.join(f'{n:g}' for n in missing)} is not in the reply.")
            continue
        try:
            value = om_slots.validate(state_.slot, proposal.value)
        except om_slots.InvalidValue as error:
            result.rejected.append(f"{state_.slot.label}: left out ({error})")
            continue
        result.proposals.append({"slot_id": state_.slot.id, "label": state_.slot.label,
                                 "before": state_.display if state_.status != "empty" else "(empty)",
                                 "after": om_slots_display(value), "value": value, "quote": proposal.quote[:200]})
    return result


def om_slots_display(value):
    return "; ".join(value) if isinstance(value, list) else str(value)


def apply(deal_id, proposal, user, origin="client_reply", db_path=None):
    """A person clicked Apply on one proposal: save it as their value, waiting for approval."""
    source = {"kind": origin, "detail": f"{CLIENT_SOURCES[origin]}, read by AI and applied by {user}"}
    om_slots.set_value(deal_id, proposal["slot_id"], proposal["value"], user, source=source, db_path=db_path)
    mark_answered(deal_id, [proposal["slot_id"]], db_path)


# ---------- documents the client sends ----------

def document_text(name, data):
    """Plain text from a document, or ValueError saying plainly why it cannot be read."""
    suffix = Path(name or "").suffix.lower()
    if suffix not in DOCUMENT_TYPES:
        raise ValueError(f"{name}: this file type is not supported here. Use a PDF, TXT, CSV or MD file, or type the answer.")
    if suffix == ".pdf":
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise ValueError(f"{name}: this PDF is locked (Needs password). Ask the client for an unlocked copy.")
            text = "\n".join(page.extract_text() or "" for page in reader.pages[:20])
        except ValueError:
            raise
        except Exception:
            raise ValueError(f"{name}: this PDF could not be read.") from None
        if not text.strip():
            raise ValueError(f"{name}: no text was found (it may be a scan). Type the answer instead.")
    else:
        text = data.decode("utf-8", errors="replace")
    return text[:20000]
