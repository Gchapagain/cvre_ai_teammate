"""Research service: public market research for a deal's submarket. Advisory only.

A run searches the web for four topics, keeps only sources on the trusted list
(config/source_tiers.json), and asks Gemini once to summarise what those sources say.
Code then checks every figure against the text of the source it is attributed to.
Nothing here reaches a narrative until a person accepts a finding.

Search queries use generic terms only (property type + submarket + topic). The deal's
name, tenants and figures are never sent out.
"""

import json
import os
import re
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError

import db
from services import gemini, qa

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TIERS_FILE = PROJECT_ROOT / "config" / "source_tiers.json"
SEARCH_URL = "https://api.tavily.com/search"
SEARCH_KEY_NAME = "TAVILY_API_KEY"
RESULTS_PER_TOPIC = 5
NO_SOURCES = "No reliable public sources found."
FIGURES_BELOW = "Sources were found; what each one says is listed below."

# topic shown on the card -> generic search terms for it
TOPICS = {
    "Vacancy": "vacancy rate",
    "Asking rent trend": "asking rent trend",
    "New supply": "new construction pipeline deliveries",
    "Employment and demand": "employment growth demand",
}

PROMPT = """You summarise public market research for a commercial real estate broker.

Below are web search results for the {property_type} market in {submarket}, grouped by topic.
Each source has an ID and the text that was found.

Rules:
- Use ONLY the source text below. No outside knowledge. Never invent or adjust a figure.
- For each topic write a summary of one or two plain sentences saying what the sources report.
  If the sources say nothing useful about the topic, set summary to null.
- For each source you use, give: its id; metric (a short name such as "vacancy rate"); figure (the
  number with its unit, copied exactly from that source's text, or null if it states none); and
  period (the date or quarter the figure refers to, copied exactly from the text, or null).
- Use the same metric name for sources that report the same thing, so they can be compared.
- Never combine or average figures from different sources.

{sources}
"""


class SearchError(Exception):
    """The web search could not be run. The message is safe to show to a user."""


class SourceNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    metric: str | None
    figure: str | None
    period: str | None


class TopicReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    summary: str | None
    sources: list[SourceNote]


class ResearchReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topics: list[TopicReply]


def load_tiers(path=TIERS_FILE):
    return json.loads(Path(path).read_text())["tiers"]


def classify(url, tiers=None):
    """Return (tier, source name) for a URL. Tier is None when the source is not on the trusted list."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for entry in tiers or load_tiers():
        on_list = any(host == domain or host.endswith("." + domain) for domain in entry["domains"])
        if on_list or any(host.endswith(suffix) for suffix in entry["suffixes"]):
            return entry["tier"], host
    return None, host


def build_query(property_type, submarket, terms):
    """A search query made only of generic terms. Nothing about the deal itself goes in."""
    return f"{property_type} real estate {submarket} {terms}"


def search_key():
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.getenv(SEARCH_KEY_NAME, "").strip()
    if not key:
        raise SearchError(f"Web research needs a free Tavily key. Add {SEARCH_KEY_NAME}=... to the .env file, then try again.")
    return key


def tavily_search(query, key=None):
    """One Tavily search (1 credit). Returns a list of {url, title, content, published_date}."""
    body = json.dumps({"query": query, "max_results": RESULTS_PER_TOPIC, "search_depth": "basic"}).encode()
    request = urllib.request.Request(SEARCH_URL, data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key or search_key()}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read()).get("results", [])
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SearchError("The search service rejected the key. Check TAVILY_API_KEY in the .env file.") from None
        if exc.code in (429, 432, 433):
            raise SearchError("The search service's free limit has been reached. Try again later.") from None
        raise SearchError(f"The search service returned an error ({exc.code}). Try again later.") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise SearchError("The search service could not be reached. Check the internet connection and try again.") from None


def gather(property_type, submarket, search):
    """Search each topic and sort the results into trusted sources and a count of skipped ones."""
    tiers, found = load_tiers(), {}
    for topic, terms in TOPICS.items():
        kept, skipped = [], 0
        for result in search(build_query(property_type, submarket, terms)):
            tier, name = classify(result.get("url", ""), tiers)
            if tier is None or not (result.get("content") or "").strip():
                skipped += 1
                continue
            kept.append({"id": f"{topic[:1]}{len(kept) + 1}", "name": name, "url": result["url"], "tier": tier,
                         "title": result.get("title") or name, "text": result["content"].strip(),
                         "date": (result.get("published_date") or "")[:10] or None})
        found[topic] = {"sources": kept, "skipped": skipped}
    return found


def _sources_text(found):
    blocks = []
    for topic, entry in found.items():
        blocks.append(f"TOPIC: {topic}")
        blocks += [f"[{s['id']}] {s['name']} - {s['title']}\n{s['text']}" for s in entry["sources"]] or ["(no sources)"]
    return "\n\n".join(blocks)


def _in_text(value, text):
    return bool(value) and re.sub(r"\s+", " ", value).strip().casefold() in re.sub(r"\s+", " ", text).casefold()


def check_reply(reply, found):
    """Turn Gemini's reply into findings, keeping only what the source text supports."""
    replies = {topic.topic: topic for topic in reply.topics}
    findings = []
    for topic, entry in found.items():
        by_id = {s["id"]: s for s in entry["sources"]}
        notes = {n.id: n for n in (replies[topic].sources if topic in replies else []) if n.id in by_id}
        sources = []
        for source in entry["sources"]:
            note = notes.get(source["id"])
            figure = note.figure if note and note.figure and not qa.unmatched_numbers(note.figure, source["text"]) else None
            period = note.period if note and _in_text(note.period, source["text"]) else None
            sources.append({"name": source["name"], "url": source["url"], "tier": source["tier"],
                            "date": source["date"] or period, "figure": figure,
                            "metric": (note.metric or "").strip().lower() or None if note and figure else None})
        summary = replies[topic].summary if topic in replies else None
        all_text = " ".join(s["text"] for s in entry["sources"])
        if not sources:
            summary = NO_SOURCES
        elif not summary or qa.unmatched_numbers(summary, all_text):
            summary = FIGURES_BELOW
        findings.append({"topic": topic, "summary": summary.strip(), "sources": sources, "skipped": entry["skipped"]})
    return findings


