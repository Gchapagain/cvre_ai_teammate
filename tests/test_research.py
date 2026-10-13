"""Tests for the research service. Search results and Gemini are always simulated."""

import copy
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import db
import seed
from services import deals, gemini, research
from tests.research_fakes import REPLY, RESULTS, fake_gemini, fake_search
from tests.test_extraction import daily_quota_error


class TestTiers(unittest.TestCase):
    def test_each_tier(self):
        self.assertEqual(research.classify("https://www.bls.gov/eag/"), (1, "bls.gov"))
        self.assertEqual(research.classify("https://data.census.gov/table"), (1, "data.census.gov"))
        self.assertEqual(research.classify("https://www.anycounty.gov/planning"), (1, "anycounty.gov"))
        self.assertEqual(research.classify("https://fred.stlouisfed.org/series/X"), (1, "fred.stlouisfed.org"))
        self.assertEqual(research.classify("https://www.cbre.com/insights"), (2, "cbre.com"))
        self.assertEqual(research.classify("https://www.us.jll.com/en/research"), (2, "us.jll.com"))
        self.assertEqual(research.classify("https://www.bisnow.com/dallas"), (3, "bisnow.com"))

    def test_unknown_and_lookalike_sources_are_not_trusted(self):
        for url in ("https://randomblog.example.com/post", "https://notcbre.com/report", "https://cbre.com.evil.net/x",
                    "https://bls.gov.fake.org/x", "not a url", ""):
            self.assertIsNone(research.classify(url)[0], url)

    def test_the_list_lives_in_one_config_file_with_three_tiers(self):
        tiers = research.load_tiers()
        self.assertEqual([entry["tier"] for entry in tiers], [1, 2, 3])
        firms = tiers[1]["domains"]
        for domain in ("cbre.com", "jll.com", "cushmanwakefield.com", "colliers.com", "nmrk.com"):
            self.assertIn(domain, firms)

    def test_a_different_config_changes_the_answer(self):
        custom = [{"tier": 1, "label": "x", "suffixes": [], "domains": ["example.org"]}]
        self.assertEqual(research.classify("https://example.org/a", custom), (1, "example.org"))
        self.assertIsNone(research.classify("https://www.bls.gov/", custom)[0])


class ResearchTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "research.db"
        self.deal_id = seed.seed(self.db_path)["fallowmere"]
        self.queries, self.prompts = [], []

    def run_research(self, results=None, reply=None):
        return research.run_research(self.deal_id, search=fake_search(results, self.queries),
                                     client=fake_gemini(reply, self.prompts), db_path=self.db_path)

    def saved(self):
        conn = db.get_connection(self.db_path)
        rows = [dict(row) for row in conn.execute("SELECT * FROM research_findings ORDER BY id")]
        conn.close()
        for row in rows:
            row["sources"] = json.loads(row["sources"])
        return {row["topic"]: row for row in rows}


class TestRun(ResearchTestCase):
    def test_four_searches_and_one_gemini_request(self):
        self.run_research()
        self.assertEqual(len(self.queries), 4)
        self.assertEqual(len(self.prompts), 1)

    def test_queries_use_only_property_type_location_and_topic(self):
        self.run_research()
        self.assertEqual(self.queries[0], "Industrial real estate Alliance, Fort Worth, TX vacancy rate")
        everything_sent = " ".join(self.queries) + self.prompts[0]
        for private in ("Fallowmere", "Vantor Robotics", "Harbor & Pine", "154,600", "154600", "20.33", "1244311"):
            self.assertNotIn(private, everything_sent)

    def test_findings_are_saved_as_new_with_tiers_dates_and_figures(self):
        self.run_research()
        saved = self.saved()
        self.assertEqual(list(saved), ["Vacancy", "Asking rent trend", "New supply", "Employment and demand"])
        self.assertEqual({row["status"] for row in saved.values()}, {"new"})
        self.assertEqual(saved["Employment and demand"]["sources"], [{
            "name": "bls.gov", "url": "https://www.bls.gov/eag/eag.tx_fortworth_md.htm", "tier": 1,
            "date": "2026-09-20", "figure": "4.1%", "metric": "unemployment rate"}])
        supply = saved["New supply"]["sources"][0]
        self.assertEqual((supply["tier"], supply["date"], supply["figure"]), (2, "mid-year 2026", "4.1 million square feet"))
        rent = saved["Asking rent trend"]["sources"][0]
        self.assertEqual((rent["tier"], rent["figure"], rent["metric"]), (3, None, None))
        self.assertTrue(all(row["fetched_at"] for row in saved.values()))

    def test_untrusted_sources_are_skipped_and_counted_never_shown(self):
        self.run_research()
        vacancy = self.saved()["Vacancy"]
        self.assertEqual(vacancy["skipped"], 1)
        self.assertEqual([s["name"] for s in vacancy["sources"]], ["cbre.com", "jll.com"])
        self.assertNotIn("randomblog", json.dumps(vacancy["sources"]) + self.prompts[0])

    def test_running_again_replaces_the_findings(self):
        self.run_research()
        first = self.saved()["Vacancy"]["id"]
        research.set_status(first, "accepted", self.db_path)
        self.run_research()
        saved = self.saved()
        self.assertEqual(len(saved), 4)
        self.assertNotEqual(saved["Vacancy"]["id"], first)
        self.assertEqual(saved["Vacancy"]["status"], "new")

    def test_a_deal_without_a_location_is_refused_before_any_search(self):
        deal_id = deals.create_deal("Made-up, no location", "Industrial", None, db_path=self.db_path)
        with self.assertRaises(ValueError):
            research.run_research(deal_id, search=fake_search(queries=self.queries), client=fake_gemini(), db_path=self.db_path)
        self.assertEqual(self.queries, [])


