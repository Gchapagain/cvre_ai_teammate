"""Tests for the calculated deal figures. Every expected number here is worked out by hand or from the sample file."""

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

import seed
from services import extraction, metrics
from tests.test_extraction import RENT_ROLL, read_source_units

TODAY = date(2026, 10, 13)


def unit(number, sf, rate=10.0, end="2028-10-13", tenant=None, **overrides):
    row = {"unit_number": number, "tenant_name": tenant or f"Tenant {number}", "square_feet": sf,
           "annual_rent": sf * rate if isinstance(sf, (int, float)) else None, "lease_end": end}
    row.update(overrides)
    return row


def values(rows):
    return {label: value for label, value, _ in rows}


class TestSnapshotOnSampleData(unittest.TestCase):
    def setUp(self):
        self.units = read_source_units()
        self.flags = [{"unit_number": "110", "rule": "rent_per_sf_above_2x_average"}]
        self.t12 = [{"line_item": item[1], "period": item[2], "amount": item[3]} for item in seed.read_t12(seed.T12_FILE)]
        self.snapshot = values(metrics.snapshot(self.units, self.flags, self.t12, TODAY))

    def test_totals_match_the_rent_roll_file(self):
        total_sf = sum(u["square_feet"] for u in self.units)
        total_rent = sum(u["annual_rent"] for u in self.units)
        self.assertEqual(total_sf, 154600)
        self.assertEqual(self.snapshot["Total SF"], "154,600")
        self.assertEqual(self.snapshot["Units"], "12")
        self.assertEqual(self.snapshot["Average rent / SF"], f"${total_rent / total_sf:,.2f}")
        self.assertEqual(self.snapshot["Flagged units"], "1")

    def test_weighted_lease_term_is_weighted_by_sf(self):
        total_sf = sum(u["square_feet"] for u in self.units)
        expected = sum(u["square_feet"] * max((date.fromisoformat(u["lease_end"]) - TODAY).days, 0) / 365.25
                       for u in self.units) / total_sf
        self.assertEqual(self.snapshot["Weighted avg lease term left"], f"{expected:.1f} years")

    def test_noi_is_the_t12_figure_or_needs_t12(self):
        self.assertEqual(self.snapshot["Net operating income"], "$1,244,311.44")
        without = values(metrics.snapshot(self.units, self.flags, [], TODAY))
        self.assertEqual(without["Net operating income"], "Needs T-12")

    def test_no_occupancy_cap_rate_or_assumed_time(self):
        labels = " ".join(self.snapshot).lower()
        self.assertNotIn("occupancy", labels)
        self.assertNotIn("cap rate", labels)
        self.assertEqual(self.snapshot["Time in review"], "Not measured yet")


class TestSnapshotWhenDataIsMissing(unittest.TestCase):
    def test_nothing_usable_says_not_available(self):
        units = [unit("1", None, end=None), unit("2", "big", end="soon")]
        snapshot = values(metrics.snapshot(units, [], [], TODAY))
        self.assertEqual(snapshot["Total SF"], "Not available")
        self.assertEqual(snapshot["Average rent / SF"], "Not available")
        self.assertEqual(snapshot["Weighted avg lease term left"], "Not available")
        self.assertEqual(snapshot["Units"], "2")

    def test_partly_usable_data_says_how_much_was_used(self):
        rows = metrics.snapshot([unit("1", 1000), unit("2", None)], [], [], TODAY)
        label, value, note = rows[0]
        self.assertEqual((label, value, note), ("Total SF", "1,000", "1 of 2 units have a usable SF"))

    def test_an_expired_lease_counts_as_zero_years_not_negative(self):
        units = [unit("1", 1000, end="2020-01-01"), unit("2", 1000, end="2028-10-13")]
        self.assertAlmostEqual(metrics.weighted_lease_term_years(units, TODAY), 1.0, places=2)

    def test_bigger_units_weigh_more(self):
        units = [unit("1", 3000, end="2027-10-13"), unit("2", 1000, end="2031-10-13")]
        self.assertAlmostEqual(metrics.weighted_lease_term_years(units, TODAY), (3 * 1 + 1 * 5) / 4, places=2)


