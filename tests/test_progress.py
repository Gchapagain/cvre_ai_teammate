"""Tests for deal progress on Home: each step, the next-step wording, and the colour at every threshold."""

import json
import unittest

from services import progress
from services.progress import Facts

LIMITS = (25, 70)
EXTRACTED = dict(documents=1, units=12)


class TestSteps(unittest.TestCase):
    def test_nothing_saved_is_zero_and_red(self):
        result = progress.calculate(Facts(), LIMITS)
        self.assertEqual((result.count, result.total, result.percent, result.colour), (0, 7, 0, "red"))
        self.assertEqual(result.next_step, "Next: add a rent roll")

    def test_a_received_document_is_one_step(self):
        result = progress.calculate(Facts(documents=1), LIMITS)
        self.assertEqual((result.count, result.colour, result.next_step), (1, "red", "Next: read the rent roll"))

    def test_extracted_units_complete_extraction_validation_and_flags(self):
        result = progress.calculate(Facts(**EXTRACTED), LIMITS)
        self.assertEqual(result.done, (True, True, True, True, False, False, False))
        self.assertEqual(result.next_step, "Next: generate a draft narrative")

    def test_an_open_flag_is_the_next_step_with_its_count(self):
        self.assertEqual(progress.calculate(Facts(**EXTRACTED, open_flags=1), LIMITS).next_step, "Next: resolve 1 flag")
        self.assertEqual(progress.calculate(Facts(**EXTRACTED, open_flags=3), LIMITS).next_step, "Next: resolve 3 flags")

    def test_no_flags_before_extraction_does_not_count_as_resolved(self):
        self.assertFalse(progress.calculate(Facts(documents=1), LIMITS).done[3])

    def test_research_counts_only_when_reviewed_and_nothing_is_left_waiting(self):
        base = dict(**EXTRACTED, drafts=1)
        self.assertEqual(progress.calculate(Facts(**base), LIMITS).next_step, "Next: run market research")
        waiting = progress.calculate(Facts(**base, findings_new=2, findings_reviewed=1), LIMITS)
        self.assertFalse(waiting.done[5])
        self.assertEqual(waiting.next_step, "Next: review 2 research findings")
        self.assertTrue(progress.calculate(Facts(**base, findings_reviewed=1), LIMITS).done[5])

    def test_every_step_done_is_100_and_green(self):
        result = progress.calculate(Facts(**EXTRACTED, drafts=1, findings_reviewed=1, approved=True), LIMITS)
        self.assertEqual((result.count, result.percent, result.colour, result.next_step), (7, 100, "green", "All steps done"))

    def test_approved_without_the_other_steps_is_not_green(self):
        result = progress.calculate(Facts(**EXTRACTED, approved=True), LIMITS)
        self.assertEqual((result.count, result.colour), (5, "yellow"))
        self.assertEqual(result.next_step, "Next: generate a draft narrative")

    def test_the_sample_deals_get_three_different_colours(self):
        self.assertEqual(progress.calculate(Facts(documents=1), LIMITS).colour, "red")                       # Quillhaven
        self.assertEqual(progress.calculate(Facts(documents=2, units=12, open_flags=1), LIMITS).colour, "orange")  # Fallowmere
        self.assertEqual(progress.calculate(Facts(documents=1, units=6, drafts=1, findings_reviewed=1,
                                                  approved=True), LIMITS).colour, "green")             # Brindlewick


class TestColours(unittest.TestCase):
    def test_every_threshold(self):
        cases = {0: "red", 24: "red", 25: "orange", 69: "orange", 70: "yellow", 99: "yellow", 100: "green"}
        for percent, colour in cases.items():
            with self.subTest(percent):
                self.assertEqual(progress.colour_for(percent, LIMITS), colour)

    def test_each_number_of_steps_out_of_seven(self):
        expected = ["red", "red", "orange", "orange", "orange", "yellow", "yellow", "green"]  # 0..7 steps
        for steps, colour in enumerate(expected):
            with self.subTest(steps):
                self.assertEqual(progress.colour_for(round(100 * steps / 7), LIMITS), colour)

    def test_only_100_is_green(self):
        self.assertNotIn("green", {progress.colour_for(p, LIMITS) for p in range(100)})

    def test_thresholds_come_from_the_config_file(self):
        settings = json.loads(progress.CONFIG.read_text())
        self.assertEqual(progress.thresholds(), (settings["red_below"], settings["orange_below"]))
        self.assertEqual(progress.colour_for(settings["red_below"] - 1), "red")
        self.assertEqual(progress.colour_for(settings["orange_below"]), "yellow")


if __name__ == "__main__":
    unittest.main()
