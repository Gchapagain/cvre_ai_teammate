"""Recommendations for a deal. A person decides; nothing here acts on its own.

Two kinds:
- rule: calculated in code from the deal's saved data. Always available, no AI. Each card names the
  rule that fired and shows the exact numbers.
- ai: written by Gemini (one request, only when a person clicks) from the deal's facts and real
  research findings. Simulated findings are never sent. Code then checks every card: it must cite at
  least one finding that exists, and every number must appear in the deal data or a cited finding.
  Anything that fails is dropped and counted.
"""

import json
from datetime import date, datetime, timezone

from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError

import db
from services import drafting, gemini, metrics, qa

RULE, AI = "rule", "ai"
CONCENTRATION_SHARE = 0.25     # one tenant at or above this share of SF is a concentration risk
CONCENTRATION_HIGH = 0.50
EXPIRY_HIGH_SHARE = 0.20       # expiring leases at or above this share of SF are High priority
DATA_QUALITY_RULES = {"missing_value", "non_numeric_value", "zero_or_negative_value", "invalid_date",
                      "lease_end_before_start", "duplicate_unit_id"}
TIER_PRIORITY = {1: "High", 2: "Medium", 3: "Low"}
AI_PRIORITY_RULE = "Priority from the strongest source cited: Tier 1 High, Tier 2 Medium, Tier 3 Low."

PROMPT = """You suggest next steps to a commercial real estate broker for one deal. A person decides what to do.

Rules:
- Use ONLY the DEAL FACTS and RESEARCH FINDINGS below. No outside knowledge, no guesses.
- Every recommendation must cite at least one finding by its number (for example 12 for [F12]) in finding_ids.
- Copy any figure exactly as written below. Never estimate, average or combine figures.
- Do not state a price, value, cap rate or occupancy.
- title: a short action. why: one or two sentences with the evidence. next_step: one concrete thing to do.
- Give at most 4 recommendations.

DEAL FACTS
{facts}

RESEARCH FINDINGS
{findings}
"""


class AiRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    why: str
    next_step: str
    finding_ids: list[int]


class AiReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendations: list[AiRecommendation]


def _local_date(timestamp):
    """A UTC timestamp saved by SQLite, as the local calendar date."""
    try:
        return datetime.fromisoformat(timestamp).replace(tzinfo=timezone.utc).astimezone().date().isoformat()
    except (TypeError, ValueError):
        return None


def _deal_evidence(documents):
    return [{"name": d["filename"], "tier": None, "date": _local_date(d.get("received_at")),
             "connection": "From this deal", "figure": None, "metric": None} for d in documents if d.get("used_for") == "Rent roll"]


def _rec(rule_key, title, priority, why, next_step, rule, evidence):
    return {"kind": RULE, "rule_key": rule_key, "title": title, "priority": priority, "why": why,
            "next_step": next_step, "rule": rule, "evidence": evidence}


def _sf(unit):
    value = unit.get("square_feet")
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else 0


def _ending(units, today, after_months, upto_months):
    ending = []
    for unit in units:
        end = metrics._lease_end(unit)
        if end and _sf(unit) and end >= today:
            months = (end - today).days / metrics.DAYS_PER_MONTH
            if after_months < months <= upto_months:
                ending.append(unit)
    return ending


def _expiry_rec(units, today, after, upto, evidence):
    ending, total = _ending(units, today, after, upto), metrics.total_sf(units)
    if not ending or not total:
        return []
    sf = sum(_sf(u) for u in ending)
    share = sf / total
    high, lower = ("High", "Medium") if upto == 12 else ("Medium", "Low")
    window = f"in the next {upto} months" if after == 0 else f"in months {after + 1} to {upto} from today"
    names = ", ".join(str(u["unit_number"]) for u in ending)
    return [_rec(f"expiring:{after}-{upto}", f"Check renewals for {len(ending)} lease{'s' if len(ending) != 1 else ''} ending {window}",
                 high if share >= EXPIRY_HIGH_SHARE else lower,
                 f"{len(ending)} lease{'s' if len(ending) != 1 else ''} ({sf:,.0f} SF, {share:.1%} of total SF) end {window}, "
                 f"counted from {today.isoformat()}: unit{'s' if len(ending) != 1 else ''} {names}.",
                 "Ask these tenants about renewal intentions before pricing.",
                 f"Leases ending {window}. {high} when they are at least {EXPIRY_HIGH_SHARE:.0%} of SF, otherwise {lower}.",
                 evidence)]


