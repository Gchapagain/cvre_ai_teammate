"""Understand a correction a person describes in their own words ("unit 110's rent should be $2,400").

One Gemini request turns the text into proposed changes. Code then checks every proposal: the unit
must be in this deal, the field must be editable, the value must have the right type, and every
number in it must appear in what the person wrote. Nothing is saved here: a person clicks Apply,
and the change goes through services/corrections like any manual edit, marked "AI-assisted".
"""

from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError

import db
from services import corrections, gemini, qa

PROMPT = """A broker is correcting values that were extracted from a rent roll. Turn what they wrote into changes.

Rules:
- Change only what the broker clearly asked for. Never guess a value or change anything else.
- unit: the unit number exactly as listed below. field: one of {fields}.
- new_value: the value the broker gave, written plainly (numbers without currency signs; dates as YYYY-MM-DD).
- Do not work out other fields from the change (the app recomputes annual rent and rent/SF itself).
- If anything is unclear (which unit, which field, or what value), propose no change for it and ask one short
  question in questions instead.
- interpretation: one plain sentence saying what you understood.

{flag}
UNITS IN THIS DEAL (unit | {fields} | rent_per_sf)
{units}

WHAT THE BROKER WROTE
{text}
"""


class ProposedChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: str
    field: str
    new_value: str


class CorrectionReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interpretation: str
    changes: list[ProposedChange]
    questions: list[str]


def _units(deal_id, db_path):
    conn = db.get_connection(db_path)
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM rent_roll_units WHERE deal_id = ? ORDER BY id", (deal_id,))]
    finally:
        conn.close()


def build_prompt(text, units, flag=None):
    fields = list(corrections.EDITABLE)
    rows = [" | ".join([str(u["unit_number"])] + [str(u.get(f)) for f in fields] + [str(u.get("rent_per_sf"))]) for u in units]
    about = f"THE FLAG BEING RESOLVED\nUnit {flag['unit_number']}: {flag['message']}\n" if flag else ""
    return PROMPT.format(fields=", ".join(fields), flag=about, units="\n".join(rows), text=text.strip())


def check(reply, units, text):
    """Group valid proposals by unit and plan them; drop and explain anything that cannot be applied."""
    by_number = {str(u["unit_number"]): u for u in units}
    wanted, dropped = {}, []
    for change in reply.changes:
        label = corrections.LABELS.get(change.field, change.field)
        unit = by_number.get(change.unit.strip())
        if unit is None:
            dropped.append(f"unit {change.unit} is not in this deal")
            continue
        if change.field not in corrections.EDITABLE:
            dropped.append(f"{label} on unit {change.unit} cannot be edited")
            continue
        try:
            value = corrections.parse(change.field, change.new_value)
        except ValueError as exc:
            dropped.append(f"unit {change.unit}: {exc}")
            continue
        if qa.unmatched_numbers(change.new_value, text):
            dropped.append(f"unit {change.unit} {label}: the value {change.new_value} is not in what you wrote")
            continue
        if value == unit.get(change.field):
            dropped.append(f"unit {change.unit} {label} is already {change.new_value}")
            continue
        wanted.setdefault(unit["id"], (unit, {}))[1][change.field] = change.new_value
    proposals = []
    for unit, values in wanted.values():
        changes, errors = corrections.plan(unit, values)
        dropped += [f"unit {unit['unit_number']}: {e}" for e in errors]
        if changes:
            proposals.append({"unit_id": unit["id"], "unit_number": unit["unit_number"], "values": values, "changes": changes})
    return proposals, dropped


def understand(deal_id, text, flag=None, client=None, db_path=None, model=None, record_to=None, replay_from=None):
    """One Gemini request. Returns {"interpretation", "proposals", "dropped", "questions"}. Saves nothing.

    replay_from: use the Gemini reply saved in this file instead of calling the API.
    record_to: after a live call, save Gemini's reply to this file.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Tell me what is wrong first.")
    units = _units(deal_id, db_path)
    prompt = build_prompt(text, units, flag)
    if replay_from:
        raw = gemini.load_recording(replay_from, prompt)
    else:
        config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                             response_json_schema=CorrectionReply.model_json_schema())
        raw = gemini.generate(client or gemini.get_client(), prompt, config, model)
        if record_to:
            gemini.save_recording(record_to, prompt, raw, model)
    try:
        reply = CorrectionReply.model_validate_json(raw)
    except ValidationError as exc:
        raise gemini.GeminiError("Gemini's reply was not in the expected format.") from exc
    proposals, dropped = check(reply, units, text)
    return {"interpretation": reply.interpretation.strip(), "proposals": proposals, "dropped": dropped,
            "questions": [q.strip() for q in reply.questions if q.strip()]}
