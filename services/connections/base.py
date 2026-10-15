"""What every connection (data source) looks like, and the shape of what it finds.

A connection only ever uses an official API, free public data, a cited web search or a file
the person imported. Nothing here scrapes a website.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MARKETS_FILE = PROJECT_ROOT / "config" / "market_data.json"

CONNECTED, NOT_SET_UP, DEMO, NEEDS_LICENSE = "Connected", "Not set up", "Demo", "Needs licensed access"
TIER_LABELS = {1: "Official / government", 2: "Brokerage / research firm", 3: "News / trade press"}


class SourceError(Exception):
    """A connection could not answer. The message is safe to show to a user and never holds a key."""


def finding(topic, summary, source_name, tier, connection_id, figure=None, metric=None, url=None, date=None,
            simulated=False, checked=True):
    """One finding, stored in research_findings. Its sources list holds the one source it came from.

    checked is False when the figure could not be compared with the source's own text.
    """
    return {"topic": topic, "summary": summary, "skipped": 0, "connection_id": connection_id, "simulated": simulated,
            "sources": [{"name": source_name, "url": url, "tier": tier, "date": date, "figure": figure,
                         "metric": metric, "checked": checked}]}


class Adapter:
    """One data source. Subclasses set the attributes below and implement search(deal)."""

    id = ""
    name = ""
    kind = ""            # Official data, Web search, Import, Licensed data (demo)
    icon = ":material/link:"
    topics = ()          # what it can answer
    provides = ""        # one line for the Connections page
    key_name = None      # the .env setting it needs, if any
    key_help = ""        # one line on how to get the key
    simulated = False    # demo adapters return made-up sample findings
    runs_on_research = True
    default_enabled = True

    def key(self):
        load_dotenv(PROJECT_ROOT / ".env")
        return os.getenv(self.key_name, "").strip() if self.key_name else ""

    def status(self, enabled=True):
        if self.simulated:
            return DEMO if enabled else NEEDS_LICENSE
        if self.key_name and not self.key():
            return NOT_SET_UP
        return CONNECTED

    def search(self, deal):
        raise NotImplementedError


def load_markets(path=MARKETS_FILE):
    return json.loads(Path(path).read_text())["markets"]


def market_for(location, markets=None):
    """The configured market for a deal's location, or None."""
    location = (location or "").lower()
    for market in markets or load_markets():
        if any(word.lower() in location for word in market["match"]):
            return market
    return None


def get_json(url, params=None, body=None, secrets=(), timeout=30):
    """Fetch JSON from an official API. Errors never include the URL, because it may hold a key."""
    full_url = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(full_url, data=data, method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SourceError("The key was rejected. Check it in the .env file.") from None
        if exc.code == 429:
            raise SourceError("The service's rate limit was reached. Try again later.") from None
        raise SourceError(f"The service returned an error ({exc.code}).") from None
    except (urllib.error.URLError, TimeoutError):
        raise SourceError("The service could not be reached. Check the internet connection.") from None
    except json.JSONDecodeError:
        raise SourceError("The service sent back something that was not data.") from None
