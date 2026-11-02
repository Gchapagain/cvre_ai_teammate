"""The AI Teammate's autopilot for the OM: fills as much as it can on its own, in the background.

Approved by the user (2026-10-31): it runs by itself when a deal page is opened, without a click, within the
app's AI limits (as the session "ai-teammate", so it counts toward the daily limit and has its own hourly limit).
Set OM_AUTOPILOT=off to stop it. Each step does work only when something is new, so opening a deal again
costs nothing when nothing changed.

Steps, in order:
1. Deal record (code): city and state from the deal's location. A sourced fact: approved automatically.
2. Emails (1 Gemini request when the deal has emails not read yet): property facts (address, buildings, land,
   year built, doors, clear height). A value is kept only when its exact words are in the email and every
   number is in them; kept values are sourced facts, approved automatically and cite the email.
3. Market research (the switched-on Connections; results under 24 hours old are reused). Web searches use
   generic terms only (property type + location), never the property's name. Real findings whose every
   figure was checked against the source's own text, from a Tier 1-3 source, are accepted automatically.
4. Text (1 request when its inputs changed): The Offering, highlights and the location (from accepted research
   only). Saved as AI drafts: prose is not a sourced fact, so a person approves it.
5. Assumptions (1 request, once): proposed only. The cash flow never uses them until the broker approves.
6. Photos: unsorted photos are sorted (1 request per 8) and placed on slides by code. A person approves them.
7. Sourced numbers (code): values calculated from the deal's documents are approved automatically, except
   anything that depends on the price until the broker has approved the price, and anything a person took
   an approval back from. The price is only ever set by the broker.
"""

import hashlib
import json
import logging
import os
import re
import threading
import time
from datetime import datetime

from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError

import db
from services import ai_limits, gemini, om_assets, om_calc, om_drafting, om_engine, om_facts, om_slots, qa

log = logging.getLogger(__name__)

ACTOR = "AI Teammate"
SESSION = "ai-teammate"
EMAIL_SLOTS = ("property.address", "property.city_state", "property.buildings", "property.land_size",
               "property.year_built", "property.bay_doors", "property.clear_height")
TEXT_SLOTS = tuple(om_drafting.TEXT_SLOTS.values())
# Slots the autopilot fills or tries to fill itself, so the broker is not asked while it is working.
HANDLED = set(EMAIL_SLOTS) | set(TEXT_SLOTS)
PRICE_DEPENDENT = {"financial.price_per_sf", "financial.cap_rate_y4"}
STEP_NAMES = {"record": "Reading the deal record", "emails": "Reading the deal's emails", "research": "Researching the market",
              "text": "Writing the OM text", "assumptions": "Proposing cash-flow assumptions",
              "photos": "Sorting and placing photos", "approve": "Approving sourced numbers"}

_lock = threading.Lock()
_runs = {}          # deal_id -> {"running", "step", "started", "finished", "lines"}
_switched_off = False  # set by tests/conftest.py, so no change to the environment can switch it back on


def switch_off():
    """Turn the autopilot off for this whole process (tests). Stronger than OM_AUTOPILOT=off."""
    global _switched_off
    _switched_off = True


def enabled():
    if _switched_off:
        return False
    return os.getenv("OM_AUTOPILOT", "on").lower() not in ("off", "0", "false", "no")


def allowed_steps():
    chosen = os.getenv("OM_AUTOPILOT_STEPS")
    return set(chosen.split(",")) if chosen else set(STEP_NAMES)


def status(deal_id):
    with _lock:
        return dict(_runs.get(deal_id) or {})


# ---------- memory: what was already done, kept in om_events ----------

def last_memory(conn, deal_id):
    row = conn.execute("SELECT detail FROM om_events WHERE deal_id = ? AND action = 'autopilot' ORDER BY id DESC LIMIT 1",
                       (deal_id,)).fetchone()
    try:
        return json.loads(row["detail"]) if row else {}
    except (TypeError, ValueError):
        return {}


