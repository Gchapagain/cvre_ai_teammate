"""Simulated replies for every connection, for tests and screenshots. Nothing here is real data or calls anything."""

from types import SimpleNamespace

from services.connections import BlsAdapter, CensusAdapter, CoStarDemo, FredAdapter, GroundedSearchAdapter, TavilyAdapter  # noqa: F401
from services.connections.official import BLS_URL
from tests import research_fakes

TEST_KEYS = {"GEMINI_API_KEY": "test-gemini", "TAVILY_API_KEY": "test-tavily", "FRED_API_KEY": "test-fred",
             "BLS_API_KEY": "test-bls", "CENSUS_API_KEY": "test-census"}


def fake_fetch(calls=None, fail=None):
    """A stand-in for the official APIs (FRED, BLS, Census)."""
    def fetch(url, params=None, body=None, **kwargs):
        if calls is not None:
            calls.append((url, params, body))
        if fail:
            raise fail
        if url.endswith("/series/search"):
            return {"seriess": [{"id": "MADEUPFWUR", "title": "Unemployment Rate in Fort Worth-Arlington-Grapevine, TX (made-up test series)",
                                 "units": "Percent"}]}
        if url.endswith("/series/observations"):
            return {"observations": [{"date": "2026-08-01", "value": "4.4"}]}
        if url == BLS_URL:
            return {"status": "REQUEST_SUCCEEDED", "Results": {"series": [{"seriesID": "SMS48231040000000001",
                    "data": [{"year": "2026", "period": "M08", "periodName": "August", "value": "1234.5"}]}]}}
        if "api.census.gov" in url:
            return [["NAME", "B01003_001E", "B19013_001E", "state", "place"],
                    ["Fort Worth city, Texas", "900001", "70001", "48", "27000"]]
        raise AssertionError(f"unexpected call to {url}")
    return fetch


def grounded_response():
    """What a Gemini answer with Google Search sources looks like (made-up content)."""
    lines = ["Vacancy | North Fort Worth industrial vacancy was 7.0% in Q2 2026.",
             "New supply | About 2 million square feet was under construction at mid-year 2026.",
             "Employment and demand | A blog says demand is strong."]
    chunks = [SimpleNamespace(web=SimpleNamespace(uri="https://vertexaisearch.cloud.google.com/grounding-api-redirect/a", title="cushmanwakefield.com")),
              SimpleNamespace(web=SimpleNamespace(uri="https://vertexaisearch.cloud.google.com/grounding-api-redirect/b", title="bisnow.com")),
              SimpleNamespace(web=SimpleNamespace(uri="https://vertexaisearch.cloud.google.com/grounding-api-redirect/c", title="someblog.example.com"))]
    supports = [SimpleNamespace(segment=SimpleNamespace(text="North Fort Worth industrial vacancy was 7.0% in Q2 2026."), grounding_chunk_indices=[0]),
                SimpleNamespace(segment=SimpleNamespace(text="About 2 million square feet was under construction at mid-year 2026."), grounding_chunk_indices=[1]),
                SimpleNamespace(segment=SimpleNamespace(text="A blog says demand is strong."), grounding_chunk_indices=[2])]
    metadata = SimpleNamespace(grounding_chunks=chunks, grounding_supports=supports)
    return SimpleNamespace(text="\n".join(lines), candidates=[SimpleNamespace(grounding_metadata=metadata)])


def fake_grounded_client(calls=None, reply=None):
    def generate_content(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        if isinstance(reply, Exception):
            raise reply
        return reply or grounded_response()
    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


def adapters(fetch=None, search=None, research_client=None, grounded_client=None, include_demo=True):
    """Every research adapter, wired to simulated services."""
    fetch = fetch or fake_fetch()
    found = [GroundedSearchAdapter(client=grounded_client or fake_grounded_client()),
             TavilyAdapter(search_fn=search or research_fakes.fake_search(), client=research_client or research_fakes.fake_gemini()),
             FredAdapter(fetch=fetch), BlsAdapter(fetch=fetch), CensusAdapter(fetch=fetch)]
    return found + ([CoStarDemo()] if include_demo else [])
