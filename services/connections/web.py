"""Web search with citations: Gemini with Google Search grounding, and Tavily.

Only sources on the trusted list (config/source_tiers.json) are kept. Nothing is scraped:
both services return search results through their own official APIs.
"""

import re

from google.genai import types

from services import gemini, research
from services.connections.base import Adapter, SourceError, finding

TOPIC_NAMES = list(research.TOPICS)
GROUNDED_PROMPT = """Using Google Search, report what recent public sources say about the {property_type} real estate
market in {submarket}. Cover these topics: {topics}.

Write one line per finding, in exactly this form:
TOPIC | one sentence stating what a source reports, with the figure and the period it refers to

Rules: only state what a source says. Never estimate, average or combine figures from different sources.
If you find nothing reliable for a topic, leave it out.
"""


def _support_text(support):
    segment = getattr(support, "segment", None)
    return (getattr(segment, "text", None) or "").strip()


class GroundedSearchAdapter(Adapter):
    id, name, kind, icon = "web_search_gemini", "Web search (Gemini + Google Search)", "Web search", ":material/travel_explore:"
    topics = tuple(TOPIC_NAMES)
    provides = "Recent market figures from the web, each tied to the page that supports it."
    key_name = "GEMINI_API_KEY"
    key_help = "Uses the Gemini key already in .env. Google Search grounding may not be available on every free key."

    def __init__(self, client=None, model=None):
        self.client, self.model = client, model

    def _sources(self, metadata):
        tiers = research.load_tiers()
        sources = []
        for chunk in getattr(metadata, "grounding_chunks", None) or []:
            web = getattr(chunk, "web", None)
            title, uri = getattr(web, "title", "") or "", getattr(web, "uri", "") or ""
            # The URL is a Google redirect, so the source is judged by its domain (the chunk title).
            tier, _ = research.classify(f"https://{title}", tiers) if title else (None, "")
            sources.append({"name": title, "url": uri, "tier": tier})
        return sources

    def search(self, deal):
        """One Gemini request with Google Search."""
        prompt = GROUNDED_PROMPT.format(property_type=deal["property_type"], submarket=deal["submarket"],
                                        topics=", ".join(TOPIC_NAMES))
        config = types.GenerateContentConfig(temperature=0, tools=[types.Tool(google_search=types.GoogleSearch())])
        response = gemini.generate_response(self.client or gemini.get_client(), prompt, config, self.model)
        metadata = getattr(response.candidates[0], "grounding_metadata", None) if response.candidates else None
        if metadata is None:
            raise SourceError("The answer came back without sources, so it cannot be used.")
        sources, supports = self._sources(metadata), getattr(metadata, "grounding_supports", None) or []
        findings = []
        for line in response.text.splitlines():
            topic, _, sentence = line.partition("|")
            topic, sentence = topic.strip(), sentence.strip()
            if topic not in TOPIC_NAMES or not sentence:
                continue
            cited = {i for s in supports if _support_text(s) and _support_text(s) in sentence
                     for i in (getattr(s, "grounding_chunk_indices", None) or [])}
            trusted = [sources[i] for i in sorted(cited) if i < len(sources) and sources[i]["tier"]]
            if not trusted:
                continue  # an unsupported line, or one supported only by untrusted pages, is dropped
            numbers = re.findall(r"\d[\d,]*(?:\.\d+)?%?", sentence)
            best = min(trusted, key=lambda s: s["tier"])
            # The source pages' own text is not returned, so the figure cannot be checked against it.
            findings.append(finding(topic, sentence, best["name"], best["tier"], self.id, figure=numbers[0] if numbers else None,
                                    url=best["url"], checked=False))
        return findings


class TavilyAdapter(Adapter):
    id, name, kind, icon = "web_search_tavily", "Web search (Tavily)", "Web search", ":material/search:"
    topics = tuple(TOPIC_NAMES)
    provides = "Web search results whose figures are checked against each source's own text."
    key_name = research.SEARCH_KEY_NAME
    key_help = "Free key (1,000 searches a month): tavily.com, then add TAVILY_API_KEY=... to .env."

    def __init__(self, search_fn=None, client=None, model=None):
        self.search_fn, self.client, self.model = search_fn, client, model

    def search(self, deal):
        """Four searches and at most one Gemini request."""
        try:
            return [dict(item, connection_id=self.id, simulated=False)
                    for item in research.tavily_findings(deal["property_type"], deal["submarket"],
                                                         self.search_fn, self.client, self.model)]
        except research.SearchError as exc:
            raise SourceError(str(exc)) from None
