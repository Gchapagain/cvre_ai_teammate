"""AI drafts for the OM, each one Gemini request and only on a click.

- draft_all_text: The Offering, the three highlight lists and (only when accepted research exists) the
  location overview, written from this deal's saved data. Code checks every number in each piece against
  the facts given; a piece with a number that is not there is dropped and reported. Drafts are saved as
  "ai-draft" (never over a person's own value or an approved one) and count only once a person approves.
  When no accepted research exists, the location is not drafted: it becomes a question for the broker.
- propose_assumptions: the cash-flow assumptions the broker has not approved yet, proposed by the AI with a
  reason each, saved as "proposed". They are never used in any calculation until the broker approves each.
The AI never writes the price, a cap rate or any calculated number.
"""

import json
from datetime import date

from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError

import db
from services import gemini, om_calc, om_slots, qa

TEXT_SLOTS = {"offering": "offering.narrative", "upside": "highlights.upside",
              "location_building": "highlights.location_building", "rare": "highlights.rare",
              "location": "location.narrative"}
NO_RESEARCH = ("No accepted research for {market} yet, so the AI did not write the location. Describe it yourself, "
               "or run research on the Review tab and accept what is useful.")

DRAFT_PROMPT = """OFFERING MEMORANDUM TEXT. Write marketing text for a commercial real estate offering memorandum.

Rules:
- Use ONLY the FACTS and ACCEPTED RESEARCH below. No outside knowledge. Never invent features, tenants or places.
- Copy any figure exactly as written below. Never estimate, round differently, or combine figures.
- Never state a price, value, cap rate, return or projection.
- offering: 2 to 3 sentences on what is for sale and why it is attractive.
- upside, location_building, rare: 2 or 3 short bullet points each (rare may have 1).
- location: 2 to 3 sentences from the ACCEPTED RESEARCH only, or null if it is "None".
- Return JSON: {{"offering": "...", "upside": ["..."], "location_building": ["..."], "rare": ["..."], "location": "..." or null}}

FACTS
{facts}

ACCEPTED RESEARCH
{research}
"""


class DraftReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offering: str
    upside: list[str]
    location_building: list[str]
    rare: list[str]
    location: str | None = None


def accepted_research(deal_id, db_path=None):
    """Real (never simulated) findings a person accepted, as text lines."""
    conn = db.get_connection(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT topic, summary, sources FROM research_findings WHERE deal_id = ? AND status = 'accepted' "
            "AND COALESCE(simulated, 0) = 0 ORDER BY id", (deal_id,))]
    except Exception:
        rows = []
    finally:
        conn.close()
    lines = []
    for row in rows:
        names = ", ".join(s.get("name", "") for s in json.loads(row["sources"] or "[]") if s.get("name"))
        lines.append(f"{row['topic']}: {row['summary']}" + (f" (source: {names})" if names else ""))
    return lines


def _lease_lines(units, today):
    soon = [u for u in units if not om_calc.is_vacant(u) and u.get("lease_end")
            and str(u["lease_end"]) <= f"{today.year + 2}-{today:%m-%d}"]
    return [f"Leases ending within 24 months: {len(soon)} of {len(units)} units"] if units else []


def facts_text(facts, today=None):
    """The deal's facts as plain lines, with figures exactly as the OM shows them."""
    deal = facts.get("deal") or {}
    lines = [f"Property: {deal.get('name')}", f"Type: {deal.get('property_type')}", f"Market: {deal.get('submarket')}"]
    for label, calc in (("Units", om_calc.unit_count(facts)), ("Total size", om_calc.total_sf(facts)),
                        ("Average unit size", om_calc.avg_unit_size(facts)), ("Leased", om_calc.leased_pct(facts))):
        if calc.ready:
            lines.append(f"{label}: {calc.display}")
    tenants = sorted({u["tenant_name"] for u in facts.get("units", []) if not om_calc.is_vacant(u)})
    if tenants:
        lines.append(f"Tenants: {len(tenants)}")
    types_ = sorted({u.get("lease_type") for u in facts.get("units", []) if u.get("lease_type")})
    if types_:
        lines.append(f"Lease types: {', '.join(types_)}")
    lines += _lease_lines(facts.get("units", []), today or date.today())
    for slot_id in ("property.buildings", "property.year_built", "property.land_size", "property.bay_doors",
                    "property.clear_height", "property.city_state"):
        row = facts.get("rows", {}).get(slot_id)
        if row and row.get("value") not in (None, ""):
            lines.append(f"{slot_id.split('.')[1].replace('_', ' ').capitalize()}: {row['value']}")
    return "\n".join(lines)


def _writable(state, slot_id):
    """AI text may fill an empty slot or replace an earlier AI draft, never a person's value or an approval."""
    slot_state = state.slots.get(slot_id)
    return slot_state is not None and (slot_state.status == "empty" or slot_state.status == "ai-draft")


