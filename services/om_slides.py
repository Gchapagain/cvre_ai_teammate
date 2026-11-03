"""The OM slide editor's plain-words view of each slide: the slides in the template's own order, what each
one still needs ("add 1 photo (the cover photo)", "write the text") and its badges. Pure functions over an
OM state (services/om_engine.py): nothing here writes or calls the AI.
"""

from dataclasses import dataclass

from services import om_drafting

PHOTO_WORDS = {"aerial": "aerial", "exterior": "exterior", "interior": "interior", "site_plan": "site plan", "map": "map"}
TEXT_TYPES = ("text", "bullets")
COLOUR_WORDS = {"green": "Approved", "amber": "Waiting for approval", "red": "Needs something"}


@dataclass
class SlideRow:
    number: int
    slide: object          # om_template.Slide
    colour: str            # green / amber / red
    badges: list
    items: list            # the slot states a person can see on this slide (fixed wording left out)


def items(state, slide):
    """The slide's slot states a person works with, in the slide's order. Fixed wording is left out."""
    return [state.slots[slot_id] for slot_id in slide.slots if not state.slots[slot_id].slot.fixed]


def badges(state, slide):
    """'needs a photo' / 'needs text' / 'needs numbers' for required items still empty on this slide."""
    out = []
    for item in items(state, slide):
        if item.status != "empty" or not item.slot.required:
            continue
        badge = ("needs a photo" if item.slot.type == "photo" else "needs text" if is_text(item)
                 else "needs numbers")
        if badge not in out:
            out.append(badge)
    return out


def is_text(item):
    """Text a person (or the AI) writes, as opposed to a number calculated in code."""
    return item.slot.type in TEXT_TYPES and not (item.slot.auto or "").startswith("calc.")


def can_draft(item):
    """Items the slide's "Draft with AI" button writes."""
    return item.slot.id in om_drafting.TEXT_SLOTS.values()


def rows(state):
    """Every slide in the OM, in the template's order."""
    return [SlideRow(number, slide, state.slide_status(slide), badges(state, slide), items(state, slide))
            for number, slide in state.slides]


def photo_words(slot):
    kinds = " or ".join(PHOTO_WORDS[k] for k in slot.photo_kinds)
    return f"{slot.count} photo{'s' if slot.count != 1 else ''} ({slot.label.lower()}: {kinds})"


def needs_line(number, slide, state):
    """'Slide 1 - Cover: add 1 photo (cover photo: exterior or aerial)', in plain words."""
    asks = []
    for item in items(state, slide):
        if item.status != "empty" or not item.slot.required:
            continue
        if item.slot.type == "photo":
            missing = item.slot.needed - len(item.photos)
            asks.append(f"add {missing} photo{'s' if missing != 1 else ''} ({item.slot.label.lower()}: "
                        + " or ".join(PHOTO_WORDS[k] for k in item.slot.photo_kinds) + ")")
        elif is_text(item):
            asks.append(f"write {item.slot.label.lower()}")
        elif item.slot.id == "financial.sale_price":
            asks.append("set the asking price")
        else:
            asks.append(f"{item.slot.label.lower()} needs " + ("; ".join(item.needs) or "data"))
    head = f"Slide {number} - {slide.title}"
    if asks:
        return f"{head}: " + "; ".join(asks)
    waiting = [i for i in items(state, slide) if i.counts and not i.approved]
    if waiting:
        return f"{head}: everything is filled; check it and approve the slide"
    if not any(i.counts for i in items(state, slide)):
        return f"{head}: fixed wording, nothing to fill" if not items(state, slide) else f"{head}: optional items only"
    return f"{head}: approved"


def waiting_items(state, slide):
    """Filled items on this slide that still need a person's approval (what "Approve this slide" approves)."""
    return [i for i in items(state, slide) if i.status not in ("empty", "approved")]