def _concentration_rec(units, evidence):
    usable, total = [u for u in units if _sf(u)], metrics.total_sf(units)
    if len(usable) < 2 or not total:
        return []
    top = max(usable, key=_sf)
    share = _sf(top) / total
    if share < CONCENTRATION_SHARE:
        return []
    name = top.get("tenant_name") or f"Unit {top['unit_number']}"
    return [_rec("concentration", f"Review tenant concentration: {name}",
                 "High" if share >= CONCENTRATION_HIGH else "Medium",
                 f"{name} occupies {_sf(top):,.0f} SF, {share:.1%} of the {total:,.0f} SF total.",
                 f"Review {name}'s lease terms and credit before pricing.",
                 f"One tenant at {CONCENTRATION_SHARE:.0%} or more of SF. High at {CONCENTRATION_HIGH:.0%} or more, otherwise Medium.",
                 evidence)]


def rule_recommendations(units, flags, t12, documents, today=None):
    """Recommendations calculated in code from the deal's saved data. No AI."""
    today, evidence = today or date.today(), _deal_evidence(documents)
    recs = []
    for flag in flags:
        if flag["rule"] in DATA_QUALITY_RULES:
            continue
        unit = flag["unit_number"] or "(no ID)"
        recs.append(_rec(f"flag:{unit}:{flag['rule']}", f"Confirm unit {unit} with the property manager before pricing", "High",
                         flag["message"] or f"Actual {flag['actual_value']}, limit {flag['threshold']}.",
                         f"Ask the property manager to confirm unit {unit}'s lease and rent. Keep it out of pricing until confirmed.",
                         f"Validation rule {flag['rule']}: {metrics.rule_name(flag['rule'])}.", evidence))
    quality = [f for f in flags if f["rule"] in DATA_QUALITY_RULES]
    if quality:
        details = "; ".join(f"unit {f['unit_number'] or '(no ID)'}: {metrics.rule_name(f['rule'])} ({f['field']})" for f in quality)
        recs.append(_rec("data-quality", f"Follow up on {len(quality)} missing or invalid value{'s' if len(quality) != 1 else ''}",
                         "High", f"{details}.", "Ask the owner or property manager for corrected figures before pricing.",
                         "Validation rules for missing, unreadable or invalid values.", evidence))
    recs += _expiry_rec(units, today, 0, 12, evidence) + _expiry_rec(units, today, 12, 24, evidence)
    recs += _concentration_rec(units, evidence)
    if units and not t12:
        recs.append(_rec("no-t12", "Request the T-12 operating statement", "Medium",
                         "No T-12 is saved for this deal, so net operating income cannot be calculated.",
                         "Ask the owner for the trailing 12-month operating statement.", "No T-12 document saved.", evidence))
    return recs


# ---- AI recommendations ----

