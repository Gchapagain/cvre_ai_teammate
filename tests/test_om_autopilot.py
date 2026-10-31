"""Tests for the AI Teammate's OM autopilot. Gemini is simulated (FakeGemini counts requests); web research
is replaced, never called. Fictional data only.
"""

import json
import os
from unittest import mock

import db
from services import ai_limits, gemini, om_autopilot, om_slots
from tests.test_om_builder import DRAFT, DbCase, FakeGemini

NO_RESEARCH = {"OM_AUTOPILOT_STEPS": "record,emails,text,assumptions,photos,approve"}
QUILLHAVEN_FACTS = {"facts": [
    {"slot_id": "property.address", "value": "220 Fictional Commerce Drive", "quote": "220 Fictional Commerce Drive", "email_id": 0},
    {"slot_id": "property.city_state", "value": "Eastwick Bend, OH", "quote": "Eastwick Bend, OH", "email_id": 0},
    {"slot_id": "property.buildings", "value": "2", "quote": "2 buildings", "email_id": 0},
    {"slot_id": "property.land_size", "value": "3.4 acres", "quote": "3.4 acres", "email_id": 0},
    {"slot_id": "property.year_built", "value": "2001 / 2018", "quote": "built in 2001 and the roofs were replaced in 2018",
     "email_id": 0},
    {"slot_id": "property.clear_height", "value": "32'", "quote": "32 foot clear height", "email_id": 0}]}
ASSUMPTIONS = {"assumptions": [{"key": "market_rent_psf", "value": 9.25, "why": "Near the in-place average."}]}


class AutopilotCase(DbCase):
    def run_autopilot(self, deal, fake, steps=NO_RESEARCH):
        with mock.patch.dict(os.environ, steps):
            return om_autopilot.run(self.deals[deal], client=fake, db_path=self.db_path)

    def email_id(self, subject):
        conn = db.get_connection(self.db_path)
        try:
            return conn.execute("SELECT id FROM emails WHERE subject = ?", (subject,)).fetchone()["id"]
        finally:
            conn.close()


class TestFromTheDealAndEmails(AutopilotCase):
    def test_city_and_state_come_from_the_deal_location(self):
        self.assertEqual(om_autopilot.city_state_from("Alliance, Fort Worth, TX"), "Fort Worth, TX")
        self.assertIsNone(om_autopilot.city_state_from("Eastwick Bend (fictional)"))

    def test_facts_in_an_email_are_filled_approved_and_cite_the_email_with_one_request(self):
        email = self.email_id("Quillhaven property details")
        reply = json.loads(json.dumps(QUILLHAVEN_FACTS).replace('"email_id": 0', f'"email_id": {email}'))
        fake = FakeGemini(reply)
        before = self.state("quillhaven").percent
        record = self.run_autopilot("quillhaven", fake)
        self.assertEqual(fake.calls, 1)
        state = self.state("quillhaven")
        for slot_id, value in (("property.address", "220 Fictional Commerce Drive"), ("property.city_state", "Eastwick Bend, OH"),
                               ("property.buildings", 2), ("property.land_size", "3.4 acres"),
                               ("property.year_built", "2001 / 2018")):
            slot = state.slots[slot_id]
            self.assertEqual((slot.status, slot.value), ("approved", value), slot_id)
            self.assertIn('From the email "Quillhaven property details"', slot.source["detail"])
            self.assertIn("approved automatically", slot.source["approved_by"])
        self.assertEqual(state.slots["property.clear_height"].status, "empty")  # its words are not in the email
        self.assertTrue(any("Not used (Clear height)" in line for line in record["lines"]))
        self.assertGreater(state.percent, before)

    def test_nothing_new_means_no_request_the_second_time(self):
        email = self.email_id("Quillhaven property details")
        self.run_autopilot("quillhaven", FakeGemini(json.loads(
            json.dumps(QUILLHAVEN_FACTS).replace('"email_id": 0', f'"email_id": {email}'))))
        fake = FakeGemini()
        self.run_autopilot("quillhaven", fake)
        self.assertEqual(fake.calls, 0)


