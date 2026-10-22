"""Tests for understanding a correction in plain words. Gemini is always simulated."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import db
import seed
from services import correction_ai, corrections, gemini
from tests.test_extraction import daily_quota_error, forbidden_client

TEXT = "Unit 110's monthly rent should be $2,400. The $5,421.33 included a one-off fit-out charge."


def reply(changes=(), questions=(), interpretation="Unit 110's monthly rent should be 2,400."):
    return {"interpretation": interpretation, "questions": list(questions),
            "changes": [{"unit": u, "field": f, "new_value": v} for u, f, v in changes]}


def client(answer, prompts=None):
    def generate_content(**kwargs):
        if prompts is not None:
            prompts.append(kwargs["contents"])
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(text=answer if isinstance(answer, str) else json.dumps(answer))
    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


class CorrectionAiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "corr.db"
        self.deals = seed.seed(self.db_path)
        self.deal_id = self.deals["fallowmere"]
        self.prompts = []

    def understand(self, answer, text=TEXT, **options):
        return correction_ai.understand(self.deal_id, text, client=client(answer, self.prompts), db_path=self.db_path, **options)

    def rows(self, sql):
        conn = db.get_connection(self.db_path)
        result = [dict(r) for r in conn.execute(sql)]
        conn.close()
        return result


class TestUnderstand(CorrectionAiTestCase):
    def test_a_clear_correction_becomes_one_checked_proposal_with_recomputed_fields(self):
        result = self.understand(reply([("110", "monthly_rent", "2400")]))
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(result["interpretation"], "Unit 110's monthly rent should be 2,400.")
        self.assertEqual((result["dropped"], result["questions"]), ([], []))
        proposal = result["proposals"][0]
        self.assertEqual(proposal["unit_number"], "110")
        self.assertEqual([(c["field"], c["new"], c["derived"]) for c in proposal["changes"]],
                         [("monthly_rent", 2400.0, False), ("annual_rent", 28800.0, True), ("rent_per_sf", 9.0, True)])

    def test_the_prompt_holds_the_persons_words_and_only_this_deals_units(self):
        self.understand(reply())
        prompt = self.prompts[0]
        self.assertIn(TEXT, prompt)
        self.assertIn("110 | Vantor Robotics Lab | 3200", prompt)
        self.assertNotIn("Pemberly Sock Emporium", prompt)
        self.assertIn("Never guess a value", prompt)

    def test_an_ambiguous_correction_asks_a_question_instead_of_changing_anything(self):
        result = self.understand(reply(questions=["Which unit's rent is wrong?"], interpretation="Some rent is wrong."),
                                 text="The rent looks wrong.")
        self.assertEqual(result["proposals"], [])
        self.assertEqual(result["questions"], ["Which unit's rent is wrong?"])

    def test_a_unit_that_is_not_in_this_deal_is_dropped_and_explained(self):
        result = self.understand(reply([("999", "monthly_rent", "2400"), ("A", "tenant_name", "Someone")]))
        self.assertEqual(result["proposals"], [])
        self.assertEqual(result["dropped"], ["unit 999 is not in this deal", "unit A is not in this deal"])

    def test_invalid_values_and_fields_are_dropped(self):
        result = self.understand(reply([("110", "monthly_rent", "a lot"), ("110", "lease_end", "next spring"),
                                        ("110", "rent_per_sf", "9"), ("110", "unit_number", "111")]),
                                 text="Unit 110 rent is a lot, lease ends next spring, rent/SF 9, unit 111.")
        self.assertEqual(result["proposals"], [])
        self.assertEqual(len(result["dropped"]), 4)
        self.assertIn("must be a number", result["dropped"][0])
        self.assertIn("cannot be edited", result["dropped"][2])

    def test_a_value_the_person_did_not_give_is_dropped(self):
        result = self.understand(reply([("110", "monthly_rent", "2500")]))
        self.assertEqual(result["proposals"], [])
        self.assertIn("the value 2500 is not in what you wrote", result["dropped"][0])

    def test_a_change_to_the_current_value_is_dropped(self):
        result = self.understand(reply([("110", "square_feet", "3200")]), text="Unit 110 is 3200 SF.")
        self.assertEqual(result["proposals"], [])
        self.assertIn("is already 3200", result["dropped"][0])

    def test_two_fields_on_one_unit_become_one_proposal(self):
        result = self.understand(reply([("110", "monthly_rent", "2400"), ("110", "lease_type", "Gross")]),
                                 text="Unit 110 pays 2400 a month on a Gross lease.")
        self.assertEqual(len(result["proposals"]), 1)
        self.assertEqual(result["proposals"][0]["values"], {"monthly_rent": "2400", "lease_type": "Gross"})

    def test_understanding_saves_nothing(self):
        before = self.db_path.read_bytes()
        self.understand(reply([("110", "monthly_rent", "2400")]))
        self.assertEqual(self.db_path.read_bytes(), before)

    def test_quota_bad_reply_and_empty_text(self):
        with mock.patch.object(gemini.time, "sleep"), self.assertRaises(gemini.GeminiQuotaError):
            self.understand(daily_quota_error())
        with self.assertRaises(gemini.GeminiError):
            self.understand("not json")
        with self.assertRaises(ValueError):
            correction_ai.understand(self.deal_id, "  ", client=forbidden_client(), db_path=self.db_path)

    def test_applying_a_proposal_uses_the_audited_path_marked_ai_assisted(self):
        proposal = self.understand(reply([("110", "monthly_rent", "2400")]))["proposals"][0]
        corrections.apply(self.deal_id, proposal["unit_id"], proposal["changes"], TEXT, "Avery Sample",
                          corrections.AI_ASSISTED, self.db_path)
        edits = self.rows("SELECT source, reason, derived FROM edits ORDER BY id")
        self.assertEqual({e["source"] for e in edits}, {"AI-assisted"})
        self.assertEqual(edits[0]["reason"], TEXT)
        self.assertEqual(self.rows("SELECT source FROM deal_events"), [{"source": "AI-assisted"}])


class TestRecordAndReplay(CorrectionAiTestCase):
    def test_replay_without_calling_gemini_and_refuse_a_stale_recording(self):
        recording = Path(self.tmp.name) / "recordings" / "correction.json"
        self.understand(reply([("110", "monthly_rent", "2400")]), record_to=recording)
        again = correction_ai.understand(self.deal_id, TEXT, client=forbidden_client(), db_path=self.db_path, replay_from=recording)
        self.assertEqual(again["proposals"][0]["unit_number"], "110")
        with self.assertRaises(gemini.GeminiError):
            correction_ai.understand(self.deal_id, TEXT + " Also check the SF.", client=forbidden_client(),
                                     db_path=self.db_path, replay_from=recording)


if __name__ == "__main__":
    unittest.main()