def research_inputs(deal_id, db_path=None):
    """Findings the AI may use: real (never simulated), not dismissed, with at least one source."""
    conn = db.get_connection(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM research_findings WHERE deal_id = ? AND simulated = 0 AND status != 'dismissed' ORDER BY id", (deal_id,))]
    finally:
        conn.close()
    for row in rows:
        row["sources"] = json.loads(row["sources"])
    return [row for row in rows if row["sources"]]


def _finding_text(finding, names):
    sources = "; ".join(f"{s['name']} (Tier {s.get('tier')}, {s.get('date') or 'date not stated'}): {s.get('figure') or 'no figure'}"
                        for s in finding["sources"])
    return f"[F{finding['id']}] {finding['topic']} ({names.get(finding['connection_id'], finding['connection_id'])}): {finding['summary']} | {sources}"


def _evidence(finding, names):
    return [dict(source, connection=names.get(finding["connection_id"], finding["connection_id"]), finding_id=finding["id"])
            for source in finding["sources"]]


def check_ai(reply, findings, facts, names):
    """Keep only recommendations that cite real findings and whose numbers can all be found. Returns (kept, removed)."""
    by_id = {f["id"]: f for f in findings}
    kept, removed = [], 0
    for item in reply.recommendations:
        cited = [by_id[i] for i in dict.fromkeys(item.finding_ids) if i in by_id]
        if not item.finding_ids or len(cited) != len(set(item.finding_ids)):
            removed += 1
            continue
        allowed = facts + "\n" + "\n".join(_finding_text(f, names) for f in cited)
        if qa.unmatched_numbers(" ".join((item.title, item.why, item.next_step)), allowed):
            removed += 1
            continue
        evidence = [e for f in cited for e in _evidence(f, names)]
        best = min((e["tier"] for e in evidence if e.get("tier")), default=3)
        kept.append({"kind": AI, "rule_key": None, "title": item.title.strip(), "priority": TIER_PRIORITY[best],
                     "why": item.why.strip(), "next_step": item.next_step.strip(), "rule": AI_PRIORITY_RULE, "evidence": evidence})
    return kept, removed


def generate_ai(deal_id, names, client=None, db_path=None, model=None, today=None):
    """One Gemini request. Saves the recommendations that pass the checks. Returns (saved, removed count).

    Earlier AI recommendations a person has not acted on are replaced; accepted or dismissed ones stay.
    """
    findings = research_inputs(deal_id, db_path)
    if not findings:
        raise ValueError("Run market research first: AI recommendations need at least one real research finding.")
    facts, _ = drafting.deal_facts(deal_id, db_path, today)
    prompt = PROMPT.format(facts=facts, findings="\n".join(_finding_text(f, names) for f in findings))
    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                         response_json_schema=AiReply.model_json_schema())
    raw = gemini.generate(client or gemini.get_client(), prompt, config, model)
    try:
        reply = AiReply.model_validate_json(raw)
    except ValidationError as exc:
        raise gemini.GeminiError("Gemini's reply was not in the expected format.") from exc
    kept, removed = check_ai(reply, findings, facts, names)
    db.init_db(db_path)
    conn = db.get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM recommendations WHERE deal_id = ? AND kind = 'ai' AND status = 'new'", (deal_id,))
            conn.executemany(
                "INSERT INTO recommendations (deal_id, kind, title, priority, why, next_step, evidence) VALUES (?, 'ai', ?, ?, ?, ?, ?)",
                [(deal_id, r["title"], r["priority"], r["why"], r["next_step"], json.dumps(r["evidence"])) for r in kept])
    finally:
        conn.close()
    return kept, removed


# ---- What a person does with them ----

def set_rule_status(deal_id, rec, status, db_path=None):
    """Record a person's decision on a rule recommendation, keyed by its rule so it sticks."""
    db.init_db(db_path)
    conn = db.get_connection(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO recommendations (deal_id, kind, rule_key, title, priority, why, next_step, evidence, status) "
                "VALUES (?, 'rule', ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(deal_id, rule_key) DO UPDATE SET status = excluded.status, "
                "title = excluded.title, priority = excluded.priority, why = excluded.why, next_step = excluded.next_step, "
                "evidence = excluded.evidence",
                (deal_id, rec["rule_key"], rec["title"], rec["priority"], rec["why"], rec["next_step"],
                 json.dumps(rec["evidence"]), status))
    finally:
        conn.close()


def set_ai_status(rec_id, status, db_path=None):
    conn = db.get_connection(db_path)
    try:
        with conn:
            conn.execute("UPDATE recommendations SET status = ? WHERE id = ? AND kind = 'ai'", (status, rec_id))
    finally:
        conn.close()


def note_text(rec):
    return f"Recommendation: {rec['title']}\nWhy: {rec['why']}\nNext step: {rec['next_step']}"
