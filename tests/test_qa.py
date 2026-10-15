"""Tests for the deal-only Q&A service. Gemini is always simulated here."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import seed
from services import gemini, qa
from tests.test_extraction import daily_quota_error, gemini_error


def fake_gemini(answer, found=True, sources=("rent_roll.xlsx",), prompts=None):
    """A stand-in client that gives one fixed reply and remembers the prompt it was sent."""
    def generate_content(**kwargs):
        if prompts is not None:
            prompts.append(kwargs["contents"])
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, str) and found is None:
            return SimpleNamespace(text=answer)
        return SimpleNamespace(text=json.dumps({"answer": answer, "found_in_deal": found, "sources": list(sources)}))
    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


class QaTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.db_path = Path(cls.tmp.name) / "qa.db"
        cls.deals = seed.seed(cls.db_path)
        cls.deal_id = cls.deals["fallowmere"]

    def ask(self, question, answer, deal_id=None, **options):
        history = options.pop("history", ())
        return qa.ask(deal_id or self.deal_id, question, history,
                      client=fake_gemini(answer, **options), db_path=self.db_path)


class TestLabels(QaTestCase):
    def test_grounded_answer_is_from_this_deal_with_its_source(self):
        answer = self.ask("What does unit 110 pay?", "Unit 110 pays $20.33 per SF, or $65,055.96 a year.")
        self.assertEqual(answer.label, qa.LABEL_FROM_DEAL)
        self.assertEqual(answer.sources, ["rent_roll.xlsx"])
        self.assertEqual(answer.note, "")

    def test_totals_worked_out_in_python_count_as_deal_data(self):
        answer = self.ask("Total SF?", "The building has 12 units and 154,600 square feet in total.")
        self.assertEqual(answer.label, qa.LABEL_FROM_DEAL)

    def test_t12_figures_count_as_deal_data(self):
        answer = self.ask("What is NOI?", "Net Operating Income for the period is $1,244,311.44.", sources=("t12.xlsx",))
        self.assertEqual(answer.label, qa.LABEL_FROM_DEAL)
        self.assertEqual(answer.sources, ["t12.xlsx"])

    def test_flags_can_be_cited(self):
        answer = self.ask("Any anomalies?", "Unit 110 is flagged for rent above 2x the other units.",
                          sources=("Validation flags",))
        self.assertEqual(answer.label, qa.LABEL_FROM_DEAL)

    def test_not_in_the_deal_gives_the_standard_reply(self):
        answer = self.ask("What is the cap rate?", "Cap rates for industrial are around 6%.", found=False, sources=())
        self.assertEqual(answer.label, qa.LABEL_NOT_VERIFIED)
        self.assertEqual(answer.text, "I don't have that in this deal.")
        self.assertEqual(answer.sources, [])

    def test_a_number_that_is_not_in_the_deal_is_downgraded(self):
        answer = self.ask("What is it worth?", "At a 6.5% cap rate the property is worth $19,143,253.")
        self.assertEqual(answer.label, qa.LABEL_NOT_VERIFIED)
        self.assertIn("not verified", answer.note)

    def test_a_slightly_wrong_number_is_downgraded(self):
        answer = self.ask("What does unit 110 pay?", "Unit 110 pays $20.35 per SF.")
        self.assertEqual(answer.label, qa.LABEL_NOT_VERIFIED)

    def test_an_answer_with_no_real_source_is_downgraded(self):
        for sources in ((), ("market_report.pdf",), ("brindlewick_rent_roll.xlsx",)):
            with self.subTest(sources=sources):
                answer = self.ask("Who is in unit 101?", "Northfield Pallet Co. is in unit 101.", sources=sources)
                self.assertEqual(answer.label, qa.LABEL_NOT_VERIFIED)
                self.assertEqual(answer.sources, [])

    def test_made_up_sources_are_dropped_from_a_good_answer(self):
        answer = self.ask("Who is in unit 101?", "Northfield Pallet Co. is in unit 101.",
                          sources=("rent_roll.xlsx", "somewhere_else.pdf"))
        self.assertEqual(answer.label, qa.LABEL_FROM_DEAL)
        self.assertEqual(answer.sources, ["rent_roll.xlsx"])

    def test_every_answer_has_one_of_the_two_labels(self):
        for found in (True, False):
            answer = self.ask("Anything", "Unit 101 is 12,000 SF.", found=found)
            self.assertIn(answer.label, (qa.LABEL_FROM_DEAL, qa.LABEL_NOT_VERIFIED))


class TestWhatGeminiIsSent(QaTestCase):
    def prompt_for(self, deal_id, history=()):
        prompts = []
        qa.ask(deal_id, "How many units are there?", history,
               client=fake_gemini("There are units.", prompts=prompts), db_path=self.db_path)
        return prompts[0]

    def test_prompt_holds_this_deals_data(self):
        prompt = self.prompt_for(self.deal_id)
        for expected in ("Vantor Robotics Lab", "65055.96", "Net Operating Income", "1244311.44",
                         "rent_per_sf_above_2x_average", "rent_roll.xlsx", "t12.xlsx", "Number of units: 12",
                         "How many units are there?"):
            self.assertIn(expected, prompt)

    def test_prompt_holds_no_other_deals_data(self):
        prompt = self.prompt_for(self.deal_id)
        for other in ("Brindlewick", "Pemberly Sock Emporium", "Quillhaven"):
            self.assertNotIn(other, prompt)
        other_prompt = self.prompt_for(self.deals["brindlewick"])
        self.assertIn("Pemberly Sock Emporium", other_prompt)
        self.assertNotIn("Vantor Robotics Lab", other_prompt)

    def test_prompt_tells_gemini_to_use_only_the_deal_data(self):
        prompt = self.prompt_for(self.deal_id)
        self.assertIn("Use ONLY the DEAL DATA", prompt)
        self.assertIn("I don't have that in this deal.", prompt)

    def test_earlier_messages_are_included_but_only_the_last_six(self):
        history = [{"role": "user", "text": f"question {i}"} for i in range(10)]
        prompt = self.prompt_for(self.deal_id, history)
        self.assertIn("question 9", prompt)
        self.assertIn("question 4", prompt)
        self.assertNotIn("question 3", prompt)


class TestWhenGeminiIsNotAvailable(QaTestCase):
    def setUp(self):
        patcher = mock.patch.object(gemini.time, "sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def test_daily_quota_raises_a_quota_error_without_retrying(self):
        prompts = []
        with self.assertRaises(gemini.GeminiQuotaError) as caught:
            self.ask("Total rent?", daily_quota_error(), prompts=prompts)
        self.assertEqual(len(prompts), 1)
        self.sleep.assert_not_called()
        self.assertIn("daily quota is used up", str(caught.exception))

    def test_rate_limit_and_busy_are_tried_three_times(self):
        for error in (gemini_error(429, "RESOURCE_EXHAUSTED"), gemini_error(503, "UNAVAILABLE")):
            with self.subTest(error.code):
                prompts = []
                with self.assertRaises(gemini.GeminiBusyError):
                    self.ask("Total rent?", error, prompts=prompts)
                self.assertEqual(len(prompts), 3)

    def test_reply_that_is_not_the_expected_json_is_an_error_not_an_answer(self):
        for bad in ("Sure! The rent is high.", '{"answer": "x"}', '{"answer": "x", "found_in_deal": "maybe", "sources": []}'):
            with self.subTest(bad):
                with self.assertRaises(gemini.GeminiError):
                    self.ask("Total rent?", bad, found=None)

    def test_deal_with_no_numbers_is_answered_without_gemini(self):
        prompts = []
        answer = self.ask("What is the NOI?", AssertionError("must not be called"),
                          deal_id=self.deals["quillhaven"], prompts=prompts)
        self.assertEqual(prompts, [])
        self.assertEqual(answer.label, qa.LABEL_NOT_VERIFIED)
        self.assertIn("I don't have that in this deal.", answer.text)

    def test_asking_never_changes_the_database(self):
        before = self.db_path.read_bytes()
        self.ask("What does unit 110 pay?", "Unit 110 pays $20.33 per SF.")
        self.assertEqual(self.db_path.read_bytes(), before)


FALLOWMERE = "Fallowmere Industrial Park (SAMPLE - fictional)"
BRINDLEWICK = "Brindlewick Retail Row (SAMPLE - fictional)"


def fake_gemini_all(answer, found=True, deals=(), sources=(), prompts=None):
    def generate_content(**kwargs):
        if prompts is not None:
            prompts.append(kwargs["contents"])
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(text=json.dumps({"answer": answer, "found_in_deals": found,
                                                "deals_used": list(deals), "sources": list(sources)}))
    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


class TestAllDeals(QaTestCase):
    def ask_all(self, answer, **options):
        return qa.ask_all("A question", client=fake_gemini_all(answer, **options), db_path=self.db_path)

    def test_grounded_answer_names_its_deals_and_sources(self):
        answer = self.ask_all("Unit 110 at Fallowmere pays $20.33 per SF and is flagged.",
                              deals=[FALLOWMERE], sources=["rent_roll.xlsx", "Validation flags"])
        self.assertEqual(answer.label, qa.LABEL_FROM_DEALS)
        self.assertEqual(answer.deals, [FALLOWMERE])
        self.assertEqual(answer.sources, ["rent_roll.xlsx", "Validation flags"])

    def test_answer_can_use_more_than_one_deal(self):
        answer = self.ask_all("Fallowmere has 12 units and Brindlewick has 5 units.",
                              deals=[FALLOWMERE, BRINDLEWICK], sources=["rent_roll.xlsx", "brindlewick_rent_roll.xlsx"])
        self.assertEqual(answer.label, qa.LABEL_FROM_DEALS)
        self.assertEqual(answer.deals, [FALLOWMERE, BRINDLEWICK])

    def test_counts_across_deals_are_worked_out_in_python(self):
        answer = self.ask_all("There are 3 deals and 1 validation flag.", deals=[FALLOWMERE], sources=["Validation flags"])
        self.assertEqual(answer.label, qa.LABEL_FROM_DEALS)

    def test_a_number_from_a_deal_it_did_not_cite_is_downgraded(self):
        # 20.33 is Fallowmere's figure, but the reply only cites Brindlewick.
        answer = self.ask_all("The top rent is $20.33 per SF.", deals=[BRINDLEWICK], sources=["brindlewick_rent_roll.xlsx"])
        self.assertEqual(answer.label, qa.LABEL_NOT_VERIFIED)

    def test_no_real_deal_named_is_downgraded(self):
        for deals in ([], ["Some Other Tower"]):
            with self.subTest(deals=deals):
                answer = self.ask_all("Unit 110 is flagged.", deals=deals, sources=["Validation flags"])
                self.assertEqual(answer.label, qa.LABEL_NOT_VERIFIED)
                self.assertEqual(answer.deals, [])

    def test_source_from_a_deal_it_did_not_cite_is_dropped(self):
        answer = self.ask_all("Brindlewick has 5 units.", deals=[BRINDLEWICK], sources=["rent_roll.xlsx"])
        self.assertEqual(answer.label, qa.LABEL_NOT_VERIFIED)
        self.assertEqual(answer.sources, [])

    def test_not_in_any_deal_gives_the_standard_reply(self):
        answer = self.ask_all("Cap rates are about 6%.", found=False)
        self.assertEqual(answer.label, qa.LABEL_NOT_VERIFIED)
        self.assertEqual(answer.text, "I don't have that in any of the deals.")

    def test_prompt_holds_every_deal_and_only_database_data(self):
        prompts = []
        self.ask_all("x", deals=[FALLOWMERE], sources=["rent_roll.xlsx"], prompts=prompts)
        for expected in (FALLOWMERE, BRINDLEWICK, "Quillhaven Flex Center", "Vantor Robotics Lab",
                         "Pemberly Sock Emporium", "Number of deals: 3", "Use ONLY the DEAL DATA"):
            self.assertIn(expected, prompts[0])

    def test_quota_and_bad_replies_raise_errors(self):
        with mock.patch.object(gemini.time, "sleep"):
            with self.assertRaises(gemini.GeminiQuotaError):
                self.ask_all(daily_quota_error())
        with self.assertRaises(gemini.GeminiError):
            qa.ask_all("x", client=fake_gemini("not json", found=None), db_path=self.db_path)


class TestNumberMatching(unittest.TestCase):
    def test_commas_currency_and_trailing_zeros_do_not_matter(self):
        self.assertEqual(qa.unmatched_numbers("$1,244,311.44 and 12,000 and 8.50", "1244311.44 | 12000 | 8.5"), [])

    def test_missing_numbers_are_reported(self):
        self.assertEqual(qa.unmatched_numbers("Rent is 20.35 for 3,200 SF", "20.33 | 3200"), [20.35])

    def test_a_percentage_must_match_a_percentage_not_a_date(self):
        context = "Unit 109 | lease start 2022-09-01 | vacancy 6.2%"
        self.assertEqual(qa.unmatched_numbers("Rents will rise 9%.", context), [9.0])
        self.assertEqual(qa.unmatched_numbers("Vacancy is 6.2%.", context), [])
        self.assertEqual(qa.unmatched_numbers("Unit 109 started in 2022.", context), [])

    def test_text_without_numbers_always_matches(self):
        self.assertEqual(qa.unmatched_numbers("Northfield Pallet Co. is the tenant.", "anything"), [])


if __name__ == "__main__":
    unittest.main()