def draft_all_text(deal_id, facts, state, user, client=None, db_path=None, today=None):
    """One Gemini request. Returns {saved: [labels], dropped: [reasons], skipped: [labels], questions: [text]}."""
    targets = [key for key, slot_id in TEXT_SLOTS.items() if _writable(state, slot_id)]
    result = {"saved": [], "dropped": [], "skipped": [], "questions": []}
    for key, slot_id in TEXT_SLOTS.items():
        if key not in targets and slot_id in state.slots:
            result["skipped"].append(state.slots[slot_id].slot.label)
    if not targets:
        return result
    research = accepted_research(deal_id, db_path)
    fact_lines = facts_text(facts, today)
    prompt = DRAFT_PROMPT.format(facts=fact_lines, research="\n".join(research) or "None")
    config = types.GenerateContentConfig(temperature=0.3, response_mime_type="application/json")
    reply = gemini.generate(client or gemini.get_client(), prompt, config)
    try:
        draft = DraftReply.model_validate(json.loads(reply))
    except (ValueError, ValidationError):
        raise gemini.GeminiError("The AI's reply could not be read. Nothing was saved.") from None
    allowed = fact_lines + "\n" + "\n".join(research)
    market = (facts.get("deal") or {}).get("submarket") or "this market"
    for key in targets:
        slot_id = TEXT_SLOTS[key]
        label = state.slots[slot_id].slot.label
        value = getattr(draft, key)
        if key == "location" and (not research or not value):
            result["questions"].append(NO_RESEARCH.format(market=market))
            continue
        text = "\n".join(value) if isinstance(value, list) else str(value or "")
        missing = qa.unmatched_numbers(text, allowed)
        if missing:
            result["dropped"].append(f"{label}: not saved, because {', '.join(f'{n:g}' for n in missing)} is not in the deal's data.")
            continue
        source = {"kind": "ai_text", "detail": "Drafted by AI from this deal's data" + (" and accepted research" if key == "location" else "")
                  + f"; requested by {user}. Check before approving."}
        try:
            om_slots.set_value(deal_id, slot_id, value, user, status="ai-draft", source=source, db_path=db_path)
        except om_slots.InvalidValue as error:
            result["dropped"].append(f"{label}: not saved ({error})")
            continue
        result["saved"].append(label)
    return result


ASSUMPTION_PROMPT = """CASH FLOW ASSUMPTIONS. Propose starting assumptions for a 5-year cash flow of this property.
The broker will check and approve or change every one; label them as proposals, not facts.

Give only these keys: {keys}.
- market_rent_psf: annual market rent per SF in dollars. escalation_pct, expense_growth_pct, vacancy_pct,
  management_fee_pct: percentages. occupancy_by_year: five percentages for years 1 to 5.
- why: one short reason for each, naming which fact or research line it rests on. If you have no basis, say so.
- Never propose a price, value or cap rate.
- Return JSON: {{"assumptions": [{{"key": "...", "value": <number or list of 5 numbers>, "why": "..."}}]}}

FACTS
{facts}

IN-PLACE RENT PER SF (from the rent roll)
{rents}

ACCEPTED RESEARCH
{research}
"""


class AssumptionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    value: float | list[float]
    why: str


class AssumptionReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assumptions: list[AssumptionProposal]


def propose_assumptions(deal_id, facts, user, client=None, db_path=None):
    """One Gemini request. Saves each valid proposal as 'proposed'. Returns {saved: [labels], dropped: [reasons]}."""
    approved = om_calc.approved_assumptions(facts)
    keys = [key for key in om_calc.ASSUMPTIONS if key not in approved]
    result = {"saved": [], "dropped": []}
    if not keys:
        return result
    rents = [f"Unit {u['unit_number']}: {u['rent_per_sf']}" for u in facts.get("units", [])
             if isinstance(u.get("rent_per_sf"), (int, float))]
    prompt = ASSUMPTION_PROMPT.format(keys=", ".join(keys), facts=facts_text(facts), rents="\n".join(rents) or "None",
                                      research="\n".join(accepted_research(deal_id, db_path)) or "None")
    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json")
    reply = gemini.generate(client or gemini.get_client(), prompt, config)
    try:
        proposals = AssumptionReply.model_validate(json.loads(reply)).assumptions
    except (ValueError, ValidationError):
        raise gemini.GeminiError("The AI's reply could not be read. Nothing was saved.") from None
    for proposal in proposals:
        if proposal.key not in keys:
            continue
        label = om_calc.ASSUMPTIONS[proposal.key][0]
        raw = ", ".join(f"{v:g}" for v in proposal.value) if isinstance(proposal.value, list) else proposal.value
        source = {"kind": "ai_proposal", "detail": f"AI proposal, not from a document: {proposal.why[:240]}"}
        try:
            om_slots.set_assumption(deal_id, proposal.key, raw, user, status="proposed", source=source, db_path=db_path)
        except om_slots.InvalidValue as error:
            result["dropped"].append(f"{label}: not saved ({error})")
            continue
        result["saved"].append(label)
    return result
