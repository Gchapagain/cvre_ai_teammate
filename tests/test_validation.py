"""Tests for the validation rules. No Gemini calls anywhere in this file."""

import copy
import tempfile
import unittest
from datetime import date
from pathlib import Path

import db
from services import extraction, validation
from tests.test_extraction import RENT_ROLL, fake_client, read_source_units


def make_unit(unit_number="101", sf=1000, rate=10.0, **overrides):
    """A small made-up unit whose numbers agree with each other.

    sf and rate build a consistent unit. Overrides then replace single fields
    (for example square_feet=0) without touching the rest.
    """
    annual = sf * rate
    unit = {
        "unit_number": unit_number,
        "tenant_name": f"Tenant {unit_number}",
        "square_feet": sf,
        "lease_start": "2024-01-01",
        "lease_end": "2029-12-31",
        "monthly_rent": annual / 12,
        "annual_rent": annual,
        "rent_per_sf": rate,
        "lease_type": "NNN",
    }
    unit.update(overrides)
    return unit


def building(*rates):
    """Same-size units numbered 101, 102, ... with the given rent/SF."""
    return [make_unit(str(101 + i), rate=rate) for i, rate in enumerate(rates)]


def summary(flags):
    """Flags as (unit, rule, field) so tests can compare them easily."""
    return sorted((f.unit_number or "", f.rule, f.field) for f in flags)


class TestSampleData(unittest.TestCase):
    def setUp(self):
        self.source = read_source_units()
        self.flags = validation.validate_units(self.source)

    def test_flags_exactly_unit_110_and_nothing_else(self):
        self.assertEqual(summary(self.flags), [("110", validation.RULE_RENT_OUTLIER, "rent_per_sf")])

    def test_unit_110_flag_has_the_right_numbers(self):
        flag = self.flags[0]
        others = [u for u in self.source if u["unit_number"] != "110"]
        average = sum(u["annual_rent"] for u in others) / sum(u["square_feet"] for u in others)
        unit_110 = next(u for u in self.source if u["unit_number"] == "110")
        self.assertEqual(flag.actual_value, str(unit_110["rent_per_sf"]))
        self.assertEqual(flag.threshold, f"{2 * average:.2f}")
        self.assertIn("Unit 110", flag.message)
        self.assertIn("other 11 unit(s)", flag.message)
        self.assertIn(f"${average:,.2f}", flag.message)


class TestRentOutlierRule(unittest.TestCase):
    def outliers(self, units):
        return [f for f in validation.validate_units(units) if f.rule == validation.RULE_RENT_OUTLIER]

    def test_unit_above_2x_is_flagged(self):
        flags = self.outliers(building(10, 10, 10, 20.01))
        self.assertEqual([f.unit_number for f in flags], ["104"])
        self.assertEqual(flags[0].actual_value, "20.01")
        self.assertEqual(flags[0].threshold, "20.00")

    def test_unit_exactly_at_2x_is_not_flagged(self):
        self.assertEqual(self.outliers(building(10, 10, 10, 20.0)), [])

    def test_unit_just_below_2x_is_not_flagged(self):
        self.assertEqual(self.outliers(building(10, 10, 10, 19.99)), [])

    def test_deal_with_one_unit_is_never_flagged(self):
        self.assertEqual(validation.validate_units(building(500)), [])

    def test_average_leaves_out_the_unit_being_tested(self):
        # With the unit included, the average would be 17.5 and 25 would pass (limit 35).
        flags = self.outliers(building(10, 25))
        self.assertEqual([f.unit_number for f in flags], ["102"])
        self.assertEqual(flags[0].threshold, "20.00")

    def test_average_is_weighted_by_square_feet(self):
        units = [
            make_unit("A", sf=9000, rate=10),
            make_unit("B", sf=1000, rate=30),
            make_unit("C", sf=1000, rate=25),
        ]
        # Others for C: (90,000 + 30,000) / 10,000 SF = 12.00, so the limit is 24.00.
        # A simple mean of 10 and 30 would give a limit of 40 and miss it.
        flag_c = next(f for f in self.outliers(units) if f.unit_number == "C")
        self.assertEqual(flag_c.threshold, "24.00")

    def test_low_rent_units_are_not_flagged(self):
        self.assertEqual(self.outliers(building(10, 10, 10, 1)), [])

    def test_units_with_bad_numbers_are_left_out_of_the_average(self):
        units = building(10, 10, 25) + [
            make_unit("201", square_feet=0),
            make_unit("202", annual_rent=None),
            make_unit("203", square_feet="big"),
        ]
        flags = self.outliers(units)
        self.assertEqual([f.unit_number for f in flags], ["103"])
        self.assertEqual(flags[0].threshold, "20.00")

    def test_nothing_to_compare_against_means_no_outlier_flag(self):
        units = [make_unit("101", rate=500), make_unit("102", square_feet=0)]
        self.assertEqual(self.outliers(units), [])

    def test_two_outliers_are_both_flagged(self):
        flags = self.outliers(building(10, 10, 10, 10, 10, 10, 10, 10, 40, 40))
        self.assertEqual([f.unit_number for f in flags], ["109", "110"])


