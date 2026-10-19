"""Connections: every data source the research feature can use, behind one small interface.

To add a source, write an Adapter (see base.py), give it a unique id, and add it to ALL below.
Rules every adapter follows: official APIs, free public data, cited web search or an imported file
only; never scraping; keys only from .env; calls only when a person clicks a button.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import db
from services import gemini
from services.connections.base import CONNECTED, DEMO, NEEDS_LICENSE, NOT_SET_UP, Adapter, SourceError
from services.connections.demo import LICENSE_NOTE, CoStarDemo, LinkedInDemo, LoopNetCrexiDemo, RedfinDemo, ZillowDemo
from services.connections.imported import ImportAdapter
from services.connections.official import BlsAdapter, CensusAdapter, FredAdapter
from services.connections.web import GroundedSearchAdapter, TavilyAdapter

log = logging.getLogger(__name__)
CACHE_HOURS = 24


def all_adapters():
    return [GroundedSearchAdapter(), TavilyAdapter(), FredAdapter(), BlsAdapter(), CensusAdapter(), ImportAdapter(),
            LinkedInDemo(), CoStarDemo(), LoopNetCrexiDemo(), ZillowDemo(), RedfinDemo()]


def by_id(connection_id, adapters=None):
    return next((a for a in adapters or all_adapters() if a.id == connection_id), None)


def states(db_path=None, adapters=None):
    """{id: {"enabled": bool, "last_used_at": str or None}} for every connection. Only reads."""
    path = Path(db_path or db.DB_PATH)
    rows = {}
    if path.exists():
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM connections")}
        except sqlite3.OperationalError:
            rows = {}  # a database from before connections existed: every source uses its default
        finally:
            conn.close()
    return {a.id: {"enabled": bool(rows[a.id]["enabled"]) if a.id in rows else a.default_enabled,
                   "last_used_at": rows.get(a.id, {}).get("last_used_at")} for a in adapters or all_adapters()}


def set_enabled(connection_id, enabled, db_path=None):
    """Switch a source on or off (a broker's choice on the Connections page)."""
    db.init_db(db_path)
    conn = db.get_connection(db_path)
    try:
        with conn:
            conn.execute("INSERT INTO connections (id, enabled) VALUES (?, ?) "
                         "ON CONFLICT(id) DO UPDATE SET enabled = excluded.enabled", (connection_id, int(enabled)))
    finally:
        conn.close()


def _touch(conn, connection_id, default_enabled):
    conn.execute("INSERT INTO connections (id, enabled, last_used_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                 "ON CONFLICT(id) DO UPDATE SET last_used_at = CURRENT_TIMESTAMP", (connection_id, int(default_enabled)))


def save_findings(deal_id, adapter, findings, db_path=None):
    """Replace one connection's findings for a deal and record that it was used."""
    db.init_db(db_path)
    conn = db.get_connection(db_path)
    try:
        with conn:
            if adapter.runs_on_research:
                conn.execute("DELETE FROM research_findings WHERE deal_id = ? AND connection_id = ?", (deal_id, adapter.id))
            conn.executemany(
                "INSERT INTO research_findings (deal_id, topic, summary, sources, skipped, connection_id, simulated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(deal_id, f["topic"], f["summary"], json.dumps(f["sources"]), f.get("skipped", 0), adapter.id,
                  int(bool(f.get("simulated") or adapter.simulated))) for f in findings],
            )
            _touch(conn, adapter.id, adapter.default_enabled)
    finally:
        conn.close()


def _fresh(conn, deal_id, connection_id, now):
    row = conn.execute("SELECT MAX(fetched_at) AS last FROM research_findings WHERE deal_id = ? AND connection_id = ?",
                       (deal_id, connection_id)).fetchone()
    if not row["last"]:
        return False
    fetched = datetime.fromisoformat(row["last"]).replace(tzinfo=timezone.utc)
    return now - fetched < timedelta(hours=CACHE_HOURS)


def _friendly(exc):
    if isinstance(exc, (SourceError, gemini.GeminiError, ValueError)):
        return str(exc)
    log.exception("A connection failed")
    return "Something unexpected went wrong."


def runnable(adapter, enabled):
    """Whether Run research should call this source: switched on, set up, and not an import."""
    return adapter.runs_on_research and enabled and adapter.status(enabled) in (CONNECTED, DEMO)


def run_research(deal, db_path=None, adapters=None, force=False, progress=lambda name, message: None, now=None):
    """Run every switched-on source for a deal, one at a time. One failing never stops the others.

    Returns [{"id", "name", "outcome", "message", "count"}] with outcome ok / cached / unavailable / not set up.
    A source with results from the last 24 hours is not called again unless force is True.
    """
    if not deal.get("property_type") or not deal.get("submarket"):
        raise ValueError("Research needs the deal's property type and location. Add them first.")
    adapters = adapters or all_adapters()
    enabled = states(db_path, adapters)
    now = now or datetime.now(timezone.utc)
    results = []
    for adapter in adapters:
        on = enabled[adapter.id]["enabled"]
        if not adapter.runs_on_research or not on:
            continue
        if adapter.status(on) == NOT_SET_UP:
            results.append({"id": adapter.id, "name": adapter.name, "outcome": "not set up", "message": adapter.key_help, "count": 0})
            continue
        conn = db.get_connection(db_path)
        try:
            cached = not force and _fresh(conn, deal["id"], adapter.id, now)
        finally:
            conn.close()
        if cached:
            results.append({"id": adapter.id, "name": adapter.name, "outcome": "cached",
                            "message": f"Used results from the last {CACHE_HOURS} hours.", "count": 0})
            progress(adapter.name, "used recent results")
            continue
        progress(adapter.name, "asking...")
        try:
            findings = adapter.search(deal)
        except Exception as exc:
            results.append({"id": adapter.id, "name": adapter.name, "outcome": "unavailable", "message": _friendly(exc), "count": 0})
            progress(adapter.name, "Source unavailable")
            continue
        save_findings(deal["id"], adapter, findings, db_path)
        results.append({"id": adapter.id, "name": adapter.name, "outcome": "ok", "message": "", "count": len(findings)})
        progress(adapter.name, f"{len(findings)} finding(s)")
    return results


def import_report(deal_id, filename, data, publisher, tier, db_path=None, client=None):
    """Read an imported report and save its findings. One Gemini request. Returns the findings."""
    adapter = ImportAdapter(client=client)
    findings = adapter.read(filename, data, publisher, tier)
    save_findings(deal_id, adapter, findings, db_path)
    return findings


__all__ = ["BlsAdapter", "CensusAdapter", "CoStarDemo", "FredAdapter", "GroundedSearchAdapter", "TavilyAdapter",
           "ImportAdapter", "LinkedInDemo", "LoopNetCrexiDemo", "ZillowDemo", "RedfinDemo", "Adapter", "CONNECTED", "DEMO", "NEEDS_LICENSE", "NOT_SET_UP", "LICENSE_NOTE", "SourceError",
           "all_adapters", "by_id", "states", "set_enabled", "run_research", "import_report", "runnable"]
