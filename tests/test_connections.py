"""Tests for the connections framework. Every adapter is fed simulated replies; nothing calls the internet."""

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from openpyxl import Workbook
from pypdf import PdfWriter

import db
import seed
from services import connections, drafting, gemini, research
from services.connections import base, official
from tests import connection_fakes, research_fakes
from tests.test_extraction import daily_quota_error

FALLOWMERE = {"id": 1, "property_type": "Industrial", "submarket": "Alliance, Fort Worth, TX"}


def with_keys(test_case, keys=None):
    """Use made-up keys instead of the real .env, so no test can ever use a real key."""
    for patcher in (mock.patch.object(base, "load_dotenv"),
                    mock.patch.dict("os.environ", keys if keys is not None else connection_fakes.TEST_KEYS, clear=True)):
        patcher.start()
        test_case.addCleanup(patcher.stop)


def text_pdf(text):
    """A one-page PDF containing the given line of text, built by hand (no extra library)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)


class ConnectionsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "connections.db"
        self.deal_id = seed.seed(self.db_path)["fallowmere"]
        self.deal = dict(FALLOWMERE, id=self.deal_id)
        with_keys(self)

    def findings(self, connection_id=None):
        conn = db.get_connection(self.db_path)
        sql, params = "SELECT * FROM research_findings WHERE deal_id = ?", [self.deal_id]
        if connection_id:
            sql, params = sql + " AND connection_id = ?", params + [connection_id]
        rows = [dict(row) for row in conn.execute(sql + " ORDER BY id", params)]
        conn.close()
        for row in rows:
            row["sources"] = json.loads(row["sources"])
        return rows


class TestOfficialAdapters(ConnectionsTestCase):
    def test_fred_two_calls_and_a_tier_1_finding(self):
        calls = []
        found = official.FredAdapter(fetch=connection_fakes.fake_fetch(calls)).search(self.deal)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1]["search_text"], "Fort Worth Arlington Grapevine unemployment rate")
        self.assertEqual(calls[1][1]["series_id"], "MADEUPFWUR")
        source = found[0]["sources"][0]
        self.assertEqual((found[0]["topic"], source["tier"], source["figure"], source["date"], source["metric"]),
                         ("Employment and demand", 1, "4.4%", "2026-08-01", "unemployment rate"))
        self.assertEqual(source["url"], "https://fred.stlouisfed.org/series/MADEUPFWUR")

    def test_bls_one_call(self):
        calls = []
        found = official.BlsAdapter(fetch=connection_fakes.fake_fetch(calls)).search(self.deal)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2]["seriesid"], ["SMS48231040000000001"])
        self.assertEqual(found[0]["sources"][0]["figure"], "1234.5 thousand jobs")
        self.assertEqual(found[0]["sources"][0]["date"], "August 2026")

    def test_census_one_call(self):
        calls = []
        found = official.CensusAdapter(fetch=connection_fakes.fake_fetch(calls)).search(self.deal)
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0][1]["for"], calls[0][1]["in"]), ("place:27000", "state:48"))
        self.assertEqual([f["sources"][0]["figure"] for f in found], ["900,001 people", "$70,001"])
        self.assertEqual(found[0]["sources"][0]["date"], "ACS 2023 5-year estimates")

    def test_keys_go_only_to_their_own_service_and_never_into_findings(self):
        calls = []
        fetch = connection_fakes.fake_fetch(calls)
        found = [f for adapter in (official.FredAdapter(fetch=fetch), official.BlsAdapter(fetch=fetch),
                                   official.CensusAdapter(fetch=fetch)) for f in adapter.search(self.deal)]
        self.assertEqual(calls[0][1]["api_key"], "test-fred")
        self.assertEqual(calls[2][2]["registrationkey"], "test-bls")
        self.assertEqual(calls[3][1]["key"], "test-census")
        self.assertNotIn("test-", json.dumps(found))

    def test_a_location_with_no_series_is_explained_not_guessed(self):
        with self.assertRaises(connections.SourceError) as caught:
            official.FredAdapter(fetch=connection_fakes.fake_fetch()).search({"property_type": "Office", "submarket": "Nowhere, ZZ"})
        self.assertIn("No official series are set up", str(caught.exception))

    def test_census_not_available_values_are_left_out(self):
        def fetch(url, params=None, body=None, **kwargs):
            return [["NAME", "B01003_001E", "B19013_001E"], ["Fort Worth city, Texas", "900001", "-666666666"]]
        found = official.CensusAdapter(fetch=fetch).search(self.deal)
        self.assertEqual([f["sources"][0]["metric"] for f in found], ["population"])


class TestWebAdapters(ConnectionsTestCase):
    def test_grounded_search_keeps_only_cited_lines_from_trusted_sources(self):
        calls = []
        adapter = connections.GroundedSearchAdapter(client=connection_fakes.fake_grounded_client(calls))
        found = adapter.search(self.deal)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["config"].tools[0].google_search is not None, True)
        self.assertEqual([f["topic"] for f in found], ["Vacancy", "New supply"])  # the blog-only line is dropped
        vacancy = found[0]["sources"][0]
        self.assertEqual((vacancy["name"], vacancy["tier"], vacancy["figure"], vacancy["checked"]),
                         ("cushmanwakefield.com", 2, "7.0%", False))
        self.assertTrue(vacancy["url"].startswith("https://vertexaisearch.cloud.google.com/"))
        self.assertEqual(found[1]["sources"][0]["tier"], 3)

    def test_grounded_search_prompt_has_no_deal_details(self):
        calls = []
        connections.GroundedSearchAdapter(client=connection_fakes.fake_grounded_client(calls)).search(self.deal)
        self.assertIn("Industrial real estate\nmarket in Alliance, Fort Worth, TX", calls[0]["contents"])
        for private in ("Fallowmere", "Vantor", "154,600", "20.33"):
            self.assertNotIn(private, calls[0]["contents"])

    def test_an_answer_without_sources_is_not_used(self):
        reply = connection_fakes.grounded_response()
        reply.candidates[0].grounding_metadata = None
        with self.assertRaises(connections.SourceError):
            connections.GroundedSearchAdapter(client=connection_fakes.fake_grounded_client(reply=reply)).search(self.deal)

    def test_tavily_adapter_wraps_the_checked_research(self):
        queries = []
        adapter = connections.TavilyAdapter(search_fn=research_fakes.fake_search(queries=queries), client=research_fakes.fake_gemini())
        found = adapter.search(self.deal)
        self.assertEqual(len(queries), 4)
        self.assertEqual({f["connection_id"] for f in found}, {"web_search_tavily"})
        self.assertEqual([s["figure"] for s in found[0]["sources"]], ["6.2%", "7.5%"])


class TestStatus(ConnectionsTestCase):
    def test_statuses(self):
        self.assertEqual(official.FredAdapter().status(), "Connected")
        self.assertEqual(connections.CoStarDemo().status(True), "Demo")
        self.assertEqual(connections.CoStarDemo().status(False), "Needs licensed access")

    def test_missing_key_is_not_set_up_with_a_one_line_how_to(self):
        with_keys(self, {})
        for adapter in (official.FredAdapter(), official.BlsAdapter(), official.CensusAdapter(), connections.TavilyAdapter()):
            self.assertEqual(adapter.status(), "Not set up")
            self.assertIn(adapter.key_name, adapter.key_help)
            self.assertNotIn("\n", adapter.key_help)

    def test_demo_sources_start_switched_off_and_live_ones_on(self):
        state = connections.states(self.db_path)
        self.assertFalse(state["demo_costar"]["enabled"])
        self.assertTrue(state["fred"]["enabled"])
        self.assertIsNone(state["fred"]["last_used_at"])

    def test_the_broker_switches_sources_on_and_off(self):
        self.assertTrue(connections.states(self.db_path)["fred"]["enabled"])
        connections.set_enabled("fred", False, self.db_path)
        connections.set_enabled("demo_costar", True, self.db_path)
        state = connections.states(self.db_path)
        self.assertEqual((state["fred"]["enabled"], state["demo_costar"]["enabled"]), (False, True))


class TestRunResearch(ConnectionsTestCase):
    def run_all(self, **options):
        adapters = options.pop("adapters", None) or connection_fakes.adapters()
        return connections.run_research(self.deal, self.db_path, adapters=adapters, **options)

    def test_runs_every_switched_on_source_and_records_last_used(self):
        results = self.run_all()
        self.assertEqual({r["id"]: r["outcome"] for r in results}, {
            "web_search_gemini": "ok", "web_search_tavily": "ok", "fred": "ok", "bls": "ok", "census": "ok"})
        self.assertEqual({f["connection_id"] for f in self.findings()},
                         {"web_search_gemini", "web_search_tavily", "fred", "bls", "census"})
        self.assertIsNotNone(connections.states(self.db_path)["fred"]["last_used_at"])

    def test_one_source_failing_does_not_stop_the_others(self):
        broken = connection_fakes.fake_fetch(fail=connections.SourceError("The service could not be reached."))
        adapters = connection_fakes.adapters()
        adapters[2] = connections.FredAdapter(fetch=broken)
        results = {r["id"]: r for r in self.run_all(adapters=adapters)}
        self.assertEqual(results["fred"]["outcome"], "unavailable")
        self.assertEqual(results["fred"]["message"], "The service could not be reached.")
        self.assertEqual(results["bls"]["outcome"], "ok")
        self.assertEqual(results["web_search_tavily"]["outcome"], "ok")

    def test_an_unexpected_crash_and_a_used_up_quota_are_contained(self):
        adapters = connection_fakes.adapters(grounded_client=connection_fakes.fake_grounded_client(reply=daily_quota_error()))
        adapters[3] = connections.BlsAdapter(fetch=connection_fakes.fake_fetch(fail=RuntimeError("boom")))
        with mock.patch.object(gemini.time, "sleep"):
            results = {r["id"]: r for r in self.run_all(adapters=adapters)}
        self.assertEqual(results["web_search_gemini"]["outcome"], "unavailable")
        self.assertIn("daily quota is used up", results["web_search_gemini"]["message"])
        self.assertEqual(results["bls"]["message"], "Something unexpected went wrong.")
        self.assertEqual(results["census"]["outcome"], "ok")

    def test_a_failing_source_keeps_its_earlier_findings(self):
        self.run_all()
        before = self.findings("fred")
        adapters = connection_fakes.adapters()
        adapters[2] = connections.FredAdapter(fetch=connection_fakes.fake_fetch(fail=connections.SourceError("down")))
        self.run_all(adapters=adapters, force=True)
        self.assertEqual(self.findings("fred"), before)

    def test_missing_key_is_reported_and_never_called(self):
        with_keys(self, {"GEMINI_API_KEY": "test-gemini", "TAVILY_API_KEY": "test-tavily"})
        calls = []
        results = {r["id"]: r for r in self.run_all(adapters=connection_fakes.adapters(fetch=connection_fakes.fake_fetch(calls)))}
        self.assertEqual(results["fred"]["outcome"], "not set up")
        self.assertIn("FRED_API_KEY", results["fred"]["message"])
        self.assertEqual(calls, [])

    def test_switched_off_sources_and_demo_sources_do_not_run_unless_on(self):
        connections.set_enabled("bls", False, self.db_path)
        ids = [r["id"] for r in self.run_all()]
        self.assertNotIn("bls", ids)
        self.assertNotIn("demo_costar", ids)
        connections.set_enabled("demo_costar", True, self.db_path)
        self.assertIn("demo_costar", [r["id"] for r in self.run_all(force=True)])

    def test_results_less_than_a_day_old_are_reused_unless_refreshed(self):
        calls = []
        adapters = connection_fakes.adapters(fetch=connection_fakes.fake_fetch(calls))
        self.run_all(adapters=adapters)
        first = len(calls)
        results = {r["id"]: r["outcome"] for r in self.run_all(adapters=adapters)}
        self.assertEqual(results["fred"], "cached")
        self.assertEqual(len(calls), first)
        later = datetime.now(timezone.utc) + timedelta(hours=25)
        self.run_all(adapters=adapters, now=later)
        self.assertGreater(len(calls), first)
        self.run_all(adapters=adapters, force=True)

    def test_a_deal_without_a_location_is_refused(self):
        with self.assertRaises(ValueError):
            connections.run_research({"id": self.deal_id, "property_type": "Industrial", "submarket": None}, self.db_path,
                                     adapters=connection_fakes.adapters())


class TestSimulatedFindings(ConnectionsTestCase):
    def setUp(self):
        super().setUp()
        connections.set_enabled("demo_costar", True, self.db_path)
        connections.run_research(self.deal, self.db_path, adapters=[connections.CoStarDemo(), connection_fakes.adapters()[1]])
        self.demo = self.findings("demo_costar")

    def test_demo_findings_are_marked_and_obviously_fake(self):
        self.assertEqual(len(self.demo), 2)
        for row in self.demo:
            self.assertEqual(row["simulated"], 1)
            self.assertTrue(row["summary"].startswith("SIMULATED SAMPLE, NOT REAL DATA"))
            self.assertIn("(simulated)", row["sources"][0]["name"])
            self.assertIsNone(row["sources"][0]["url"])

    def test_a_simulated_finding_can_never_be_accepted(self):
        with self.assertRaises(ValueError) as caught:
            research.set_status(self.demo[0]["id"], "accepted", self.db_path)
        self.assertIn("never be accepted", str(caught.exception))
        self.assertEqual(self.findings("demo_costar")[0]["status"], "new")

    def test_simulated_figures_never_reach_the_narrative_or_count_as_disagreement(self):
        conn = db.get_connection(self.db_path)
        with conn:
            conn.execute("UPDATE research_findings SET status = 'accepted' WHERE simulated = 1")  # even if forced
        conn.close()
        facts, _ = drafting.deal_facts(self.deal_id, self.db_path)
        self.assertNotIn("11.1%", facts)
        sources = [dict(s, simulated=True) for s in self.demo[0]["sources"]] + [{"metric": "vacancy rate", "figure": "6.2%"}]
        self.assertEqual(research.disagreements(sources), [])


class TestImportReport(ConnectionsTestCase):
    REPLY = {"findings": [
        {"topic": "Vacancy", "summary": "The report puts vacancy at 6.4% in Q3 2026.", "figure": "6.4%", "metric": "Vacancy rate", "period": "Q3 2026"},
        {"topic": "Asking rent trend", "summary": "Asking rent was $9.99 per SF.", "figure": "$9.99", "metric": "asking rent", "period": None},
        {"topic": "New supply", "summary": "Deliveries slowed.", "figure": "12 buildings", "metric": "deliveries", "period": "Q4 2030"},
        {"topic": "Weather", "summary": "It was sunny.", "figure": None, "metric": None, "period": None}]}

    def import_file(self, filename, data, reply=None, tier=2):
        calls = []
        findings = connections.import_report(self.deal_id, filename, data, "Made-up Brokerage", tier, self.db_path,
                                             client=research_fakes.fake_gemini(reply or self.REPLY, calls))
        return findings, calls

    def xlsx(self, rows):
        path = Path(self.tmp.name) / "report.xlsx"
        workbook = Workbook()
        for row in rows:
            workbook.active.append(row)
        workbook.save(path)
        return path.read_bytes()

    def test_a_spreadsheet_report_becomes_findings_that_cite_the_file(self):
        data = self.xlsx([["Metric", "Value", "Period"], ["Vacancy rate", "6.4%", "Q3 2026"], ["Deliveries", "12 buildings", "Q4 2026"]])
        findings, calls = self.import_file("dfw_q3.xlsx", data)
        self.assertEqual(len(calls), 1)
        self.assertIn("Vacancy rate | 6.4% | Q3 2026", calls[0])
        saved = self.findings("import")
        self.assertEqual([row["topic"] for row in saved], ["Vacancy", "New supply"])  # $9.99 is not in the file; Weather is not a topic
        vacancy = saved[0]["sources"][0]
        self.assertEqual((vacancy["name"], vacancy["tier"], vacancy["figure"], vacancy["date"], vacancy["metric"]),
                         ("dfw_q3.xlsx (imported, Made-up Brokerage)", 2, "6.4%", "Q3 2026", "vacancy rate"))
        supply = saved[1]["sources"][0]
        self.assertEqual((supply["figure"], supply["date"]), ("12 buildings", None))  # the period Q4 2030 is not in the file

    def test_csv_and_pdf_reports(self):
        # Vacancy is kept with its figure. "Deliveries slowed." has no number, so it is kept but its
        # figure (not in the file) is dropped: words without numbers cannot be checked in code.
        csv = b"Metric,Value\nVacancy rate,6.4%\nAs of,Q3 2026\n"
        found, calls = self.import_file("report.csv", csv)
        self.assertEqual([(f["topic"], f["sources"][0]["figure"]) for f in found], [("Vacancy", "6.4%"), ("New supply", None)])
        self.assertIn("Vacancy rate | 6.4%", calls[0])
        pdf = text_pdf("Industrial vacancy was 6.4% in Q3 2026.")
        found, calls = self.import_file("report.pdf", pdf)
        self.assertIn("Industrial vacancy was 6.4% in Q3 2026.", calls[0])
        self.assertEqual(found[0]["sources"][0]["figure"], "6.4%")

    def test_imports_are_added_not_replaced(self):
        csv = b"Metric,Value\nVacancy rate,6.4%\nAs of,Q3 2026\n"
        self.import_file("a.csv", csv)
        self.import_file("b.csv", csv)
        self.assertEqual(len(self.findings("import")), 4)

    def test_a_locked_pdf_needs_a_password_and_is_never_sent(self):
        writer = PdfWriter()
        writer.add_blank_page(612, 792)
        writer.encrypt("secret")
        path = Path(self.tmp.name) / "locked.pdf"
        with open(path, "wb") as handle:
            writer.write(handle)
        with self.assertRaises(connections.SourceError) as caught:
            self.import_file("locked.pdf", path.read_bytes(), reply=AssertionError("must not be called"))
        self.assertIn("Needs password", str(caught.exception))

    def test_bad_files_and_missing_tier_are_refused_without_calling_gemini(self):
        for filename, data, tier in (("notes.txt", b"hello", 2), ("report.csv", b"Metric,Value\n", None),
                                     ("report.pdf", b"not a pdf", 2)):
            with self.subTest(filename):
                with self.assertRaises(connections.SourceError):
                    self.import_file(filename, data, reply=AssertionError("must not be called"), tier=tier)
        self.assertEqual(self.findings("import"), [])


class TestMigration(unittest.TestCase):
    def test_existing_findings_keep_their_data_and_gain_the_new_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE deals (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
                INSERT INTO deals (id, name) VALUES (1, 'Made-up');
                CREATE TABLE research_findings (id INTEGER PRIMARY KEY AUTOINCREMENT, deal_id INTEGER NOT NULL,
                    topic TEXT NOT NULL, summary TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '[]',
                    skipped INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'new',
                    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                INSERT INTO research_findings (deal_id, topic, summary, status) VALUES (1, 'Vacancy', 'Kept as it was.', 'accepted');
            """)
            conn.commit()
            conn.close()
            db.init_db(path)
            db.init_db(path)  # running it twice is harmless
            conn = db.get_connection(path)
            row = dict(conn.execute("SELECT * FROM research_findings").fetchone())
            conn.close()
        self.assertEqual((row["summary"], row["status"], row["connection_id"], row["simulated"]),
                         ("Kept as it was.", "accepted", "web_search_tavily", 0))


if __name__ == "__main__":
    unittest.main()
