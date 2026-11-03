"""The OM completion engine: what each template slot holds right now, where it came from, whether a
person approved it, and how complete the OM is. Pure functions over "facts" (app/queries.om_facts()),
so showing the OM never writes anything.

Slot statuses
- empty            nothing yet
- auto-filled      calculated or taken from the deal's documents; waiting for a person to approve
- ai-draft         written by the AI; waiting for a person to approve
- broker-provided  typed or uploaded by a person; waiting for approval
- approved         a person approved it. For calculated values the approval holds only while the number
                   is the same as when it was approved; if the data changes it goes back to auto-filled.

Completion = approved required slots / required slots (fixed boilerplate does not count).
"""

import json
from dataclasses import dataclass, field

from services import om_calc, om_template, progress

FILLED = ("auto-filled", "ai-draft", "broker-provided")
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
WHO = {"broker": "Broker", "client": "Client", "document": "A document"}
# Which documents each calculation reads, so a value names its real source files.
FROM_DOCUMENTS = {"total_sf": ("Rent roll",), "unit_count": ("Rent roll",), "avg_unit_size": ("Rent roll",),
                  "leased_pct": ("Rent roll",), "in_place_rent": ("Rent roll",), "price_per_sf": ("Rent roll",),
                  "rent_roll_table": ("Rent roll",), "in_place_noi": ("T-12",), "cash_flow": ("Rent roll", "T-12"),
                  "cap_rate_y4": ("Rent roll", "T-12")}
PHOTO_NAMES = {"aerial": "aerial", "exterior": "exterior", "interior": "interior", "site_plan": "site plan", "map": "map"}


@dataclass
class SlotState:
    slot: om_template.Slot
    section: str
    slides: list                  # slide numbers it appears on
    status: str
    value: object = None
    display: str = ""
    source: dict = field(default_factory=dict)
    calc: om_calc.Calc | None = None
    needs: list = field(default_factory=list)
    note: str = ""                # e.g. "Changed since it was approved"
    photos: list = field(default_factory=list)

    @property
    def approved(self):
        return self.status == "approved"

    @property
    def counts(self):
        return self.slot.required and not self.slot.fixed


def _same(a, b):
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _auto_value(slot, facts, template):
    """(Calc or None, source) for a slot with an automatic value."""
    if not slot.auto:
        return None, {}
    kind, _, name = slot.auto.partition(".")
    if kind == "deal":
        value = (facts.get("deal") or {}).get(name)
        if value in (None, ""):
            return om_calc.Calc(needs=[f"the deal's {name.replace('_', ' ')}"]), {}
        return om_calc.Calc(value, str(value), f"Deal record: {name.replace('_', ' ')}", [f"Deal record: {value}"]), \
            {"kind": "document_field", "detail": f"Deal record, {name.replace('_', ' ')}"}
    if name == "contents":
        return om_calc.contents(facts, template), {"kind": "calculated", "detail": "Built from the sections"}
    calc = om_calc.CALCS[name](facts)
    used = FROM_DOCUMENTS.get(name, ())
    documents = ", ".join(sorted({d["filename"] for d in facts.get("documents", []) if d.get("used_for") in used}))
    kind = "document_field" if slot.source == "document_field" else "calculated"
    return calc, {"kind": kind, "detail": calc.formula + (f" (from {documents})" if documents else "")}


def _photo_state(slot, state, facts, row):
    photos = [a for a in facts.get("assets", []) if a.get("slot_id") == slot.id]
    state.photos = photos
    have, need = len(photos), slot.needed
    kinds = " or ".join(PHOTO_NAMES[k] for k in slot.photo_kinds)
    if have < need:
        state.status = "empty"
        state.needs = [f"{need - have} more {kinds} photo{'s' if need - have != 1 else ''}"]
        state.display = f"{have} of {need} photos"
        return state
    ids = sorted(a["id"] for a in photos)
    state.value, state.display = ids, f"{have} photo{'s' if have != 1 else ''}"
    sample = any(a.get("sample") for a in photos)
    state.source = {"kind": "broker_photo", "detail": "Sample illustration (demo)" if sample else "Uploaded by the broker"}
    if row and row["status"] == "approved" and _same(row["value"], ids):
        state.status = "approved"
    else:
        state.status = "broker-provided"
        if row and row["status"] == "approved":
            state.note = "Photos changed since they were approved"
    return state


