"""Tests for the drafting service. Gemini is always simulated."""

import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import db
import seed
from services import drafting, gemini
from tests.test_extraction import daily_quota_error, forbidden_client

TODAY = date(2026, 10, 13)
GOOD = ("Fallowmere Industrial Park has 12 units totalling 154,600 SF, with average rent of $8.84 per SF. "
        "Net operating income is $1,244,311.44 as stated in the T-12.")


def fake_gemini(reply, prompts=None):
    def generate_content(**kwargs):
        if prompts is not None:
            prompts.append(kwargs["contents"])
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(text=reply)
    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


class DraftingTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "drafts.db"
        self.deals = seed.seed(self.db_path)
        self.deal_id = self.deals["fallowmere"]

    def generate(self, reply, deal_id=None, **options):
        prompts = options.pop("prompts", None)
        draft_id = drafting.generate_draft(deal_id or self.deal_id, client=fake_gemini(reply, prompts),
                                           db_path=self.db_path, today=TODAY, **options)
        return drafting.get_draft(draft_id, self.db_path)

    def rows(self, sql):
        conn = db.get_connection(self.db_path)
        result = [dict(row) for row in conn.execute(sql)]
        conn.close()
        return result


class TestGenerate(DraftingTestCase):
    def test_draft_is_saved_as_generated_not_sent_and_unedited(self):
        draft = self.generate(GOOD + " Flagged units need confirmation before use.")
        self.assertEqual((draft["deal_id"], draft["status"], draft["edited"]), (self.deal_id, "Generated, not sent", 0))
        self.assertTrue(draft["text"].startswith("Fallowmere Industrial Park has 12 units"))
        self.assertTrue(draft["created_at"])

    def test_one_request_with_only_this_deals_facts_and_the_rules(self):
        prompts = []
        self.generate(GOOD, prompts=prompts)
        self.assertEqual(len(prompts), 1)
        prompt = prompts[0]
        for expected in ("Vantor Robotics Lab", "Net Operating Income", "Total SF: 154,600", "Average rent / SF: $8.84",
                         "Harbor & Pine Distribution is the largest tenant", "rent_per_sf_above_2x_average",
                         "Never state a figure that is not written there", "need confirmation"):
            self.assertIn(expected, prompt)
        for other in ("Brindlewick", "Pemberly Sock Emporium", "Quillhaven"):
            self.assertNotIn(other, prompt)

    def test_the_flag_sentence_is_added_if_the_ai_leaves_it_out(self):
        draft = self.generate(GOOD)
        self.assertTrue(draft["text"].endswith("Flagged units (110) need confirmation before these figures are used."))

    def test_the_flag_sentence_is_not_added_twice_or_to_a_clean_deal(self):
        said = GOOD + " The flagged unit must be confirmed first."
        self.assertEqual(self.generate(said)["text"], said)
        clean = self.generate("Brindlewick Retail Row has 5 units.", deal_id=self.deals["brindlewick"])
        self.assertEqual(clean["text"], "Brindlewick Retail Row has 5 units.")

    def test_a_deal_with_no_numbers_is_refused_without_calling_gemini(self):
        with self.assertRaises(ValueError):
            drafting.generate_draft(self.deals["quillhaven"], client=forbidden_client(), db_path=self.db_path)
        self.assertEqual(self.rows("SELECT id FROM drafts"), [])

    def test_quota_error_saves_nothing(self):
        with mock.patch.object(gemini.time, "sleep"):
            with self.assertRaises(gemini.GeminiQuotaError):
                self.generate(daily_quota_error())
        self.assertEqual(self.rows("SELECT id FROM drafts"), [])

    def test_the_rent_roll_is_never_changed_by_drafting(self):
        before = self.rows("SELECT * FROM rent_roll_units")
        self.generate(GOOD)
        self.assertEqual(self.rows("SELECT * FROM rent_roll_units"), before)


