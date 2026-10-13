"""Starting a new deal, either from uploaded files or from a description the AI turns into a draft.

The AI never saves anything here. draft_from_description only returns a draft for a
person to edit; a deal is created when the person presses Create deal.
"""

import re
from dataclasses import dataclass, field

from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError

from services import deals, extraction, gemini, pipeline, qa

RENT_ROLL, T12, UNKNOWN = "Rent roll", "T-12", "Not recognised"
T12_NOT_BUILT = "Saved, not read: reading T-12 files is not built yet."
ONE_RENT_ROLL = "Saved, not read: only the first rent roll in an upload is read."
NOT_RECOGNISED = "Saved, not read: this does not look like a rent roll or a T-12."

DRAFT_PROMPT = """A commercial real estate broker is describing a new deal. Fill in a draft from what they said.

Rules:
- Use ONLY what the description states. Never guess, estimate or add outside knowledge.
- name: the property or deal name, only if they gave one. Otherwise null. Do not make one up.
- property_type: one of {types}, only if the description makes it clear. Otherwise null.
- location: the city, area or address exactly as they said it. Otherwise null.
- facts: every other fact they stated, one short sentence each, with figures copied exactly. Empty if none.

DESCRIPTION
{description}
"""


class DraftReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None
    property_type: str | None
    location: str | None
    facts: list[str]


@dataclass
class DealDraft:
    """A draft for a person to check. Blank means the description did not say."""

    name: str = ""
    property_type: str | None = None
    location: str = ""
    facts: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)  # what the check below took out, in plain words


def _plain(text):
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def check_draft(reply, description):
    """Keep only what can be matched to the description. Anything else is blanked, not trusted."""
    said, draft = _plain(description), DealDraft()
    for label, value in (("name", reply.name), ("location", reply.location)):
        if value and _plain(value) in said:
            setattr(draft, label, value.strip())
        elif value:
            draft.removed.append(f"{label} '{value}' (not in what you wrote)")
    if reply.property_type in deals.PROPERTY_TYPES:
        draft.property_type = reply.property_type
    for fact in reply.facts:
        if qa.unmatched_numbers(fact, description):
            draft.removed.append(f"'{fact}' (has a number you did not give)")
        elif fact.strip():
            draft.facts.append(fact.strip())
    return draft


def draft_from_description(description, client=None, model=None):
    """Ask Gemini for a draft deal. Raises gemini.GeminiError if it cannot be reached. Saves nothing."""
    description = (description or "").strip()
    if not description:
        raise ValueError("Describe the deal first.")
    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                         response_json_schema=DraftReply.model_json_schema())
    prompt = DRAFT_PROMPT.format(types=", ".join(deals.PROPERTY_TYPES), description=description)
    raw = gemini.generate(client or gemini.get_client(), prompt, config, model)
    try:
        reply = DraftReply.model_validate_json(raw)
    except ValidationError as exc:
        raise gemini.GeminiError("Gemini's reply was not in the expected format.") from exc
    return check_draft(reply, description)


def create_from_draft(name, property_type, location, notes, db_path=None):
    """Save a deal a person has checked. Any notes are saved as one typed note."""
    deal_id = deals.create_deal(name, property_type, location, status="New", db_path=db_path)
    if (notes or "").strip():
        deals.add_note(deal_id, notes, "Typed", db_path)
    return deal_id


def classify(path):
    """Work out what an uploaded file is by looking at its headings. No AI involved."""
    try:
        rows = extraction.read_sheet_rows(path)
    except extraction.ExtractionError:
        return UNKNOWN
    if rows and not min((extraction._missing_columns(row) for row in rows), key=len):
        return RENT_ROLL
    cells = {cell.strip().lower() for row in rows for cell in row}
    return T12 if cells & {"net operating income", "line item", "total income"} else UNKNOWN


def _read_rent_roll(deal_id, path, document_id, client, db_path):
    """Run extraction and validation on one rent roll. Returns (summary or None, message)."""
    try:
        summary = pipeline.process_deal(path, deal_id, client=client, db_path=db_path, document_id=document_id)
    except extraction.ExtractionError as exc:
        return None, "Saved, not read: " + str(exc).replace(" Nothing was saved.", "")
    flags = summary["flags_raised"]
    return summary, f"Read: {summary['units_saved']} units, {flags} flag{'' if flags == 1 else 's'}."


def create_from_uploads(name, property_type, location, files, client=None, db_path=None, upload_dir=None,
                        progress=lambda message: None):
    """Create a deal from uploaded files: save every file, then read the first rent roll.

    files is a list of (filename, bytes). The deal and its files are saved even if nothing
    can be read (for example when the AI quota is used up); they stay as Received.
    """
    deal_id = deals.create_deal(name, property_type, location, status="Extracting", db_path=db_path)
    progress(f"Created the deal '{name.strip()}'.")
    result = {"deal_id": deal_id, "files": [], "read": False, "units_saved": 0, "flags_raised": 0}
    for filename, data in files:
        document_id, path = deals.save_upload(deal_id, filename, data, db_path, upload_dir)
        kind = classify(path)
        deals.set_document_type(document_id, None if kind == UNKNOWN else kind, db_path)
        progress(f"Saved {path.name} ({kind}).")
        message = {T12: T12_NOT_BUILT, UNKNOWN: NOT_RECOGNISED}.get(kind, ONE_RENT_ROLL)
        if kind == RENT_ROLL and not result["read"] and not result.get("tried"):
            result["tried"] = True
            progress(f"Reading {path.name} with the AI...")
            summary, message = _read_rent_roll(deal_id, path, document_id, client, db_path)
            if summary:
                result.update(read=True, units_saved=summary["units_saved"], flags_raised=summary["flags_raised"])
        result["files"].append({"filename": path.name, "kind": kind, "message": message})
    result.pop("tried", None)
    if result["read"]:
        deals.set_status(deal_id, "Needs Review", db_path)
    return result
