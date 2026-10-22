"""Q&A service: a chat that answers only from deal data saved in SQLite.

ask() is limited to one deal. ask_all() covers every deal and reports which deals it used.

Every answer carries a label. "From this deal" (or "From these deals") is only
used when Gemini says the answer is in the data, names a real source, and every
number in the answer can be found in the data it cites. Otherwise the label is
"Not verified".
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError

import db
from services import gemini

LABEL_FROM_DEAL = "From this deal"
LABEL_FROM_DEALS = "From these deals"
LABEL_NOT_VERIFIED = "Not verified"
NOT_IN_DEAL = "I don't have that in this deal."
NOT_IN_ANY_DEAL = "I don't have that in any of the deals."
NO_NUMBERS_YET = "This deal's documents have not been read yet, so there is nothing I can answer from. " + NOT_IN_DEAL
UNMATCHED_NOTE = ("Treat this as not verified: it includes a figure or a source "
                  "I could not match to this deal's data.")
FLAGS_SOURCE = "Validation flags"
HISTORY_TURNS = 6

UNIT_FIELDS = ["unit_number", "tenant_name", "square_feet", "lease_start", "lease_end",
               "monthly_rent", "annual_rent", "rent_per_sf", "lease_type"]

PROMPT = """You answer questions about one commercial real estate deal for a broker or analyst.

Rules:
- Use ONLY the DEAL DATA below. Do not use outside knowledge, market opinions or guesses.
- If the answer is not in the DEAL DATA, set found_in_deal to false and set answer to "{not_in_deal}"
- Copy figures exactly as they appear in the DEAL DATA. Do not round or estimate.
- In sources, list the names from "Sources you may cite" that your answer came from.
- Answer in one to three plain sentences. No lists, no headings.

DEAL DATA
{context}

EARLIER IN THIS CHAT
{history}

QUESTION
{question}
"""


ALL_DEALS_PROMPT = """You answer questions about a set of commercial real estate deals for a broker or analyst.

Rules:
- Use ONLY the DEAL DATA below. Do not use outside knowledge, market opinions or guesses.
- If the answer is not in the DEAL DATA, set found_in_deals to false and set answer to "{not_in_deal}"
- Copy figures exactly as they appear in the DEAL DATA. Do not round or estimate.
- In deals_used, list the exact deal names your answer came from.
- In sources, list the names from each deal's "Sources you may cite" that your answer came from.
- Answer in one to three plain sentences. No lists, no headings.

DEAL DATA
{context}

EARLIER IN THIS CHAT
{history}

QUESTION
{question}
"""


class QaAllReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    found_in_deals: bool
    deals_used: list[str]
    sources: list[str]


class QaReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    found_in_deal: bool
    sources: list[str]


@dataclass(frozen=True)
class Answer:
    text: str
    label: str
    sources: list[str] = field(default_factory=list)
    note: str = ""
    deals: list[str] = field(default_factory=list)


def _rows(conn, sql, deal_id):
    return [dict(row) for row in conn.execute(sql, (deal_id,))]


def load_deal_data(deal_id, db_path=None):
    """Read everything the chat is allowed to use for one deal."""
    conn = db.get_connection(db_path)
    try:
        return {
            "deal": _rows(conn, "SELECT name, property_type, submarket, status FROM deals WHERE id = ?", deal_id),
            "documents": _rows(conn, "SELECT filename, doc_type, status FROM documents WHERE deal_id = ? ORDER BY id", deal_id),
            "units": _rows(conn, "SELECT * FROM rent_roll_units WHERE deal_id = ? ORDER BY id", deal_id),
            "t12": _rows(conn, "SELECT category, line_item, period, amount FROM t12_line_items WHERE deal_id = ? ORDER BY id", deal_id),
            "flags": _rows(conn, "SELECT unit_number, rule, message, status FROM flags WHERE deal_id = ? ORDER BY id", deal_id),
        }
    finally:
        conn.close()


def _numeric(values):
    return [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _rent_roll_totals(units):
    """Totals worked out in plain Python, so common questions do not rely on the AI's arithmetic."""
    sf = sum(_numeric(u["square_feet"] for u in units))
    annual = sum(_numeric(u["annual_rent"] for u in units))
    lines = [
        f"Number of units: {len(units)}",
        f"Total square feet: {sf:.2f}",
        f"Total monthly rent: {sum(_numeric(u['monthly_rent'] for u in units)):.2f}",
        f"Total annual rent: {annual:.2f}",
    ]
    if sf:
        lines.append(f"Building average rent per SF (total annual rent / total SF): {annual / sf:.2f}")
    return lines


def allowed_sources(data):
    names = [doc["filename"] for doc in data["documents"]]
    return names + [FLAGS_SOURCE] if data["flags"] else names


def build_context(data):
    """The deal data as plain text for the prompt."""
    lines = []
    for deal in data["deal"]:
        lines.append(f"Deal: {deal['name']} | type: {deal['property_type']} | "
                     f"submarket: {deal['submarket']} | status: {deal['status']}")
    lines.append("\nDocuments (filename | type | status):")
    lines += [f"{d['filename']} | {d['doc_type']} | {d['status']}" for d in data["documents"]]
    if data["units"]:
        lines.append("\nRent roll (" + " | ".join(UNIT_FIELDS) + "):")
        lines += [" | ".join(str(unit[f]) for f in UNIT_FIELDS) for unit in data["units"]]
        lines.append("\nRent roll totals (calculated from the rows above):")
        lines += _rent_roll_totals(data["units"])
    if data["t12"]:
        lines.append("\nT-12 operating statement (category | line item | period | amount):")
        lines += [f"{t['category']} | {t['line_item']} | {t['period']} | {t['amount']}" for t in data["t12"]]
    lines.append("\nValidation flags (unit | rule | message | status: open, confirmed by a person, or corrected):")
    lines += [f"{f['unit_number']} | {f['rule']} | {f['message']} | {f.get('status', 'open')}" for f in data["flags"]] or ["None"]
    lines.append("\nSources you may cite: " + "; ".join(allowed_sources(data)))
    return "\n".join(lines)