class TestNumberCheck(DraftingTestCase):
    def check(self, text):
        return drafting.unmatched_numbers(text, self.deal_id, self.db_path, TODAY)

    def test_figures_from_the_data_and_the_calculations_all_match(self):
        text = (GOOD + " Harbor & Pine Distribution is the largest tenant at 22,000 SF, 14.2% of the total. "
                "Weighted lease term is 2.3 years. Unit 110 is at $20.33 per SF against a limit of $17.19.")
        self.assertEqual(self.check(text), [])

    def test_an_invented_or_altered_figure_is_caught(self):
        self.assertEqual(self.check("The property should trade at a 6.5% cap rate, or about $19,143,253."), [6.5, 19143253.0])
        self.assertEqual(self.check("Average rent is $8.85 per SF."), [8.85])
        self.assertEqual(self.check("Occupancy is 95%."), [95.0])

    def test_text_without_numbers_matches(self):
        self.assertEqual(self.check("The rent roll is stable and the flagged unit needs confirmation."), [])

    def test_only_accepted_research_figures_are_allowed(self):
        sources = json.dumps([{"name": "bls.gov", "tier": 1, "date": "2026-08-01", "figure": "4.1% unemployment"}])
        conn = db.get_connection(self.db_path)
        with conn:
            conn.execute("INSERT INTO research_findings (deal_id, topic, summary, sources, status) VALUES (?, ?, ?, ?, 'new')",
                         (self.deal_id, "Employment", "Unemployment was 4.1%.", sources))
        conn.close()
        self.assertEqual(self.check("Local unemployment is 4.1%."), [4.1])
        conn = db.get_connection(self.db_path)
        with conn:
            conn.execute("UPDATE research_findings SET status = 'accepted'")
        conn.close()
        self.assertEqual(self.check("Local unemployment is 4.1%."), [])
        facts, _ = drafting.deal_facts(self.deal_id, self.db_path, TODAY)
        self.assertIn("bls.gov (Tier 1, 2026-08-01): 4.1% unemployment", facts)


