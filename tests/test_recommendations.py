"""Tests for recommendations. Gemini is always simulated; research findings come from simulated sources."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import db
import seed
from services import connections, drafting, gemini, recommendations
from tests import connection_fakes
from tests.test_connections import with_keys
from tests.test_extraction import daily_quota_error, read_source_units
from tests.test_metrics import unit

TODAY = date(2026, 10, 14)
NAMES = {a.id: a.name for a in connections.all_adapters()}
DOCS = [{"filename": "rent_roll.xlsx", "used_for": "Rent roll", "received_at": "2026-10-14 09:00:00"}]


def keyed(recs):
    return {rec["rule_key"]: rec for rec in recs}


class TestRuleRecommendations(unittest.TestCase):
    def test_sample_deal(self):
        flags = [{"unit_number": "110", "rule": "rent_per_sf_above_2x_average", "field": "rent_per_sf",
                  "message": "Unit 110 rent/SF is $20.33, which is 2.37x the average of the other 11 unit(s) ($8.60). The limit is 2x ($17.19).",
                  "actual_value": "20.33", "threshold": "17.19"}]
        recs = keyed(recommendations.rule_recommendations(read_source_units(), flags, [{"line_item": "x"}], DOCS, TODAY))
        self.assertEqual(list(recs), ["flag:110:rent_per_sf_above_2x_average", "expiring:0-12", "expiring:12-24"])
        flag = recs["flag:110:rent_per_sf_above_2x_average"]
        self.assertEqual((flag["title"], flag["priority"], flag["kind"]),
                         ("Confirm unit 110 with the property manager before pricing", "High", "rule"))
        self.assertEqual(flag["why"], flags[0]["message"])
        self.assertIn("rent_per_sf_above_2x_average", flag["rule"])
        self.assertEqual(flag["evidence"], [{"name": "rent_roll.xlsx", "tier": None, "date": "2026-10-14",
                                             "connection": "From this deal", "figure": None, "metric": None}])
        twelve = recs["expiring:0-12"]
        self.assertEqual(twelve["priority"], "High")
        self.assertEqual(twelve["why"], "4 leases (44,700 SF, 28.9% of total SF) end in the next 12 months, counted from "
                                        "2026-10-14: units 101, 106, 109, 111.")
        self.assertEqual(recs["expiring:12-24"]["priority"], "Medium")
        self.assertIn("4 leases (49,700 SF, 32.1% of total SF) end in months 13 to 24", recs["expiring:12-24"]["why"])

    def test_expiry_priority_follows_the_share_threshold(self):
        units = [unit("A", 1000, end="2027-06-01"), unit("B", 9000, end="2031-01-01")]
        self.assertEqual(keyed(recommendations.rule_recommendations(units, [], [1], DOCS, TODAY))["expiring:0-12"]["priority"], "Medium")
        units = [unit("A", 2000, end="2027-06-01"), unit("B", 8000, end="2031-01-01")]
        self.assertEqual(keyed(recommendations.rule_recommendations(units, [], [1], DOCS, TODAY))["expiring:0-12"]["priority"], "High")

    def test_tenant_concentration(self):
        units = [unit("A", 2400, tenant="Gantry Lane Books"), unit("B", 7600, tenant="Big Tenant Co.")]
        rec = keyed(recommendations.rule_recommendations(units, [], [1], DOCS, TODAY))["concentration"]
        self.assertEqual((rec["title"], rec["priority"]), ("Review tenant concentration: Big Tenant Co.", "High"))
        self.assertEqual(rec["why"], "Big Tenant Co. occupies 7,600 SF, 76.0% of the 10,000 SF total.")
        units = [unit("A", 7000), unit("B", 3000)]
        self.assertEqual(keyed(recommendations.rule_recommendations(units, [], [1], DOCS, TODAY))["concentration"]["priority"], "High")
        units = [unit("A", 3000), unit("B", 3000), unit("C", 4000)]
        self.assertEqual(keyed(recommendations.rule_recommendations(units, [], [1], DOCS, TODAY))["concentration"]["priority"], "Medium")
        units = [unit(str(n), 1000) for n in range(5)]
        self.assertNotIn("concentration", keyed(recommendations.rule_recommendations(units, [], [1], DOCS, TODAY)))

    def test_missing_values_become_one_follow_up(self):
        flags = [{"unit_number": "3", "rule": "missing_value", "field": "monthly_rent", "message": "", "actual_value": None, "threshold": "required"},
                 {"unit_number": "4", "rule": "non_numeric_value", "field": "square_feet", "message": "", "actual_value": "big", "threshold": "a number"}]
        recs = keyed(recommendations.rule_recommendations([unit("3", 1000)], flags, [1], DOCS, TODAY))
        self.assertNotIn("flag:3:missing_value", recs)
        rec = recs["data-quality"]
        self.assertEqual((rec["title"], rec["priority"]), ("Follow up on 2 missing or invalid values", "High"))
        self.assertEqual(rec["why"], "unit 3: a value is missing (monthly_rent); unit 4: a value is not a number (square_feet).")

    def test_no_t12_and_no_data(self):
        self.assertIn("no-t12", keyed(recommendations.rule_recommendations([unit("A", 1000)], [], [], DOCS, TODAY)))
        self.assertEqual(recommendations.rule_recommendations([], [], [], [], TODAY), [])


class AiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "recs.db"
        self.deal_id = seed.seed(self.db_path)["fallowmere"]
        with_keys(self)
        connections.set_enabled("demo_costar", True, self.db_path)
        connections.run_research({"id": self.deal_id, "property_type": "Industrial", "submarket": "Alliance, Fort Worth, TX"},
                                 self.db_path, adapters=connection_fakes.adapters())
        self.ids = {(r["connection_id"], r["topic"]): r["id"] for r in recommendations.research_inputs(self.deal_id, self.db_path)}
        conn = db.get_connection(self.db_path)
        self.demo_id = conn.execute("SELECT id FROM research_findings WHERE simulated = 1").fetchone()["id"]
        conn.close()
        self.prompts = []

    def generate(self, items):
        reply = items if isinstance(items, (str, Exception)) else json.dumps({"recommendations": items})

        def generate_content(**kwargs):
            self.prompts.append(kwargs["contents"])
            if isinstance(reply, Exception):
                raise reply
            return SimpleNamespace(text=reply)
        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
        return recommendations.generate_ai(self.deal_id, NAMES, client=client, db_path=self.db_path, today=TODAY)

    def saved(self):
        conn = db.get_connection(self.db_path)
        rows = [dict(r) for r in conn.execute("SELECT * FROM recommendations WHERE kind = 'ai' ORDER BY id")]
        conn.close()
        return rows

    def rec(self, ids, why="Local unemployment was 4.4% in 2026-08-01.", title="Watch labour supply", step="Ask leasing about hiring."):
        return {"title": title, "why": why, "next_step": step, "finding_ids": ids}


class TestAiRecommendations(AiTestCase):
    def test_one_request_with_real_findings_and_never_simulated_ones(self):
        self.generate([])
        self.assertEqual(len(self.prompts), 1)
        prompt = self.prompts[0]
        self.assertIn(f"[F{self.ids[('fred', 'Employment and demand')]}]", prompt)
        self.assertIn("FRED, St. Louis Fed (Tier 1, 2026-08-01): 4.4%", prompt)
        self.assertNotIn(f"[F{self.demo_id}]", prompt)
        self.assertNotIn("SIMULATED", prompt)
        self.assertNotIn("11.1%", prompt)

    def test_a_cited_recommendation_with_matching_numbers_is_kept(self):
        fred = self.ids[("fred", "Employment and demand")]
        kept, removed = self.generate([self.rec([fred])])
        self.assertEqual((len(kept), removed), (1, 0))
        saved = self.saved()[0]
        self.assertEqual((saved["title"], saved["priority"], saved["status"]), ("Watch labour supply", "High", "new"))
        evidence = json.loads(saved["evidence"])
        self.assertEqual((evidence[0]["name"], evidence[0]["tier"], evidence[0]["connection"], evidence[0]["finding_id"]),
                         ("FRED, St. Louis Fed", 1, "FRED (St. Louis Fed)", fred))

    def test_a_missing_finding_id_drops_the_recommendation(self):
        kept, removed = self.generate([self.rec([99999]), self.rec([self.ids[("fred", "Employment and demand")], 99999])])
        self.assertEqual((kept, removed), ([], 2))
        self.assertEqual(self.saved(), [])

    def test_no_citation_or_a_simulated_citation_drops_it(self):
        kept, removed = self.generate([self.rec([]), self.rec([self.demo_id], why="Vacancy is 11.1%.")])
        self.assertEqual((kept, removed), ([], 2))

    def test_a_number_that_is_not_in_the_data_drops_it(self):
        fred = self.ids[("fred", "Employment and demand")]
        kept, removed = self.generate([self.rec([fred], why="Unemployment of 4.4% means rents will rise 9%."),
                                       self.rec([fred], step="Offer a 3% concession.")])
        self.assertEqual((kept, removed), ([], 2))

    def test_a_number_from_a_finding_it_did_not_cite_drops_it(self):
        census = self.ids[("census", "Population and income")]
        kept, removed = self.generate([self.rec([census], why="Unemployment was 4.4%.")])
        self.assertEqual(removed, 1)

    def test_deal_numbers_are_allowed(self):
        fred = self.ids[("fred", "Employment and demand")]
        kept, _ = self.generate([self.rec([fred], why="With 4.4% unemployment, the 4 leases ending in 12 months at 154,600 SF total need early renewal talks.")])
        self.assertEqual(len(kept), 1)

    def test_priority_comes_from_the_strongest_source_cited(self):
        tier2 = self.ids[("web_search_tavily", "Vacancy")]
        tier3 = self.ids[("web_search_tavily", "Asking rent trend")]
        kept, _ = self.generate([self.rec([tier2], why="Vacancy was 6.2% and 7.5%."), self.rec([tier3], why="Asking rents rose.")])
        self.assertEqual([k["priority"] for k in kept], ["Medium", "Low"])

    def test_sources_that_disagree_are_kept_in_the_evidence(self):
        from services import research
        tavily = self.ids[("web_search_tavily", "Vacancy")]
        kept, _ = self.generate([self.rec([tavily], why="Vacancy was 6.2% in one report and 7.5% in another.")])
        self.assertEqual(research.disagreements(kept[0]["evidence"]), ["vacancy rate"])

    def test_new_suggestions_replace_unhandled_ones_but_keep_decisions(self):
        fred = self.ids[("fred", "Employment and demand")]
        self.generate([self.rec([fred], title="First"), self.rec([fred], title="Second")])
        first = self.saved()[0]["id"]
        recommendations.set_ai_status(first, "accepted", self.db_path)
        self.generate([self.rec([fred], title="Third")])
        self.assertEqual([(r["title"], r["status"]) for r in self.saved()], [("First", "accepted"), ("Third", "new")])

    def test_no_real_findings_means_no_request(self):
        conn = db.get_connection(self.db_path)
        with conn:
            conn.execute("DELETE FROM research_findings WHERE simulated = 0")
        conn.close()
        with self.assertRaises(ValueError) as caught:
            self.generate([])
        self.assertIn("Run market research first", str(caught.exception))
        self.assertEqual(self.prompts, [])

    def test_quota_and_bad_replies(self):
        with mock.patch.object(gemini.time, "sleep"):
            with self.assertRaises(gemini.GeminiQuotaError):
                self.generate(daily_quota_error())
        with self.assertRaises(gemini.GeminiError):
            self.generate("not json")
        self.assertEqual(self.saved(), [])


class TestDecisions(AiTestCase):
    def test_rule_decisions_stick_by_rule_key(self):
        rec = recommendations.rule_recommendations([unit("A", 1000, end="2027-01-01")], [], [1], DOCS, TODAY)[0]
        recommendations.set_rule_status(self.deal_id, rec, "accepted", self.db_path)
        recommendations.set_rule_status(self.deal_id, rec, "dismissed", self.db_path)
        conn = db.get_connection(self.db_path)
        rows = [dict(r) for r in conn.execute("SELECT rule_key, status FROM recommendations WHERE kind = 'rule'")]
        conn.close()
        self.assertEqual(rows, [{"rule_key": "expiring:0-12", "status": "dismissed"}])

    def test_accepted_recommendations_reach_the_narrative_facts(self):
        rec = recommendations.rule_recommendations([unit("A", 1000, end="2027-01-01")], [], [1], DOCS, TODAY)[0]
        facts = drafting.deal_facts(self.deal_id, self.db_path, TODAY)[0]
        self.assertNotIn(rec["title"], facts)
        recommendations.set_rule_status(self.deal_id, rec, "accepted", self.db_path)
        self.assertIn(rec["title"], drafting.deal_facts(self.deal_id, self.db_path, TODAY)[0])

    def test_note_text(self):
        rec = {"title": "Do a thing", "why": "Because.", "next_step": "Call them."}
        self.assertEqual(recommendations.note_text(rec), "Recommendation: Do a thing\nWhy: Because.\nNext step: Call them.")


if __name__ == "__main__":
    unittest.main()