def _numbers(text):
    """Every number in a piece of text, ignoring commas and currency signs."""
    found = set()
    for token in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        found.add(round(float(token.replace(",", "")), 2))
    return found


def _percents(text):
    """Every number written as a percentage."""
    return {round(float(token.replace(",", "")), 2) for token in re.findall(r"(\d[\d,]*(?:\.\d+)?)\s*%", text)}


def unmatched_numbers(answer_text, context):
    """Numbers in the answer that do not appear anywhere in the deal data.

    A percentage must appear as a percentage: otherwise "9%" would match the 09 in a date.
    """
    return sorted((_numbers(answer_text) - _numbers(context)) | (_percents(answer_text) - _percents(context)))


def _history_text(history):
    turns = [f"{turn['role']}: {turn['text']}" for turn in history[-HISTORY_TURNS:]]
    return "\n".join(turns) or "(nothing yet)"


def label_reply(reply, data, context):
    """Turn Gemini's reply into a labelled answer, downgrading anything that cannot be matched."""
    if not reply.found_in_deal:
        return Answer(NOT_IN_DEAL, LABEL_NOT_VERIFIED)
    sources = [s for s in reply.sources if s in allowed_sources(data)]
    if not sources or unmatched_numbers(reply.answer, context):
        return Answer(reply.answer, LABEL_NOT_VERIFIED, sources, UNMATCHED_NOTE)
    return Answer(reply.answer, LABEL_FROM_DEAL, sources)


def _config(reply_model=QaReply):
    return types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
        response_json_schema=reply_model.model_json_schema(),
    )


def _generate(reply_model, prompt, client, model):
    raw = gemini.generate(client or gemini.get_client(), prompt, _config(reply_model), model)
    try:
        return reply_model.model_validate_json(raw)
    except ValidationError as exc:
        raise gemini.GeminiError("Gemini's reply was not in the expected format.") from exc


def _overview(all_data):
    """Counts across every deal, worked out in plain Python."""
    statuses = Counter(data["deal"][0]["status"] for data in all_data)
    lines = [f"Number of deals: {len(all_data)}"]
    lines += [f"Deals with status {status}: {count}" for status, count in statuses.items()]
    lines.append(f"Validation flags across all deals: {sum(len(data['flags']) for data in all_data)}")
    return "\n".join(lines)


def label_all_reply(reply, all_data, contexts, overview):
    """Label an all-deals reply, checking it only against the deals it says it used."""
    if not reply.found_in_deals:
        return Answer(NOT_IN_ANY_DEAL, LABEL_NOT_VERIFIED)
    deals = [name for name in reply.deals_used if name in contexts]
    allowed = [s for data in all_data if data["deal"][0]["name"] in deals for s in allowed_sources(data)]
    sources = [s for s in dict.fromkeys(reply.sources) if s in allowed]
    cited = overview + "\n" + "\n".join(contexts[name] for name in deals)
    if not deals or not sources or unmatched_numbers(reply.answer, cited):
        return Answer(reply.answer, LABEL_NOT_VERIFIED, sources, UNMATCHED_NOTE, deals)
    return Answer(reply.answer, LABEL_FROM_DEALS, sources, deals=deals)


def ask_all(question, history=(), client=None, db_path=None, model=None):
    """Answer one question from every deal in the database, naming the deals the answer used."""
    conn = db.get_connection(db_path)
    try:
        deal_ids = [row["id"] for row in conn.execute("SELECT id FROM deals ORDER BY id")]
    finally:
        conn.close()
    all_data = [load_deal_data(deal_id, db_path) for deal_id in deal_ids]
    if not all_data:
        return Answer(NOT_IN_ANY_DEAL, LABEL_NOT_VERIFIED)
    contexts = {data["deal"][0]["name"]: build_context(data) for data in all_data}
    overview = _overview(all_data)
    context = "ALL DEALS\n" + overview + "".join(f"\n\n=== {name} ===\n{text}" for name, text in contexts.items())
    prompt = ALL_DEALS_PROMPT.format(not_in_deal=NOT_IN_ANY_DEAL, context=context,
                                     history=_history_text(list(history)), question=question)
    return label_all_reply(_generate(QaAllReply, prompt, client, model), all_data, contexts, overview)


def ask(deal_id, question, history=(), client=None, db_path=None, model=None):
    """Answer one question about one deal. Raises gemini.GeminiError if Gemini cannot be reached."""
    data = load_deal_data(deal_id, db_path)
    if not data["units"] and not data["t12"]:
        return Answer(NO_NUMBERS_YET, LABEL_NOT_VERIFIED)
    context = build_context(data)
    prompt = PROMPT.format(not_in_deal=NOT_IN_DEAL, context=context,
                           history=_history_text(list(history)), question=question)
    return label_reply(_generate(QaReply, prompt, client, model), data, context)