class TestHumanActions(DraftingTestCase):
    def test_approve_is_refused_while_a_figure_does_not_match(self):
        draft = self.generate("Value is about $19,000,000. Flagged units need confirmation.")
        with self.assertRaises(drafting.DraftNotVerified) as caught:
            drafting.approve(draft["id"], self.db_path, TODAY)
        self.assertIn("19,000,000", str(caught.exception))
        self.assertEqual(drafting.get_draft(draft["id"], self.db_path)["status"], "Generated, not sent")

    def test_editing_out_the_figure_allows_approval(self):
        draft = self.generate("Value is about $19,000,000. Flagged units need confirmation.")
        drafting.save_edit(draft["id"], "The 12 units total 154,600 SF. Unit 110 needs confirmation.", self.db_path)
        edited = drafting.get_draft(draft["id"], self.db_path)
        self.assertEqual((edited["edited"], edited["status"]), (1, "Generated, not sent"))
        drafting.approve(draft["id"], self.db_path, TODAY)
        self.assertEqual(drafting.get_draft(draft["id"], self.db_path)["status"], "Approved")

    def test_editing_an_approved_draft_takes_the_approval_away(self):
        draft = self.generate(GOOD + " Flagged units need confirmation.")
        drafting.approve(draft["id"], self.db_path, TODAY)
        drafting.save_edit(draft["id"], "Changed after approval. Unit 110 needs confirmation.", self.db_path)
        self.assertEqual(drafting.get_draft(draft["id"], self.db_path)["status"], "Generated, not sent")

    def test_flag_for_producer_and_empty_edits(self):
        draft = self.generate(GOOD)
        drafting.flag_for_producer(draft["id"], self.db_path)
        self.assertEqual(drafting.get_draft(draft["id"], self.db_path)["status"], "Flagged for producer")
        with self.assertRaises(ValueError):
            drafting.save_edit(draft["id"], "   ", self.db_path)

    def test_generating_never_approves(self):
        self.generate(GOOD)
        self.assertEqual(self.rows("SELECT DISTINCT status FROM drafts"), [{"status": "Generated, not sent"}])

    def test_status_must_be_one_of_the_three(self):
        conn = db.get_connection(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO drafts (deal_id, text, status) VALUES (?, 'x', 'Sent to client')", (self.deal_id,))
        conn.close()


class TestRecordAndReplay(DraftingTestCase):
    def setUp(self):
        super().setUp()
        self.recording = Path(self.tmp.name) / "recordings" / "draft.json"

    def test_replay_gives_the_recorded_draft_without_calling_gemini(self):
        self.generate(GOOD, record_to=self.recording)
        replayed_id = drafting.generate_draft(self.deal_id, client=forbidden_client(), db_path=self.db_path,
                                              today=TODAY, replay_from=self.recording)
        self.assertTrue(drafting.get_draft(replayed_id, self.db_path)["text"].startswith(GOOD))
        self.assertEqual(set(json.loads(self.recording.read_text())), {"recorded_at", "model", "prompt_sha256", "response_text"})

    def test_out_of_date_recording_is_refused(self):
        self.generate(GOOD, record_to=self.recording)
        conn = db.get_connection(self.db_path)
        with conn:
            conn.execute("UPDATE rent_roll_units SET monthly_rent = monthly_rent + 1 WHERE unit_number = '101'")
        conn.close()
        with self.assertRaises(gemini.GeminiError) as caught:
            drafting.generate_draft(self.deal_id, client=forbidden_client(), db_path=self.db_path,
                                    today=TODAY, replay_from=self.recording)
        self.assertIn("out of date", str(caught.exception))

    def test_nothing_is_recorded_when_gemini_fails(self):
        with mock.patch.object(gemini.time, "sleep"):
            with self.assertRaises(gemini.GeminiError):
                self.generate(daily_quota_error(), record_to=self.recording)
        self.assertFalse(self.recording.exists())


class TestOldDraftsTable(unittest.TestCase):
    OLD = "CREATE TABLE drafts (id INTEGER PRIMARY KEY, deal_id INTEGER, draft_type TEXT, title TEXT, body TEXT, status TEXT)"

    def columns(self, conn, table):
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}

    def make_old(self, folder, with_row):
        path = Path(folder) / "old.db"
        conn = db.get_connection(path)
        conn.execute(self.OLD)
        if with_row:
            conn.execute("INSERT INTO drafts (deal_id, body) VALUES (1, 'An old draft worth keeping')")
        conn.commit()
        conn.close()
        db.init_db(path)
        return db.get_connection(path)

    def test_an_empty_old_table_is_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = self.make_old(folder, with_row=False)
            self.assertIn("text", self.columns(conn, "drafts"))
            self.assertEqual(self.columns(conn, "drafts_before_review_tab"), set())
            conn.close()

    def test_an_old_table_with_rows_is_kept_under_another_name(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = self.make_old(folder, with_row=True)
            self.assertIn("text", self.columns(conn, "drafts"))
            kept = conn.execute("SELECT body FROM drafts_before_review_tab").fetchall()
            self.assertEqual([row["body"] for row in kept], ["An old draft worth keeping"])
            conn.close()

    def test_running_it_again_changes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = self.make_old(folder, with_row=False)
            conn.execute("INSERT INTO deals (name) VALUES ('Made-up')")
            conn.execute("INSERT INTO drafts (deal_id, text) VALUES (1, 'Keep me')")
            conn.commit()
            conn.close()
            db.init_db(Path(folder) / "old.db")
            conn = db.get_connection(Path(folder) / "old.db")
            self.assertEqual(conn.execute("SELECT text FROM drafts").fetchone()["text"], "Keep me")
            conn.close()


if __name__ == "__main__":
    unittest.main()