class TestValueRules(unittest.TestCase):
    def flags_for(self, **overrides):
        """Flags for one changed unit sitting in an otherwise clean building."""
        units = building(10, 10) + [make_unit("999", **overrides)]
        return [f for f in validation.validate_units(units) if f.unit_number == "999"]

    def test_clean_unit_has_no_flags(self):
        self.assertEqual(self.flags_for(), [])

    def test_missing_numbers_are_flagged(self):
        for field in validation.NUMERIC_FIELDS:
            for empty in (None, "", "   "):
                with self.subTest(field=field, value=empty):
                    flags = self.flags_for(**{field: empty})
                    self.assertEqual(summary(flags), [("999", validation.RULE_MISSING, field)])
                    self.assertEqual(flags[0].threshold, "required")

    def test_non_numeric_values_are_flagged_and_kept_as_found(self):
        for field in validation.NUMERIC_FIELDS:
            for bad in ("twelve thousand", "$1,200", True, float("nan"), float("inf")):
                with self.subTest(field=field, value=bad):
                    flags = self.flags_for(**{field: bad})
                    self.assertEqual(summary(flags), [("999", validation.RULE_NON_NUMERIC, field)])
                    self.assertEqual(flags[0].actual_value, str(bad))

    def test_zero_or_negative_numbers_are_flagged(self):
        for field in validation.NUMERIC_FIELDS:
            for bad in (0, 0.0, -1, -2500.5):
                with self.subTest(field=field, value=bad):
                    flags = self.flags_for(**{field: bad})
                    self.assertEqual(summary(flags), [("999", validation.RULE_ZERO_OR_NEGATIVE, field)])
                    self.assertEqual(flags[0].actual_value, str(bad))
                    self.assertEqual(flags[0].threshold, "greater than 0")

    def test_tiny_positive_number_is_not_flagged_as_zero(self):
        self.assertEqual(self.flags_for(monthly_rent=0.01), [])

    def test_missing_unit_id_is_flagged(self):
        for empty in (None, "", "  "):
            with self.subTest(value=empty):
                flags = validation.validate_units(building(10, 10) + [make_unit(empty)])
                self.assertEqual(summary(flags), [("", validation.RULE_MISSING, "unit_number")])
                self.assertIsNone(flags[0].unit_number)

    def test_several_problems_on_one_unit_are_all_flagged(self):
        flags = self.flags_for(square_feet=-5, monthly_rent=None, annual_rent="n/a")
        self.assertEqual(summary(flags), [
            ("999", validation.RULE_MISSING, "monthly_rent"),
            ("999", validation.RULE_NON_NUMERIC, "annual_rent"),
            ("999", validation.RULE_ZERO_OR_NEGATIVE, "square_feet"),
        ])


