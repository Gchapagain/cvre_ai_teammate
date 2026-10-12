"""Tests for process_deal: extraction then validation, with a short summary. No Gemini calls."""

import db
from services import extraction, pipeline, validation
from tests.test_extraction import RENT_ROLL, ExtractionTestCase, fake_client


class TestProcessDeal(ExtractionTestCase):
    def flag_count(self):
        conn = db.get_connection(self.db_path)
        count = conn.execute("SELECT COUNT(*) FROM flags WHERE deal_id = ?", (self.deal_id,)).fetchone()[0]
        conn.close()
        return count

    def test_sample_data_summary(self):
        summary = pipeline.process_deal(
            RENT_ROLL, self.deal_id, client=fake_client(self.source), db_path=self.db_path
        )
        self.assertEqual(summary, {
            "units_saved": 12,
            "flags_raised": 1,
            "rules": {validation.RULE_RENT_OUTLIER: 1},
        })
        self.assertEqual(len(self.saved_units()), 12)
        self.assertEqual(self.flag_count(), 1)

    def test_summary_counts_each_rule(self):
        units = [dict(u) for u in self.source]
        units[0]["square_feet"] = 0
        units[1]["monthly_rent"] = -1
        units[2]["annual_rent"] = "TBD"
        summary = pipeline.process_deal(RENT_ROLL, self.deal_id, client=fake_client(units), db_path=self.db_path)
        self.assertEqual(summary["units_saved"], 12)
        self.assertEqual(summary["rules"], {
            validation.RULE_ZERO_OR_NEGATIVE: 2,
            validation.RULE_NON_NUMERIC: 1,
            validation.RULE_RENT_OUTLIER: 1,
        })
        self.assertEqual(summary["flags_raised"], 4)
        self.assertEqual(self.flag_count(), 4)

    def test_clean_rent_roll_has_no_flags(self):
        units = [u for u in self.source if u["unit_number"] != "110"]
        summary = pipeline.process_deal(RENT_ROLL, self.deal_id, client=fake_client(units), db_path=self.db_path)
        self.assertEqual(summary, {"units_saved": 11, "flags_raised": 0, "rules": {}})

    def test_rejected_file_saves_nothing_and_skips_validation(self):
        with self.assertRaises(extraction.ExtractionError):
            pipeline.process_deal(RENT_ROLL, self.deal_id, client=fake_client([]), db_path=self.db_path)
        self.assertEqual(self.saved_units(), {})
        self.assertEqual(self.flag_count(), 0)