class TestSourcesDisagree(ResearchTestCase):
    def test_both_figures_are_kept_and_the_disagreement_is_reported(self):
        self.run_research()
        sources = self.saved()["Vacancy"]["sources"]
        self.assertEqual([s["figure"] for s in sources], ["6.2%", "7.5%"])
        self.assertEqual(research.disagreements(sources), ["vacancy rate"])

    def test_no_merged_or_averaged_figure_is_stored(self):
        self.run_research()
        stored = json.dumps(self.saved()["Vacancy"])
        for merged in ("6.85", "6.9", "13.7"):
            self.assertNotIn(merged, stored)

    def test_matching_figures_or_different_metrics_are_not_a_disagreement(self):
        same = [{"metric": "vacancy rate", "figure": "6.2%"}, {"metric": "vacancy rate", "figure": "6.20 percent"}]
        different_things = [{"metric": "vacancy rate", "figure": "6.2%"}, {"metric": "availability rate", "figure": "9%"}]
        no_figures = [{"metric": None, "figure": None}, {"metric": "vacancy rate", "figure": "6.2%"}]
        for sources in (same, different_things, no_figures, []):
            self.assertEqual(research.disagreements(sources), [])


class TestNothingFound(ResearchTestCase):
    def test_only_untrusted_sources_means_no_findings_and_no_gemini_call(self):
        junk = {terms: [{"url": "https://randomblog.example.com/x", "content": "Vacancy is 3%."}] for terms in RESULTS}
        self.run_research(results=junk, reply=AssertionError("must not be called"))
        self.assertEqual(self.prompts, [])
        saved = self.saved()
        self.assertEqual(len(saved), 4)
        for row in saved.values():
            self.assertEqual((row["summary"], row["sources"], row["skipped"]), ("No reliable public sources found.", [], 1))

    def test_no_results_at_all(self):
        self.run_research(results={})
        self.assertEqual({row["summary"] for row in self.saved().values()}, {"No reliable public sources found."})

    def test_a_topic_with_no_sources_says_so_even_if_gemini_makes_something_up(self):
        results = {"vacancy rate": RESULTS["vacancy rate"]}
        reply = copy.deepcopy(REPLY)
        reply["topics"][3]["summary"] = "Employment is booming, up 9%."
        self.run_research(results=results, reply=reply)
        employment = self.saved()["Employment and demand"]
        self.assertEqual((employment["summary"], employment["sources"]), ("No reliable public sources found.", []))

    def test_a_finding_with_no_sources_cannot_be_accepted(self):
        self.run_research(results={})
        finding_id = self.saved()["Vacancy"]["id"]
        with self.assertRaises(ValueError):
            research.set_status(finding_id, "accepted", self.db_path)
        self.assertEqual(self.saved()["Vacancy"]["status"], "new")


