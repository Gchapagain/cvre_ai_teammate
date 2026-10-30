"""Load an OM template (templates/om_v1.json) and the fixed boilerplate (config/om_boilerplate.json).

A template is a list of sections, slides and slots. Slots are defined once and placed on one or more
slides by id. Nothing here touches the database.
"""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
BOILERPLATE = ROOT / "config" / "om_boilerplate.json"
DEFAULT = "om_v1"

TYPES = {"text", "bullets", "table", "kpi", "photo", "boilerplate", "auto"}
SOURCES = {"document_field", "calculated", "ai_text", "broker_input", "broker_photo", "research", "fixed"}
PHOTO_KINDS = ("aerial", "exterior", "interior", "site_plan", "map")
PRIORITIES = ("high", "medium", "low")


@dataclass(frozen=True)
class Slot:
    id: str
    label: str
    type: str
    source: str
    required: bool
    why: str
    broker_question: str = ""
    client_question: str = ""
    answer_by: tuple = ()
    topic: str = ""
    priority: str = "medium"
    validation: dict = field(default_factory=dict)
    auto: str | None = None          # where an automatic value comes from: deal.<column> or calc.<name>
    photo_kinds: tuple = ()
    count: int = 1                   # photos needed
    boilerplate: str | None = None   # key in config/om_boilerplate.json

    @property
    def fixed(self):
        """Fixed wording or structure that is never asked for and never counts toward completion."""
        return self.type in ("boilerplate", "auto") or self.source == "fixed"


@dataclass(frozen=True)
class Slide:
    id: str
    layout: str
    title: str
    section: str
    slots: tuple
    only_if_filled: str | None = None  # an optional slide shown only when this slot has a value


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    sections: tuple   # ({id, number, title}, ...)
    slots: dict       # slot id -> Slot
    slides: tuple
    slide_limits: tuple

    def section(self, section_id):
        return next(s for s in self.sections if s["id"] == section_id)

    def slot_section(self, slot_id):
        """The section a slot counts toward: the first slide it appears on."""
        return next(slide.section for slide in self.slides if slot_id in slide.slots)

    def slides_for(self, slot_id):
        return [slide for slide in self.slides if slot_id in slide.slots]


def _slot(slot_id, raw):
    if raw["type"] not in TYPES or raw["source"] not in SOURCES:
        raise ValueError(f"Slot {slot_id} has an unknown type or source.")
    return Slot(id=slot_id, label=raw["label"], type=raw["type"], source=raw["source"], required=raw["required"],
                why=raw["why"], broker_question=raw.get("broker_question", ""), client_question=raw.get("client_question", ""),
                answer_by=tuple(raw.get("answer_by", ())), topic=raw.get("topic", ""), priority=raw.get("priority", "medium"),
                validation=raw.get("validation", {}), auto=raw.get("auto"), photo_kinds=tuple(raw.get("photo_kinds", ())),
                count=raw.get("count", 1), boilerplate=raw.get("boilerplate"))


@lru_cache(maxsize=4)
def load(template_id=DEFAULT):
    raw = json.loads((TEMPLATES / f"{template_id}.json").read_text())
    slots = {slot_id: _slot(slot_id, spec) for slot_id, spec in raw["slots"].items()}
    slides = tuple(Slide(id=s["id"], layout=s["layout"], title=s["title"], section=s["section"], slots=tuple(s["slots"]),
                         only_if_filled=s.get("only_if_filled")) for s in raw["slides"])
    for slide in slides:
        unknown = [slot_id for slot_id in slide.slots if slot_id not in slots]
        if unknown:
            raise ValueError(f"Slide {slide.id} uses unknown slots: {unknown}")
    limits = raw.get("slide_limits", {"min": 18, "max": 25})
    return Template(raw["id"], raw["name"], tuple(raw["sections"]), slots, slides, (limits["min"], limits["max"]))


@lru_cache(maxsize=1)
def boilerplate():
    """The fixed legal wording. The AI never writes or rewrites it."""
    return json.loads(BOILERPLATE.read_text())
