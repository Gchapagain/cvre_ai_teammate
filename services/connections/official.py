"""Official public data: FRED (St. Louis Fed), BLS and the Census Bureau. Free keys, Tier 1 sources.

Each adapter only answers for markets listed in config/market_data.json.
"""

from services.connections.base import Adapter, SourceError, finding, get_json, market_for

FRED_URL = "https://api.stlouisfed.org/fred"
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
CENSUS_URL = "https://api.census.gov/data/{year}/acs/acs5"


def _no_market(deal):
    raise SourceError(f"No official series are set up for '{deal.get('submarket') or 'this location'}' yet "
                      "(see config/market_data.json).")


class FredAdapter(Adapter):
    id, name, kind, icon = "fred", "FRED (St. Louis Fed)", "Official data", ":material/account_balance:"
    topics = ("Employment and demand",)
    provides = "The latest local unemployment rate, from the Federal Reserve Bank of St. Louis."
    key_name = "FRED_API_KEY"
    key_help = "Free key: fredaccount.stlouisfed.org, then add FRED_API_KEY=... to .env."

    def __init__(self, fetch=get_json, markets=None):
        self.fetch, self.markets = fetch, markets

    def search(self, deal):
        """Two API calls: find the series, then read its latest value."""
        market = market_for(deal.get("submarket"), self.markets) or _no_market(deal)
        found = self.fetch(f"{FRED_URL}/series/search", {
            "search_text": market["fred_search"], "api_key": self.key(), "file_type": "json",
            "order_by": "popularity", "sort_order": "desc", "limit": 1})
        if not found.get("seriess"):
            return []
        series = found["seriess"][0]
        latest = self.fetch(f"{FRED_URL}/series/observations", {
            "series_id": series["id"], "api_key": self.key(), "file_type": "json", "sort_order": "desc", "limit": 1})
        observations = [o for o in latest.get("observations", []) if o.get("value") not in (None, "", ".")]
        if not observations:
            return []
        value, date = observations[0]["value"], observations[0]["date"]
        unit = "%" if "percent" in series.get("units", "").lower() else f" {series.get('units', '')}".rstrip()
        return [finding("Employment and demand", f"{series['title']}: {value}{unit} ({date}).", "FRED, St. Louis Fed",
                        1, self.id, figure=f"{value}{unit}", metric=market.get("fred_metric", "unemployment rate"),
                        url=f"https://fred.stlouisfed.org/series/{series['id']}", date=date)]


class BlsAdapter(Adapter):
    id, name, kind, icon = "bls", "BLS (Bureau of Labor Statistics)", "Official data", ":material/work:"
    topics = ("Employment and demand",)
    provides = "Local employment counts from the U.S. Bureau of Labor Statistics."
    key_name = "BLS_API_KEY"
    key_help = "Free key: data.bls.gov/registrationEngine, then add BLS_API_KEY=... to .env."

    def __init__(self, fetch=get_json, markets=None):
        self.fetch, self.markets = fetch, markets

    def search(self, deal):
        """One API call for all the market's series."""
        market = market_for(deal.get("submarket"), self.markets) or _no_market(deal)
        wanted = {s["id"]: s for s in market.get("bls_series", [])}
        if not wanted:
            return []
        reply = self.fetch(BLS_URL, body={"seriesid": list(wanted), "registrationkey": self.key(), "latest": True})
        if reply.get("status") != "REQUEST_SUCCEEDED":
            raise SourceError("BLS did not return the data: " + "; ".join(reply.get("message", [])[:1] or ["no reason given"]))
        findings = []
        for series in reply.get("Results", {}).get("series", []):
            info, data = wanted.get(series.get("seriesID")), series.get("data") or []
            if not info or not data:
                continue
            point = data[0]
            date = f"{point.get('periodName', '')} {point.get('year', '')}".strip()
            figure = f"{point['value']} {info['unit']}"
            findings.append(finding("Employment and demand", f"{info['label']}: {figure} ({date}).", "BLS", 1, self.id,
                                    figure=figure, metric=info["metric"], date=date,
                                    url=f"https://data.bls.gov/timeseries/{series['seriesID']}"))
        return findings


class CensusAdapter(Adapter):
    id, name, kind, icon = "census", "U.S. Census Bureau", "Official data", ":material/groups:"
    topics = ("Population and income",)
    provides = "Population and median household income from the American Community Survey."
    key_name = "CENSUS_API_KEY"
    key_help = "Free key: api.census.gov/data/key_signup.html, then add CENSUS_API_KEY=... to .env."

    def __init__(self, fetch=get_json, markets=None):
        self.fetch, self.markets = fetch, markets

    def search(self, deal):
        """One API call."""
        market = market_for(deal.get("submarket"), self.markets) or _no_market(deal)
        census = market.get("census")
        if not census:
            return []
        codes = [v["code"] for v in census["variables"]]
        rows = self.fetch(CENSUS_URL.format(year=census["year"]), {
            "get": ",".join(["NAME"] + codes), "for": census["for"], "in": census["in"], "key": self.key()})
        if not isinstance(rows, list) or len(rows) < 2:
            return []
        values = dict(zip(rows[0], rows[1]))
        date = f"ACS {census['year']} 5-year estimates"
        findings = []
        for variable in census["variables"]:
            value = values.get(variable["code"])
            if value in (None, "", "-666666666") or str(value).startswith("-"):
                continue  # the Census uses large negative numbers to mean "not available"
            figure = f"${int(float(value)):,}" if variable["unit"] == "dollars" else f"{int(float(value)):,} {variable['unit']}"
            findings.append(finding("Population and income", f"{variable['label']}, {values.get('NAME', census['place_name'])}: {figure}.",
                                    "U.S. Census Bureau", 1, self.id, figure=figure, metric=variable["metric"],
                                    date=date, url="https://data.census.gov/"))
        return findings