class TestTakeaways(unittest.TestCase):
    def test_sample_data_lines(self):
        lines = metrics.takeaways(read_source_units(), [{"unit_number": "110", "rule": "rent_per_sf_above_2x_average"}], TODAY)
        self.assertEqual(lines, [
            "Harbor & Pine Distribution is the largest tenant: 22,000 SF, 14.2% of the 154,600 SF total.",
            "4 leases (44,700 SF, 28.9% of total SF) end in the next 12 months: units 101, 106, 109, 111.",
            "8 leases (94,400 SF, 61.1% of total SF) end in the next 24 months: units 101, 102, 103, 106, 108, 109, 111, 112.",
            "Shortest remaining term: unit 106, ends 2026-12-31 (3 months).",
            "Longest remaining term: unit 107, ends 2032-10-31 (6.1 years).",
            "Unit 110 is flagged: rent/SF is more than 2x the average of the other units. Confirm it before using its figures.",
        ])

    def test_expiry_windows(self):
        units = [unit("A", 1000, end="2027-10-13"), unit("B", 3000, end="2027-10-14"), unit("C", 1000, end="2029-01-01")]
        lines = metrics.takeaways(units, [], TODAY)
        self.assertIn("1 lease (1,000 SF, 20.0% of total SF) ends in the next 12 months: unit A.", lines)
        self.assertIn("2 leases (4,000 SF, 80.0% of total SF) end in the next 24 months: units A, B.", lines)

    def test_no_expiries_is_said_plainly(self):
        lines = metrics.takeaways([unit("A", 1000, end="2031-01-01")], [], TODAY)
        self.assertIn("No leases end in the next 12 months.", lines)
        self.assertIn("No leases end in the next 24 months.", lines)

    def test_leases_that_already_ended_are_called_out(self):
        lines = metrics.takeaways([unit("A", 1000, end="2026-01-31"), unit("B", 1000, end="2030-01-01")], [], TODAY)
        self.assertIn("1 lease already ended before 2026-10-13: unit A.", lines)
        self.assertIn("Shortest remaining term: unit B, ends 2030-01-01 (39 months).", lines)

    def test_one_unit_has_no_longest_line(self):
        lines = metrics.takeaways([unit("A", 1000)], [], TODAY)
        self.assertEqual(len([line for line in lines if "remaining term" in line]), 1)

    def test_anything_that_would_be_a_guess_is_left_out(self):
        self.assertEqual(metrics.takeaways([unit("A", None, end=None), unit("B", "n/a", end="soon")], [], TODAY), [])
        self.assertEqual(metrics.takeaways([], [], TODAY), [])

    def test_every_flag_gets_a_line_with_its_rule(self):
        flags = [{"unit_number": "7", "rule": "duplicate_unit_id"}, {"unit_number": None, "rule": "made_up_rule"}]
        lines = metrics.takeaways([], flags, TODAY)
        self.assertEqual(lines[0], "Unit 7 is flagged: the unit ID appears more than once. Confirm it before using its figures.")
        self.assertIn("Unit (no ID) is flagged: made_up_rule.", lines[1])


class TestSmallHelpers(unittest.TestCase):
    def test_time_ago(self):
        now = datetime(2026, 10, 13, 13, 5, tzinfo=timezone.utc)
        self.assertEqual(metrics.time_ago("2026-10-13 10:00:00", now), "3 hours ago")
        self.assertEqual(metrics.time_ago("2026-10-13 13:04:00", now), "1 minute ago")
        self.assertEqual(metrics.time_ago("2026-10-11 13:04:00", now), "2 days ago")
        self.assertEqual(metrics.time_ago("2026-10-13 13:04:50", now), "just now")
        self.assertEqual(metrics.time_ago(None, now), "")
        self.assertEqual(metrics.time_ago("yesterday", now), "")

    def test_count_unit_rows(self):
        self.assertEqual(extraction.count_unit_rows(RENT_ROLL), 12)
        self.assertIsNone(extraction.count_unit_rows(seed.T12_FILE))
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(extraction.count_unit_rows(Path(folder) / "missing.xlsx"))


if __name__ == "__main__":
    unittest.main()