def slot_state(slot, facts, template, numbers):
    """The current state of one slot."""
    row = facts.get("rows", {}).get(slot.id)
    state = SlotState(slot, template.slot_section(slot.id), numbers.get(slot.id, []), "empty")
    if slot.fixed:
        if slot.boilerplate:
            text = om_template.boilerplate()[slot.boilerplate]
            state.value, state.display = text, text if isinstance(text, str) else " ".join(text)
            state.source = {"kind": "fixed", "detail": "config/om_legal_placeholder.json (placeholder text)"}
        else:
            calc, state.source = _auto_value(slot, facts, template)
            state.calc, state.value, state.display = calc, calc.value, calc.display
        state.status = "approved"
        return state
    if slot.type == "photo":
        return _photo_state(slot, state, facts, row)
    calc, auto_source = _auto_value(slot, facts, template)
    state.calc = calc
    stored = row and row["status"] in ("broker-provided", "ai-draft", "approved") and row.get("value") not in (None, "")
    stored_is_override = stored and row["source"].get("kind") not in ("calculated", "document_field")
    if stored_is_override:
        state.value, state.status, state.source = row["value"], row["status"], row["source"]
        currency = (slot.validation or {}).get("kind") == "currency" and isinstance(row["value"], (int, float))
        state.display = om_calc.money(row["value"]) if currency else display(row["value"])
        return state
    if calc is not None and calc.ready:
        state.value, state.display, state.source = calc.value, calc.display, auto_source
        if row and row["status"] == "approved":
            if _same(row["value"], calc.value):
                state.status = "approved"
            else:
                state.status, state.note = "auto-filled", "Changed since it was approved"
        else:
            state.status = "auto-filled"
        return state
    state.needs = list(calc.needs) if calc else []
    return state


def display(value):
    if isinstance(value, list):
        return "; ".join(display(v) for v in value)
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


@dataclass
class OmState:
    template: om_template.Template
    slots: dict                    # slot id -> SlotState
    slides: list                   # [(number, Slide)] actually included

    @property
    def counted(self):
        return [s for s in self.slots.values() if s.counts]

    def completion(self, section=None):
        """(approved %, filled-but-waiting %, approved count, waiting count, required count)."""
        counted = [s for s in self.counted if section is None or s.section == section]
        if not counted:
            return 100, 0, 0, 0, 0
        approved = sum(1 for s in counted if s.approved)
        waiting = sum(1 for s in counted if s.status in FILLED)
        return (round(100 * approved / len(counted)), round(100 * waiting / len(counted)), approved, waiting, len(counted))

    @property
    def percent(self):
        return self.completion()[0]

    @property
    def colour(self):
        return progress.colour_for(self.percent)

    def missing(self):
        """Empty slots: required ones first, then by priority. Each with what, why, slides and who can answer."""
        empty = [s for s in self.slots.values() if not s.slot.fixed and s.status == "empty"]
        empty.sort(key=lambda s: (not s.slot.required, PRIORITY_ORDER.get(s.slot.priority, 1), min(s.slides or [99])))
        return empty

    def waiting(self):
        """Filled slots waiting for a person's approval."""
        return [s for s in self.slots.values() if not s.slot.fixed and s.status in FILLED]

    def required_missing(self):
        return [s for s in self.missing() if s.slot.required]

    def slide_status(self, slide):
        """green (every required slot approved), amber (filled, waiting approval), red (something required is empty)."""
        states = [self.slots[i] for i in slide.slots if self.slots[i].counts]
        if any(s.status == "empty" for s in states):
            return "red"
        if any(not s.approved for s in states):
            return "amber"
        return "green"


def who_can_answer(state):
    return " / ".join(WHO[w] for w in state.slot.answer_by) or "Broker"


def build(facts, template=None):
    template = template or om_template.load()
    included, number = [], 0
    for slide in template.slides:
        if slide.only_if_filled:
            filled = [a for a in facts.get("assets", []) if a.get("slot_id") == slide.only_if_filled]
            if not filled:
                continue
        number += 1
        included.append((number, slide))
    numbers = {}
    for number, slide in included:
        for slot_id in slide.slots:
            numbers.setdefault(slot_id, []).append(number)
    slots = {slot_id: slot_state(slot, facts, template, numbers) for slot_id, slot in template.slots.items()
             if slot_id in numbers or any(slot_id in s.slots for s in template.slides)}
    return OmState(template, slots, included)


def summary_line(state, deal_name):
    """'OM for Fallowmere is 64% complete - 5 items missing'."""
    missing, waiting = len(state.required_missing()), len([s for s in state.waiting() if s.slot.required])
    if missing:
        rest = f"{missing} item{'s' if missing != 1 else ''} missing"
    elif waiting:
        rest = f"{waiting} item{'s' if waiting != 1 else ''} waiting for your approval"
    else:
        rest = "ready for a client-ready export"
    return f"OM for {deal_name} is {state.percent}% complete - {rest}"


def time_spent(events, gap_minutes=15):
    """(minutes, sessions) of OM work from the action log: clicks less than gap_minutes apart are one session.

    This is time spent working on the OM in the app, not a claim about time saved.
    """
    from datetime import datetime, timedelta
    times = sorted(datetime.fromisoformat(str(e["created_at"])) for e in events if e.get("created_at"))
    if not times:
        return 0, 0
    minutes, sessions, start, last = 0.0, 1, times[0], times[0]
    for moment in times[1:]:
        if moment - last > timedelta(minutes=gap_minutes):
            minutes += max(1.0, (last - start).total_seconds() / 60)
            sessions, start = sessions + 1, moment
        last = moment
    minutes += max(1.0, (last - start).total_seconds() / 60)
    return round(minutes), sessions
