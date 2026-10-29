"""How far a deal has got, calculated from what is saved. No AI and no assumed numbers.

A deal has seven steps. Each is done or not, judged only from rows in the database:
  1. Documents received   at least one document is saved for the deal
  2. Fields extracted     rent roll units are saved
  3. Validation run       units are saved (validation always runs right after extraction, so
                          saved units have been checked; nothing records a separate time)
  4. Flags resolved       units are saved and no flag is open
  5. Draft narrative      a draft narrative is saved
  6. Research reviewed    a person accepted or dismissed real research, and none is left new
  7. Approved             the deal's status is Approved

The colour comes from the share of steps done, with thresholds in config/progress.json.
"""

import json
from dataclasses import dataclass
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config" / "progress.json"

STEPS = ("Documents received", "Fields extracted", "Validation run", "Flags resolved",
         "Draft narrative", "Research reviewed", "Approved")
COLOURS = ("red", "orange", "yellow", "green")


@dataclass(frozen=True)
class Facts:
    """What the database says about one deal. queries.progress_facts() fills these in."""
    documents: int = 0
    units: int = 0
    open_flags: int = 0
    drafts: int = 0
    findings_new: int = 0       # real (not simulated) findings still waiting for a person
    findings_reviewed: int = 0  # real findings a person accepted or dismissed
    approved: bool = False


@dataclass(frozen=True)
class Progress:
    done: tuple  # one True/False per step, in STEPS order
    next_step: str
    colour: str

    @property
    def count(self):
        return sum(self.done)

    @property
    def total(self):
        return len(self.done)

    @property
    def percent(self):
        return round(100 * self.count / self.total)


def thresholds():
    settings = json.loads(CONFIG.read_text())
    return settings["red_below"], settings["orange_below"]


def colour_for(percent, limits=None):
    """red, orange, yellow, or green. Only exactly 100% is green."""
    red_below, orange_below = limits or thresholds()
    if percent >= 100:
        return "green"
    if percent < red_below:
        return "red"
    return "orange" if percent < orange_below else "yellow"


def _plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def _next_steps(facts):
    """The wording for each step when it is the next one to do."""
    research = (f"Next: review {_plural(facts.findings_new, 'research finding')}" if facts.findings_new
                else "Next: run market research")
    return ("Next: add a rent roll", "Next: read the rent roll", "Next: check the rent roll",
            f"Next: resolve {_plural(facts.open_flags, 'flag')}", "Next: generate a draft narrative",
            research, "Next: approve the deal")


def calculate(facts, limits=None):
    done = (
        facts.documents > 0,
        facts.units > 0,
        facts.units > 0,
        facts.units > 0 and facts.open_flags == 0,
        facts.drafts > 0,
        facts.findings_reviewed > 0 and facts.findings_new == 0,
        facts.approved,
    )
    steps = _next_steps(facts)
    next_step = next((steps[i] for i, ok in enumerate(done) if not ok), "All steps done")
    percent = round(100 * sum(done) / len(done))
    return Progress(done, next_step, colour_for(percent, limits))