class TestFiguresAreCheckedAgainstTheSource(ResearchTestCase):
    def reply_with(self, **changes):
        reply = copy.deepcopy(REPLY)
        reply["topics"][0]["sources"][0].update(changes)
        return reply

    def test_a_figure_that_is_not_in_its_source_is_dropped(self):
        self.run_research(reply=self.reply_with(figure="5.9%"))
        first = self.saved()["Vacancy"]["sources"][0]
        self.assertEqual((first["figure"], first["metric"]), (None, None))

    def test_a_figure_borrowed_from_another_source_is_dropped(self):
        self.run_research(reply=self.reply_with(figure="7.5%"))
        self.assertIsNone(self.saved()["Vacancy"]["sources"][0]["figure"])

    def test_a_period_that_is_not_in_the_source_is_dropped_but_the_published_date_stays(self):
        self.run_research(reply=self.reply_with(period="Q3 2026"))
        self.assertEqual(self.saved()["Vacancy"]["sources"][0]["date"], "2026-07-18")

    def test_a_summary_with_a_number_no_source_states_is_replaced(self):
        reply = copy.deepcopy(REPLY)
        reply["topics"][0]["summary"] = "Vacancy averages about 6.85% across sources."
        self.run_research(reply=reply)
        self.assertEqual(self.saved()["Vacancy"]["summary"], "Sources were found; what each one says is listed below.")

    def test_a_source_id_gemini_made_up_is_ignored(self):
        reply = copy.deepcopy(REPLY)
        reply["topics"][0]["sources"].append({"id": "V9", "metric": "vacancy rate", "figure": "1%", "period": None})
        self.run_research(reply=reply)
        self.assertEqual(len(self.saved()["Vacancy"]["sources"]), 2)


class TestFailuresKeepEarlierFindings(ResearchTestCase):
    def test_search_and_ai_failures(self):
        self.run_research()
        before = self.saved()
        with self.assertRaises(research.SearchError):
            self.run_research(results=research.SearchError("limit reached"))
        with mock.patch.object(gemini.time, "sleep"), self.assertRaises(gemini.GeminiQuotaError):
            self.run_research(reply=daily_quota_error())
        with self.assertRaises(gemini.GeminiError):
            self.run_research(reply="not json")
        self.assertEqual(self.saved(), before)


class TestAcceptAndDismiss(ResearchTestCase):
    def test_a_person_sets_the_status(self):
        self.run_research()
        finding_id = self.saved()["Vacancy"]["id"]
        research.set_status(finding_id, "accepted", self.db_path)
        self.assertEqual(self.saved()["Vacancy"]["status"], "accepted")
        research.set_status(finding_id, "dismissed", self.db_path)
        self.assertEqual(self.saved()["Vacancy"]["status"], "dismissed")
        self.assertEqual(self.saved()["New supply"]["status"], "new")


class TestSearchClient(unittest.TestCase):
    KEY = "tvly-made-up-test-key"

    def test_missing_key_gives_a_clear_message(self):
        with mock.patch.object(research, "load_dotenv"), mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(research.SearchError) as caught:
                research.search_key()
        self.assertIn("TAVILY_API_KEY", str(caught.exception))

    def test_request_carries_the_query_and_the_key_only_in_the_header(self):
        sent = {}

        def urlopen(request, timeout):
            sent["url"], sent["headers"], sent["body"] = request.full_url, dict(request.headers), json.loads(request.data)
            return io.BytesIO(json.dumps({"results": [{"url": "https://www.bls.gov/x", "content": "text"}]}).encode())
        with mock.patch.object(research.urllib.request, "urlopen", urlopen):
            results = research.tavily_search("Industrial real estate Somewhere vacancy rate", self.KEY)
        self.assertEqual(results, [{"url": "https://www.bls.gov/x", "content": "text"}])
        self.assertEqual(sent["url"], "https://api.tavily.com/search")
        self.assertEqual(sent["headers"]["Authorization"], f"Bearer {self.KEY}")
        self.assertEqual(sent["body"], {"query": "Industrial real estate Somewhere vacancy rate", "max_results": 5, "search_depth": "basic"})
        self.assertNotIn(self.KEY, json.dumps(sent["body"]))

    def test_errors_are_friendly_and_never_contain_the_key(self):
        failures = {
            401: "rejected the key", 429: "free limit has been reached", 500: "returned an error (500)",
        }
        for code, expected in failures.items():
            error = urllib.error.HTTPError("https://api.tavily.com/search", code, "x", {}, io.BytesIO(self.KEY.encode()))
            with mock.patch.object(research.urllib.request, "urlopen", side_effect=error):
                with self.assertRaises(research.SearchError) as caught:
                    research.tavily_search("q", self.KEY)
            self.assertIn(expected, str(caught.exception))
            self.assertNotIn(self.KEY, str(caught.exception))
        with mock.patch.object(research.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(research.SearchError) as caught:
                research.tavily_search("q", self.KEY)
        self.assertIn("could not be reached", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