def _first_number(text):
    numbers = re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")
    return float(numbers[0].replace(",", "")) if numbers else None


def disagreements(sources):
    """Metrics for which two sources give different figures. The figures are never merged."""
    by_metric = defaultdict(set)
    for source in sources:
        value = _first_number(source.get("figure"))
        if source.get("metric") and value is not None:
            by_metric[source["metric"]].add(value)
    return sorted(metric for metric, values in by_metric.items() if len(values) > 1)


def _summarise(found, property_type, submarket, client, model):
    """One Gemini request. Skipped entirely when no trusted source was found for any topic."""
    if not any(entry["sources"] for entry in found.values()):
        return ResearchReply(topics=[])
    prompt = PROMPT.format(property_type=property_type, submarket=submarket, sources=_sources_text(found))
    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                         response_json_schema=ResearchReply.model_json_schema())
    raw = gemini.generate(client or gemini.get_client(), prompt, config, model)
    try:
        return ResearchReply.model_validate_json(raw)
    except ValidationError as exc:
        raise gemini.GeminiError("Gemini's reply was not in the expected format.") from exc


def _deal_market(conn, deal_id):
    deal = conn.execute("SELECT property_type, submarket FROM deals WHERE id = ?", (deal_id,)).fetchone()
    if not deal or not deal["property_type"] or not deal["submarket"]:
        raise ValueError("Research needs the deal's property type and location. Add them first.")
    return deal["property_type"], deal["submarket"]


def run_research(deal_id, search=None, client=None, db_path=None, model=None):
    """Research the deal's market and replace its saved findings. Returns the new findings.

    Uses one search per topic (4) and at most one Gemini request. Raises SearchError,
    gemini.GeminiError or ValueError; in every one of those cases the old findings are kept.
    """
    db.init_db(db_path)
    conn = db.get_connection(db_path)
    try:
        property_type, submarket = _deal_market(conn, deal_id)
        found = gather(property_type, submarket, search or tavily_search)
        findings = check_reply(_summarise(found, property_type, submarket, client, model), found)
        with conn:
            conn.execute("DELETE FROM research_findings WHERE deal_id = ?", (deal_id,))
            conn.executemany(
                "INSERT INTO research_findings (deal_id, topic, summary, sources, skipped) VALUES (?, ?, ?, ?, ?)",
                [(deal_id, f["topic"], f["summary"], json.dumps(f["sources"]), f["skipped"]) for f in findings],
            )
    finally:
        conn.close()
    return findings


def set_status(finding_id, status, db_path=None):
    """A person accepts or dismisses a finding. A finding with no sources cannot be accepted."""
    conn = db.get_connection(db_path)
    try:
        row = conn.execute("SELECT sources FROM research_findings WHERE id = ?", (finding_id,)).fetchone()
        if status == "accepted" and not json.loads(row["sources"]):
            raise ValueError("A finding with no sources cannot be accepted.")
        with conn:
            conn.execute("UPDATE research_findings SET status = ? WHERE id = ?", (status, finding_id))
    finally:
        conn.close()
