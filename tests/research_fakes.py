"""Made-up search results and Gemini replies for research tests and screenshots. Nothing here is real data."""

import json
from types import SimpleNamespace

RESULTS = {
    "vacancy rate": [
        {"url": "https://www.cbre.com/insights/figures/dallas-fort-worth-industrial", "title": "DFW Industrial Figures",
         "content": "North Fort Worth industrial vacancy was 6.2% in Q2 2026 as new deliveries slowed.", "published_date": "2026-07-18"},
        {"url": "https://www.jll.com/en/trends-and-insights/research/dfw-industrial", "title": "DFW Industrial Insight",
         "content": "Vacancy in the Alliance submarket reached 7.5% in Q2 2026.", "published_date": "2026-07-25"},
        {"url": "https://randomblog.example.com/dfw-warehouses", "title": "My warehouse blog", "content": "Vacancy is 3%, trust me."},
    ],
    "asking rent trend": [
        {"url": "https://www.bisnow.com/dallas-ft-worth/news/industrial/rents", "title": "DFW industrial rents",
         "content": "Asking rents for bulk warehouse space rose over the past year, brokers said.", "published_date": "2026-08-02"},
    ],
    "new construction pipeline deliveries": [
        {"url": "https://www.colliers.com/en/research/dallas-fort-worth-industrial", "title": "DFW Industrial Report",
         "content": "About 4.1 million square feet was under construction in North Fort Worth at mid-year 2026."},
    ],
    "employment growth demand": [
        {"url": "https://www.bls.gov/eag/eag.tx_fortworth_md.htm", "title": "Fort Worth-Arlington Economy at a Glance",
         "content": "The unemployment rate in Fort Worth-Arlington was 4.1% in August 2026.", "published_date": "2026-09-20"},
    ],
}

REPLY = {"topics": [
    {"topic": "Vacancy", "summary": "Two brokerage reports put Q2 2026 vacancy at 6.2% and 7.5%.", "sources": [
        {"id": "V1", "metric": "Vacancy rate", "figure": "6.2%", "period": "Q2 2026"},
        {"id": "V2", "metric": "vacancy rate", "figure": "7.5%", "period": "Q2 2026"}]},
    {"topic": "Asking rent trend", "summary": "Trade press reports asking rents rose over the past year.", "sources": [
        {"id": "A1", "metric": "asking rent", "figure": None, "period": None}]},
    {"topic": "New supply", "summary": "About 4.1 million square feet was under construction at mid-year 2026.", "sources": [
        {"id": "N1", "metric": "under construction", "figure": "4.1 million square feet", "period": "mid-year 2026"}]},
    {"topic": "Employment and demand", "summary": "The unemployment rate was 4.1% in August 2026.", "sources": [
        {"id": "E1", "metric": "unemployment rate", "figure": "4.1%", "period": "August 2026"}]},
]}


def fake_search(results=None, queries=None):
    """A stand-in for the search API: answers each query from the table above."""
    results = RESULTS if results is None else results

    def search(query):
        if queries is not None:
            queries.append(query)
        if isinstance(results, Exception):
            raise results
        return next((rows for terms, rows in results.items() if terms in query), [])
    return search


def fake_gemini(reply=None, prompts=None):
    reply = REPLY if reply is None else reply

    def generate_content(**kwargs):
        if prompts is not None:
            prompts.append(kwargs["contents"])
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(text=reply if isinstance(reply, str) else json.dumps(reply))
    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