def _fingerprint(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ---------- step 1: the deal record ----------

def city_state_from(submarket):
    """'Alliance, Fort Worth, TX' -> 'Fort Worth, TX'; None when the location does not end in 'City, ST'."""
    match = re.search(r"([A-Za-z .'-]+),\s*([A-Z]{2})\s*$", submarket or "")
    return f"{match.group(1).strip()}, {match.group(2)}" if match else None


def _approve_value(deal_id, slot_id, value, detail, db_path):
    """Save a sourced fact and approve it in one step, as the AI Teammate."""
    om_slots.set_value(deal_id, slot_id, value, ACTOR, source={"kind": "sourced", "detail": detail}, db_path=db_path)
    conn = db.get_connection(db_path)
    try:
        state = om_engine.build(om_facts.load(conn, deal_id)).slots[slot_id]
    finally:
        conn.close()
    om_slots.approve(deal_id, [state], f"{ACTOR} (sourced fact, approved automatically)", db_path)


def step_record(deal_id, facts, state, db_path):
    lines = []
    city = city_state_from((facts.get("deal") or {}).get("submarket"))
    slot = state.slots.get("property.city_state")
    if city and slot is not None and slot.status == "empty":
        _approve_value(deal_id, "property.city_state", city, f"Deal record, location: {facts['deal']['submarket']}", db_path)
        lines.append(f"City and state from the deal record: {city}")
    return lines


# ---------- step 2: emails ----------

EMAIL_PROMPT = """PROPERTY FACTS FROM EMAILS. Find facts about the property in these emails sent to a commercial real estate broker.

Rules:
- Only these items: {items}.
- quote: the exact words from the email (copy them character for character). value: the fact, plainly.
- Never guess, convert units or combine figures. Skip anything unclear.
- Return JSON: {{"facts": [{{"slot_id": "...", "value": "...", "quote": "...", "email_id": <number>}}]}}

EMAILS
{emails}"""


class EmailFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: str
    value: str
    quote: str
    email_id: int


class EmailReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[EmailFact]


def deal_emails(conn, deal_id):
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, sender, subject, preview, received_at FROM emails WHERE deal_id = ? AND status != 'dismissed' "
            "ORDER BY id", (deal_id,))]
    except Exception:
        return []


def step_emails(deal_id, state, emails, client, db_path):
    """Returns (lines, ids read). Uses one request when there is something to look for."""
    open_slots = [s for s in EMAIL_SLOTS if s in state.slots and state.slots[s].status == "empty"]
    if not emails or not open_slots:
        return [], [e["id"] for e in emails]
    labels = {s: state.slots[s].slot.label for s in open_slots}
    text = "\n\n".join(f"[email {e['id']}] From {e['sender']}, subject: {e['subject']}\n{e['preview'] or ''}" for e in emails)
    prompt = EMAIL_PROMPT.format(items=", ".join(f"{s} ({labels[s]})" for s in open_slots), emails=text)
    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json")
    reply = gemini.generate(client or gemini.get_client(), prompt, config)
    try:
        found = EmailReply.model_validate(json.loads(reply)).facts
    except (ValueError, ValidationError):
        raise gemini.GeminiError("The AI's reply about the emails could not be read.") from None
    by_id, lines = {e["id"]: e for e in emails}, []
    for fact in found:
        email = by_id.get(fact.email_id)
        if fact.slot_id not in open_slots or email is None:
            continue
        body = f"{email['subject']} {email['preview'] or ''}"
        if not fact.quote.strip() or fact.quote.lower() not in body.lower() or qa.unmatched_numbers(fact.value, fact.quote):
            lines.append(f"Not used ({labels[fact.slot_id]}): the email's own words did not support it.")
            continue
        detail = f'From the email "{email["subject"]}" from {email["sender"]}: "{fact.quote}"'
        try:
            _approve_value(deal_id, fact.slot_id, fact.value, detail, db_path)
        except om_slots.InvalidValue as error:
            lines.append(f"Not used ({labels[fact.slot_id]}): {error}")
            continue
        open_slots.remove(fact.slot_id)
        lines.append(f"{labels[fact.slot_id]} from an email: {fact.value}")
    return lines, [e["id"] for e in emails]


# ---------- step 3: research ----------

def _sourced(finding):
    sources = finding["sources"]
    return bool(sources) and all(s.get("checked") is True and s.get("tier") in (1, 2, 3) for s in sources)