class TestDateRules(unittest.TestCase):
    def flags_for(self, **overrides):
        return validation.validate_units(building(10, 10) + [make_unit("999", **overrides)])

    def test_lease_end_before_start_is_flagged(self):
        flags = self.flags_for(lease_start="2026-06-01", lease_end="2026-05-31")
        self.assertEqual(summary(flags), [("999", validation.RULE_LEASE_DATES, "lease_end")])
        self.assertEqual(flags[0].actual_value, "2026-05-31")
        self.assertEqual(flags[0].threshold, "on or after 2026-06-01")

    def test_lease_ending_on_its_start_date_is_not_flagged(self):
        self.assertEqual(self.flags_for(lease_start="2026-06-01", lease_end="2026-06-01"), [])

    def test_date_objects_work_as_well_as_text(self):
        flags = self.flags_for(lease_start=date(2026, 6, 1), lease_end=date(2025, 6, 1))
        self.assertEqual(summary(flags), [("999", validation.RULE_LEASE_DATES, "lease_end")])

    def test_missing_dates_are_flagged(self):
        for field in validation.DATE_FIELDS:
            with self.subTest(field=field):
                flags = self.flags_for(**{field: None})
                self.assertEqual(summary(flags), [("999", validation.RULE_MISSING, field)])

    def test_unreadable_dates_are_flagged(self):
        for bad in ("next year", "31/12/2029", 20291231):
            with self.subTest(value=bad):
                flags = self.flags_for(lease_end=bad)
                self.assertEqual(summary(flags), [("999", validation.RULE_INVALID_DATE, "lease_end")])
                self.assertEqual(flags[0].actual_value, str(bad))


class TestDuplicateRule(unittest.TestCase):
    def test_every_row_with_a_repeated_id_is_flagged(self):
        units = building(10, 10, 10) + [make_unit("102"), make_unit(" 102 ")]
        flags = validation.validate_units(units)
        self.assertEqual(summary(flags), [("102", validation.RULE_DUPLICATE, "unit_number")] * 3)
        self.assertIn("appears 3 times", flags[0].message)

    def test_different_ids_are_not_flagged(self):
        self.assertEqual(validation.validate_units(building(10, 10, 10)), [])

    def test_units_with_no_id_are_not_called_duplicates(self):
        flags = validation.validate_units([make_unit(None), make_unit(None), make_unit("101")])
        self.assertNotIn(validation.RULE_DUPLICATE, [f.rule for f in flags])


class TestFlagsNeverChangeData(unittest.TestCase):
    MESSY = [
        make_unit("101"),
        make_unit("101", square_feet=0),
        make_unit("103", rent_per_sf=99, lease_end="2020-01-01"),
        make_unit(None, monthly_rent="lots", annual_rent=None),
    ]

    def test_input_is_untouched(self):
        units = copy.deepcopy(self.MESSY)
        validation.validate_units(units)
        self.assertEqual(units, self.MESSY)

    def test_every_flag_is_complete(self):
        flags = validation.validate_units(copy.deepcopy(self.MESSY))
        self.assertGreater(len(flags), 5)
        for flag in flags:
            with self.subTest(flag=flag):
                self.assertIn(flag.rule, validation.RENT_ROLL_RULES)
                self.assertTrue(flag.field)
                self.assertTrue(flag.threshold)
                self.assertTrue(flag.message)

    def test_empty_rent_roll_gives_no_flags(self):
        self.assertEqual(validation.validate_units([]), [])