class TestTextAssumptionsAndApprovals(AutopilotCase):
    def test_fallowmere_gets_drafts_and_proposals_but_nothing_the_broker_decides(self):
        fake = FakeGemini({"facts": []}, DRAFT, ASSUMPTIONS)
        record = self.run_autopilot("fallowmere", fake)
        self.assertEqual(fake.calls, 3)
        state = self.state()
        self.assertEqual(state.slots["offering.narrative"].status, "ai-draft")  # prose waits for a person
        self.assertEqual(self.facts()["assumptions"]["market_rent_psf"]["status"], "proposed")
        self.assertEqual(state.slots["financial.sale_price"].status, "empty")  # never set by the AI
        self.assertTrue(any(line.startswith("Drafted:") for line in record["lines"]))
        again = FakeGemini()
        self.run_autopilot("fallowmere", again)
        self.assertEqual(again.calls, 0)

    def test_price_based_numbers_wait_until_the_broker_approves_the_price(self):
        deal = self.deals["fallowmere"]
        om_slots.set_value(deal, "financial.sale_price", "15,460,000", "Avery Sample", db_path=self.db_path)
        self.run_autopilot("fallowmere", FakeGemini({"facts": []}, DRAFT, ASSUMPTIONS))
        self.assertEqual(self.state().slots["financial.price_per_sf"].status, "auto-filled")
        om_slots.approve(deal, [self.state().slots["financial.sale_price"]], "Avery Sample", self.db_path)
        self.run_autopilot("fallowmere", FakeGemini())
        self.assertEqual(self.state().slots["financial.price_per_sf"].status, "approved")

    def test_an_approval_a_person_took_back_is_not_given_again(self):
        deal = self.deals["fallowmere"]
        om_slots.unapprove(deal, "property.total_sf", "Avery Sample", self.db_path)
        self.run_autopilot("fallowmere", FakeGemini({"facts": []}, DRAFT, ASSUMPTIONS))
        self.assertEqual(self.state().slots["property.total_sf"].status, "auto-filled")

    def test_the_ai_limit_pauses_the_ai_steps_and_the_rest_still_runs(self):
        deal = self.deals["fallowmere"]
        om_slots.unapprove(deal, "property.leased_pct", "Someone else", self.db_path)
        conn = db.get_connection(self.db_path)
        with conn:  # make the take-back look like the AI Teammate's own, so the approve step may redo it
            conn.execute("UPDATE om_events SET user = ? WHERE action = 'unapprove'", (om_autopilot.ACTOR,))
        conn.close()
        fake = FakeGemini(gemini.RateLimited("The app's AI limit of 15 requests a day has been reached."))
        record = self.run_autopilot("fallowmere", fake)
        self.assertEqual(fake.calls, 1)
        self.assertTrue(any(line.startswith("Paused:") for line in record["lines"]))
        self.assertEqual(self.state().slots["property.leased_pct"].status, "approved")


class TestResearch(AutopilotCase):
    def add_finding(self, sources, simulated=0):
        conn = db.get_connection(self.db_path)
        with conn:
            finding = conn.execute("INSERT INTO research_findings (deal_id, topic, summary, sources, status, simulated) "
                                   "VALUES (?, 'Vacancy', 'Made up for the test.', ?, 'new', ?)",
                                   (self.deals["fallowmere"], json.dumps(sources), simulated)).lastrowid
        conn.close()
        return finding

    def statuses(self):
        conn = db.get_connection(self.db_path)
        try:
            return {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM research_findings")}
        finally:
            conn.close()

    def test_only_checked_real_tiered_findings_are_accepted(self):
        good = self.add_finding([{"name": "Official stats (test)", "tier": 1, "checked": True}])
        unchecked = self.add_finding([{"name": "Search answer (test)", "tier": 2, "checked": False}])
        untiered = self.add_finding([{"name": "A blog (test)", "tier": None, "checked": True}])
        fake = self.add_finding([{"name": "Demo source", "tier": 2, "checked": True}], simulated=1)
        self.assertEqual(om_autopilot.auto_accept(self.deals["fallowmere"], self.db_path), 1)
        statuses = self.statuses()
        self.assertEqual(statuses[good], "accepted")
        self.assertEqual([statuses[i] for i in (unchecked, untiered, fake)], ["new", "new", "new"])

    def test_research_runs_through_connections_with_generic_terms_only(self):
        with mock.patch("services.connections.run_research", return_value=[]) as research:
            self.run_autopilot("fallowmere", FakeGemini(), steps={"OM_AUTOPILOT_STEPS": "research"})
        deal = research.call_args.args[0]
        self.assertEqual((deal["property_type"], deal["submarket"]), ("Industrial", "Alliance, Fort Worth, TX"))


class TestRunningOnItsOwn(AutopilotCase):
    def test_background_ai_counts_as_its_own_session(self):
        self.assertIsNone(ai_limits.current_session())
        with ai_limits.as_session(om_autopilot.SESSION):
            self.assertEqual(ai_limits.current_session(), "ai-teammate")
        self.assertIsNone(ai_limits.current_session())

    def test_it_is_off_in_tests_and_can_be_switched_off(self):
        self.assertFalse(om_autopilot.enabled())
        self.assertFalse(om_autopilot.start(self.deals["fallowmere"]))
        with mock.patch.dict(os.environ, {"OM_AUTOPILOT": "on"}):
            self.assertTrue(om_autopilot.enabled())

    def test_every_run_is_logged_as_the_ai_teammate(self):
        self.run_autopilot("fallowmere", FakeGemini({"facts": []}, DRAFT, ASSUMPTIONS))
        conn = db.get_connection(self.db_path)
        row = conn.execute("SELECT user, detail FROM om_events WHERE action = 'autopilot'").fetchone()
        conn.close()
        self.assertEqual(row["user"], "AI Teammate")
        self.assertIn("lines", json.loads(row["detail"]))