def auto_accept(deal_id, db_path):
    """Accept new real findings whose every figure was checked against a Tier 1-3 source. Returns the count."""
    conn = db.get_connection(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, sources FROM research_findings WHERE deal_id = ? AND status = 'new' AND simulated = 0", (deal_id,))]
        accepted = 0
        with conn:
            for row in rows:
                if _sourced({"sources": json.loads(row["sources"] or "[]")}):
                    conn.execute("UPDATE research_findings SET status = 'accepted' WHERE id = ?", (row["id"],))
                    om_slots.log(conn, deal_id, "research_accepted", f"finding {row['id']} (sourced, accepted automatically)", ACTOR)
                    accepted += 1
    finally:
        conn.close()
    return accepted


def step_research(deal_id, facts, db_path):
    from services import connections
    deal = facts.get("deal") or {}
    if not deal.get("property_type") or not deal.get("submarket"):
        return ["Market research needs the deal's property type and location."]
    results = connections.run_research(deal, db_path)
    ran = [r for r in results if r["outcome"] == "ok"]
    lines = [f"Market research: {sum(r['count'] for r in ran)} finding(s) from {len(ran)} source(s)"] if ran else []
    accepted = auto_accept(deal_id, db_path)
    if accepted:
        lines.append(f"{accepted} sourced research finding(s) accepted automatically")
    return lines


# ---------- the run ----------

def _facts(deal_id, email, db_path):
    conn = db.get_connection(db_path)
    try:
        facts = om_facts.load(conn, deal_id, email)
        return facts, om_engine.build(facts), last_memory(conn, deal_id), deal_emails(conn, deal_id)
    finally:
        conn.close()


def _human_unapproved(deal_id, db_path):
    conn = db.get_connection(db_path)
    try:
        return {r["detail"] for r in conn.execute(
            "SELECT detail FROM om_events WHERE deal_id = ? AND action = 'unapprove' AND user != ?", (deal_id, ACTOR))}
    finally:
        conn.close()


def step_approve(deal_id, state, db_path):
    """Approve calculated values that come straight from the deal's documents or profile."""
    price = state.slots.get("financial.sale_price")
    price_ok = price is not None and price.approved
    skip = _human_unapproved(deal_id, db_path)
    ready = [s for s in state.waiting() if s.status == "auto-filled" and s.slot.id not in skip
             and (price_ok or s.slot.id not in PRICE_DEPENDENT)]
    if ready:
        om_slots.approve(deal_id, ready, f"{ACTOR} (sourced, approved automatically)", db_path)
    return [f"Approved {len(ready)} value(s) calculated from the deal's documents"] if ready else []


def _set(deal_id, **changes):
    with _lock:
        _runs.setdefault(deal_id, {}).update(changes)


def run(deal_id, email=None, client=None, db_path=None):
    """Do every step that has something new to do. Returns the memory it saved (lines, what was done)."""
    steps = allowed_steps()
    lines, ai_stopped = [], None
    facts, state, memory, emails = _facts(deal_id, email, db_path)
    done = dict(memory.get("done") or {})

    def ai_step(name, work):
        nonlocal ai_stopped
        if ai_stopped or name not in steps:
            return None
        _set(deal_id, step=STEP_NAMES[name])
        try:
            with ai_limits.as_session(SESSION):
                return work()
        except (gemini.RateLimited, gemini.GeminiQuotaError) as error:
            ai_stopped = f"Paused: {error} The AI Teammate continues when you next open the deal."
        except gemini.GeminiError as error:
            ai_stopped = f"The AI part stopped: {error}"
        except Exception:
            log.exception("Autopilot step %s failed", name)
            lines.append(f"{STEP_NAMES[name]}: something went wrong; it will try again next time.")
        return None

    if "record" in steps:
        _set(deal_id, step=STEP_NAMES["record"])
        lines += step_record(deal_id, facts, state, db_path)
        facts, state, _, _ = _facts(deal_id, email, db_path)

    new_emails = [e for e in emails if e["id"] not in set(done.get("emails", []))]
    if new_emails:
        result = ai_step("emails", lambda: step_emails(deal_id, state, new_emails, client, db_path))
        if result:
            lines += result[0]
            done["emails"] = sorted(set(done.get("emails", [])) | set(result[1]))
            facts, state, _, _ = _facts(deal_id, email, db_path)

    if "research" in steps:
        _set(deal_id, step=STEP_NAMES["research"])
        try:
            with ai_limits.as_session(SESSION):
                lines += step_research(deal_id, facts, db_path)
        except Exception as error:  # one failing source never stops the rest of the run
            lines.append(f"Market research: {error}")

    if facts.get("units"):
        text_fp = _fingerprint(om_drafting.facts_text(facts), om_drafting.accepted_research(deal_id, db_path),
                               [state.slots[s].status for s in TEXT_SLOTS if s in state.slots])
        needs_text = any(state.slots[s].status in ("empty", "ai-draft") for s in TEXT_SLOTS if s in state.slots)
        if needs_text and done.get("text") != text_fp:
            result = ai_step("text", lambda: om_drafting.draft_all_text(deal_id, facts, state, ACTOR, client, db_path))
            if result is not None:
                lines += [f"Drafted: {', '.join(result['saved'])}"] if result["saved"] else []
                lines += result["dropped"] + result["questions"]
                facts, state, _, _ = _facts(deal_id, email, db_path)
                done["text"] = _fingerprint(om_drafting.facts_text(facts), om_drafting.accepted_research(deal_id, db_path),
                                            [state.slots[s].status for s in TEXT_SLOTS if s in state.slots])

        unset = [k for k in om_calc.ASSUMPTIONS if k not in facts.get("assumptions", {})]
        if unset and facts.get("t12") and not done.get("assumptions"):
            result = ai_step("assumptions", lambda: om_drafting.propose_assumptions(deal_id, facts, ACTOR, client, db_path))
            if result is not None:
                done["assumptions"] = True
                if result["saved"]:
                    lines.append(f"Proposed assumptions for you to check: {', '.join(result['saved'])}")

    unsorted = [a["id"] for a in facts.get("assets", []) if not a.get("kind")]
    if unsorted and set(unsorted) - set(done.get("photos", [])):
        result = ai_step("photos", lambda: om_assets.sort_photos(deal_id, client, db_path))
        if result is not None:
            om_assets.apply_kinds(deal_id, result[0], ACTOR, db_path)
            done["photos"] = sorted(set(done.get("photos", [])) | set(unsorted))
            lines.append(f"Sorted {len(result[0])} photo(s)")
    if "photos" in steps:
        placed = om_assets.auto_place(deal_id, ACTOR, db_path)
        if placed:
            lines.append(f"Placed {placed} photo(s) on the slides")

    if "approve" in steps:
        _set(deal_id, step=STEP_NAMES["approve"])
        facts, state, _, _ = _facts(deal_id, email, db_path)
        lines += step_approve(deal_id, state, db_path)

    if ai_stopped:
        lines.append(ai_stopped)
    record = {"done": done, "lines": lines, "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    if lines or done != (memory.get("done") or {}):
        conn = om_slots._connect(db_path)
        try:
            with conn:
                om_slots.log(conn, deal_id, "autopilot", json.dumps(record), ACTOR)
        finally:
            conn.close()
    return record


def _worker(deal_id, email, db_path):
    try:
        record = run(deal_id, email, db_path=db_path)
        _set(deal_id, running=False, step="", finished=time.time(), lines=record["lines"])
    except Exception:
        log.exception("The OM autopilot failed")
        _set(deal_id, running=False, step="", finished=time.time(), lines=["The AI Teammate stopped unexpectedly."])


def start(deal_id, email=None, db_path=None, min_gap=30):
    """Start a background run for this deal unless one is running or one started in the last min_gap seconds."""
    if not enabled():
        return False
    with _lock:
        current = _runs.get(deal_id) or {}
        if current.get("running") or time.time() - current.get("started", 0) < min_gap:
            return False
        _runs[deal_id] = {"running": True, "step": "Starting", "started": time.time(), "finished": None, "lines": []}
    threading.Thread(target=_worker, args=(deal_id, email, db_path or db.DB_PATH), daemon=True,
                     name=f"om-autopilot-{deal_id}").start()
    return True