class TestValidateDeal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "test.db"
        db.init_db(self.db_path)
        self.deal_id = self.add_deal("Sample Deal")

    def add_deal(self, name):
        conn = db.get_connection(self.db_path)
        with conn:
            deal_id = conn.execute("INSERT INTO deals (name) VALUES (?)", (name,)).lastrowid
        conn.close()
        return deal_id

    def add_units(self, deal_id, units):
        conn = db.get_connection(self.db_path)
        with conn:
            extraction_fields = [k for k in units[0] if k != "id"]
            conn.executemany(
                f"INSERT INTO rent_roll_units (deal_id, {', '.join(extraction_fields)}) "
                f"VALUES (?, {', '.join('?' for _ in extraction_fields)})",
                [(deal_id, *(u[k] for k in extraction_fields)) for u in units],
            )
        conn.close()

    def rows(self, table, deal_id=None):
        conn = db.get_connection(self.db_path)
        rows = conn.execute(f"SELECT * FROM {table} WHERE deal_id = ? ORDER BY id", (deal_id or self.deal_id,))
        result = [dict(row) for row in rows]
        conn.close()
        return result

    def test_extracted_sample_data_saves_exactly_one_flag_for_unit_110(self):
        extraction.extract_rent_roll(
            RENT_ROLL, self.deal_id, client=fake_client(read_source_units()), db_path=self.db_path
        )
        validation.validate_deal(self.deal_id, self.db_path)
        saved = self.rows("flags")
        self.assertEqual(len(saved), 1)
        unit_110 = next(u for u in self.rows("rent_roll_units") if u["unit_number"] == "110")
        self.assertEqual(saved[0]["unit_number"], "110")
        self.assertEqual(saved[0]["rule"], validation.RULE_RENT_OUTLIER)
        self.assertEqual(saved[0]["field"], "rent_per_sf")
        self.assertEqual(saved[0]["rent_roll_unit_id"], unit_110["id"])
        self.assertEqual(saved[0]["actual_value"], str(unit_110["rent_per_sf"]))
        self.assertTrue(saved[0]["threshold"])
        self.assertIn("Unit 110", saved[0]["message"])

    def test_rent_roll_rows_are_not_changed_or_deleted(self):
        self.add_units(self.deal_id, building(10, 10, 99) + [make_unit("104", square_feet=-1)])
        before = self.rows("rent_roll_units")
        flags = validation.validate_deal(self.deal_id, self.db_path)
        self.assertGreaterEqual(len(flags), 2)
        self.assertEqual(self.rows("rent_roll_units"), before)

    def test_bad_values_stored_in_the_database_are_flagged_without_an_error(self):
        self.add_units(self.deal_id, building(10, 10) + [
            make_unit("103", square_feet="twelve thousand", monthly_rent=None, lease_end="soon"),
        ])
        validation.validate_deal(self.deal_id, self.db_path)
        saved = {(f["rule"], f["field"]): f for f in self.rows("flags")}
        self.assertEqual(set(saved), {
            (validation.RULE_NON_NUMERIC, "square_feet"),
            (validation.RULE_MISSING, "monthly_rent"),
            (validation.RULE_INVALID_DATE, "lease_end"),
        })
        self.assertEqual(saved[(validation.RULE_NON_NUMERIC, "square_feet")]["actual_value"], "twelve thousand")
        self.assertIsNone(saved[(validation.RULE_MISSING, "monthly_rent")]["actual_value"])

    def test_running_twice_replaces_flags_instead_of_duplicating(self):
        self.add_units(self.deal_id, building(10, 10, 99))
        validation.validate_deal(self.deal_id, self.db_path)
        validation.validate_deal(self.deal_id, self.db_path)
        self.assertEqual(len(self.rows("flags")), 1)

    def test_other_deals_flags_are_left_alone(self):
        other = self.add_deal("Other Deal")
        self.add_units(other, building(10, 10, 99))
        self.add_units(self.deal_id, building(10, 10, 10))
        validation.validate_deal(other, self.db_path)
        self.assertEqual(validation.validate_deal(self.deal_id, self.db_path), [])
        self.assertEqual(len(self.rows("flags", other)), 1)
        self.assertEqual(self.rows("flags"), [])

    def test_deal_with_no_rent_roll_gives_no_flags(self):
        self.assertEqual(validation.validate_deal(self.deal_id, self.db_path), [])
        self.assertEqual(self.rows("flags"), [])

    def test_re_extracting_clears_old_flags_with_the_old_rows(self):
        self.add_units(self.deal_id, building(10, 10, 99))
        validation.validate_deal(self.deal_id, self.db_path)
        extraction.extract_rent_roll(
            RENT_ROLL, self.deal_id, client=fake_client(read_source_units()), db_path=self.db_path
        )
        self.assertEqual(self.rows("flags"), [])


if __name__ == "__main__":
    unittest.main()
