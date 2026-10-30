"""Tests for the OM Builder's template, calculations, completion engine and writes. No Gemini calls.

All deals here are fictional.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import db
import seed
from services import om_calc, om_engine, om_slots, om_template, validation

USER = "Avery Sample"

# A made-up four-unit flex building with one vacant unit and one rent that does not add up:
# unit 3 is 5,600 SF x $14.25 = $79,800, but the row says $79,600.
TEST_UNITS = [
    {"unit_number": "1", "tenant_name": "Pinwheel Print Shop (test)", "square_feet": 4000, "rent_per_sf": 15.00,
     "annual_rent": 60000.00, "monthly_rent": 5000.00, "lease_start": "2024-01-01", "lease_end": "2029-12-31"},
    {"unit_number": "2", "tenant_name": "Copperkettle Cafe Supply (test)", "square_feet": 2400, "rent_per_sf": 16.50,
     "annual_rent": 39600.00, "monthly_rent": 3300.00, "lease_start": "2023-06-01", "lease_end": "2028-05-31"},
    {"unit_number": "3", "tenant_name": "Bramblewood Joinery (test)", "square_feet": 5600, "rent_per_sf": 14.25,
     "annual_rent": 79600.00, "monthly_rent": 6633.33, "lease_start": "2022-03-01", "lease_end": "2027-02-28"},
    {"unit_number": "4", "tenant_name": "Vacant", "square_feet": 2000, "rent_per_sf": None,
     "annual_rent": None, "monthly_rent": None, "lease_start": None, "lease_end": None},
]
APPROVED_ASSUMPTIONS = {
    "market_rent_psf": {"value": 15.0, "status": "approved"},
    "escalation_pct": {"value": 3.0, "status": "approved"},
    "occupancy_by_year": {"value": [100, 100, 100, 100, 100], "status": "approved"},
    "expense_growth_pct": {"value": 3.0, "status": "approved"},
    "vacancy_pct": {"value": 5.0, "status": "approved"},
    "management_fee_pct": {"value": 3.0, "status": "approved"},
}
T12 = [
    {"category": "Income", "line_item": "Base Rental Income", "period": "Total", "amount": 179200.0},
    {"category": "Income", "line_item": "CAM Reimbursements", "period": "Total", "amount": 24000.0},
    {"category": "Expense", "line_item": "Property Taxes", "period": "Total", "amount": 18000.0},
    {"category": "Expense", "line_item": "Insurance", "period": "Total", "amount": 6000.0},
    {"category": "Expense", "line_item": "Management Fee", "period": "Total", "amount": 6096.0},
    {"category": "Total", "line_item": "Net Operating Income", "period": "Total", "amount": 173104.0},
]


def facts(**changes):
    base = {"deal": {"name": "Larkmoor Flex Court (test - fictional)", "property_type": "Flex"}, "units": TEST_UNITS,
            "t12": T12, "documents": [], "rows": {}, "assets": [], "assumptions": {}, "price": None,
            "profile": {"full_name": "Avery Sample", "title": "SVP (sample)", "phone": "(555) 010-0142",
                        "email": "demo.broker@example.com"}}
    base.update(changes)
    return base


class TestTemplate(unittest.TestCase):
    def test_the_template_loads_with_five_sections_and_19_baseline_slides(self):
        template = om_template.load()
        self.assertEqual([s["number"] for s in template.sections], ["01", "02", "03", "04", "05"])
        self.assertEqual(len(template.slides), 19)
        self.assertEqual(template.slide_limits, (18, 25))

    def test_every_required_slot_explains_itself_and_who_can_answer(self):
        for slot in om_template.load().slots.values():
            with self.subTest(slot.id):
                self.assertTrue(slot.why)
                if slot.required and not slot.fixed and slot.source in ("broker_input", "broker_photo", "ai_text", "research"):
                    self.assertTrue(slot.broker_question, "a broker question")
                    self.assertTrue(slot.answer_by)

    def test_boilerplate_is_fixed_and_comes_from_the_config_file(self):
        template, text = om_template.load(), om_template.boilerplate()
        fixed = [s for s in template.slots.values() if s.type == "boilerplate"]
        self.assertTrue(fixed and all(s.fixed and not s.required and s.boilerplate in text for s in fixed))

    def test_no_logo_or_company_name_is_in_the_template(self):
        raw = (om_template.TEMPLATES / "om_v1.json").read_text() + om_template.BOILERPLATE.read_text()
        self.assertNotIn("CBRE", raw)
        self.assertNotIn(".png", raw)


class TestCalculations(unittest.TestCase):
    def test_golden_leased_percent(self):
        calc = om_calc.leased_pct(facts())
        # 4,000 + 2,400 + 5,600 leased of 14,000 SF = 85.714...%
        self.assertAlmostEqual(calc.value, 12000 / 14000 * 100)
        self.assertEqual(calc.display, "85.7%")
        self.assertIn("Vacant units: 4", calc.steps)

    def test_golden_price_per_sf(self):
        calc = om_calc.price_per_sf(facts(price=2_450_000))
        self.assertEqual(calc.value, 175.0)  # 2,450,000 / 14,000 SF
        self.assertEqual(calc.display, "$175.00")
        self.assertEqual(calc.steps, ["$2,450,000 / 14,000 SF = $175.00 per SF"])

    def test_totals_average_and_in_place_rent(self):
        self.assertEqual(om_calc.total_sf(facts()).value, 14000)
        self.assertEqual(om_calc.avg_unit_size(facts()).value, 3500)
        self.assertEqual(om_calc.in_place_rent(facts()).value, 179200.0)
        self.assertEqual(om_calc.in_place_noi(facts()).value, 173104.0)

    def test_nothing_is_calculated_without_its_inputs(self):
        self.assertEqual(om_calc.price_per_sf(facts()).needs, ["the sale price (broker)"])
        self.assertIn("a rent roll with unit sizes", om_calc.total_sf(facts(units=[])).needs)
        flow = om_calc.cash_flow(facts())
        self.assertIsNone(flow.value)
        self.assertIn("6 approved assumptions (market rent per sf (annual), annual rent escalation, lease-up: occupancy in years 1 to 5, expense growth per year, vacancy allowance, management fee)", flow.needs)

    def test_only_approved_assumptions_feed_the_cash_flow(self):
        proposed = {k: dict(v, status="proposed") for k, v in APPROVED_ASSUMPTIONS.items()}
        self.assertFalse(om_calc.cash_flow(facts(assumptions=proposed)).ready)
        self.assertTrue(om_calc.cash_flow(facts(assumptions=APPROVED_ASSUMPTIONS)).ready)

    def test_cash_flow_year_1_by_hand(self):
        flow = dict(om_calc.cash_flow(facts(assumptions=APPROVED_ASSUMPTIONS)).value)
        # Rental income: 179,200 x 1.03 + (1.00 x 14,000 - 12,000) x 15.00 x 1.03^0 = 184,576 + 30,000 = 214,576
        self.assertAlmostEqual(flow["Rental income"][1], 214576.0)
        # Reimbursements: 24,000 x 1.03 x (1.00 / 0.857142...) = 28,840
        self.assertAlmostEqual(flow["Reimbursements"][1], 28840.0)
        egi = (214576.0 + 28840.0) * 0.95
        self.assertAlmostEqual(flow["Effective gross income"][1], egi)
        expenses = 18000 * 1.03 + 6000 * 1.03 + 0.03 * egi
        self.assertAlmostEqual(flow["Net operating income"][1], egi - expenses)
        self.assertEqual(flow["Net operating income"][0], flow["Effective gross income"][0] - flow["Total expenses"][0])

    def test_year_4_cap_rate(self):
        f = facts(assumptions=APPROVED_ASSUMPTIONS, price=2_450_000)
        noi_4 = dict(om_calc.cash_flow(f).value)["Net operating income"][4]
        self.assertAlmostEqual(om_calc.cap_rate(f, 4).value, noi_4 / 2_450_000 * 100)

    def test_every_calculation_explains_itself(self):
        f = facts(assumptions=APPROVED_ASSUMPTIONS, price=2_450_000)
        for name, calc in om_calc.CALCS.items():
            with self.subTest(name):
                result = calc(f)
                self.assertTrue(result.ready, result.needs)
                self.assertTrue(result.formula)
                self.assertTrue(result.steps)


class TestRentRule(unittest.TestCase):
    def test_the_mismatch_is_flagged_with_the_exact_numbers(self):
        flags = [f for f in validation.validate_units(TEST_UNITS) if f.rule == validation.RULE_RENT_MATH]
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].unit_number, "3")
        self.assertEqual(flags[0].message, "Unit 3 annual rent is $79,600.00, but 5,600 SF x $14.25/SF = $79,800.00 "
                                           "(a $200.00 difference).")
        self.assertEqual((flags[0].actual_value, flags[0].threshold), ("79600.0", "79800.00"))

    def test_rounding_of_a_stated_rate_is_not_a_mismatch(self):
        unit = {"unit_number": "110", "square_feet": 3200, "rent_per_sf": 20.33, "annual_rent": 65055.96}
        self.assertEqual(validation.check_rent_math(unit), [])
        big = {"unit_number": "9", "square_feet": 50000, "rent_per_sf": 8.33, "annual_rent": 416666.67}  # 8.3333.../SF
        self.assertEqual(validation.check_rent_math(big), [])

    def test_a_one_dollar_gap_is_allowed_and_more_is_not(self):
        unit = {"unit_number": "5", "square_feet": 100, "rent_per_sf": 10.0}
        self.assertEqual(validation.check_rent_math(dict(unit, annual_rent=1001.0)), [])
        self.assertEqual(len(validation.check_rent_math(dict(unit, annual_rent=1001.5))), 1)

    def test_units_must_add_up_to_the_stated_total(self):
        leased = TEST_UNITS[:3]  # 60,000 + 39,600 + 79,600 = 179,200
        self.assertEqual(validation.check_stated_total(leased, {"total_annual_rent": 179200.0}), [])
        [flag] = validation.check_stated_total(leased, {"total_annual_rent": 179400.0})
        self.assertEqual(flag.message, "The unit annual rents add up to $179,200.00, but the rent roll's total row says "
                                       "$179,400.00 (a $200.00 difference).")
        self.assertEqual(validation.check_stated_total(leased, None), [])

    def test_the_sample_deals_pass_the_rent_rule(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "s.db"
        seed.seed(path)
        conn = db.get_connection(path)
        rules = [r[0] for r in conn.execute("SELECT rule FROM flags")]
        conn.close()
        self.assertNotIn(validation.RULE_RENT_MATH, rules)
        self.assertNotIn(validation.RULE_RENT_TOTAL, rules)


class TestCompletion(unittest.TestCase):
    def state(self, **changes):
        return om_engine.build(facts(**changes))

    def test_a_brand_new_deal_is_zero_with_a_long_missing_list(self):
        state = om_engine.build({"deal": {"name": "Empty Deal (test)"}, "units": [], "t12": [], "documents": [],
                                 "rows": {}, "assets": [], "assumptions": {}, "price": None, "profile": {}})
        approved, waiting, done, filled, total = state.completion()
        self.assertEqual((approved, done), (0, 0))
        self.assertGreater(total, 20)
        self.assertGreater(len(state.required_missing()), 20)
        self.assertEqual(state.colour, "red")
        first = state.missing()[0]
        self.assertTrue(first.slot.required)
        self.assertTrue(first.slot.why and first.slides)

    def test_partial_counts_approved_and_waiting_separately(self):
        state = self.state()
        approved, waiting, done, filled, total = state.completion()
        self.assertEqual(done, 0)
        self.assertGreater(filled, 0)  # name, type, total SF, ... are filled and wait for approval
        rows = {s.slot.id: {"value": s.value, "status": "approved", "source": s.source}
                for s in state.waiting()[:3]}
        partial = self.state(rows=rows)
        self.assertEqual(partial.completion()[2], 3)
        self.assertEqual(partial.percent, round(100 * 3 / total))

    def test_one_hundred_percent_when_every_required_slot_is_approved(self):
        template = om_template.load()
        rows, assets = {}, []
        for slot in template.slots.values():
            if slot.type == "photo" and slot.required:
                for n in range(slot.count):
                    assets.append({"id": len(assets) + 1, "slot_id": slot.id, "kind": slot.photo_kinds[0]})
        f = facts(assumptions=APPROVED_ASSUMPTIONS, price=2_450_000, assets=assets,
                  deal={"name": "Larkmoor Flex Court (test - fictional)", "property_type": "Flex", "address": "1 Test Way"})
        draft = om_engine.build(f)
        for s in draft.slots.values():
            if s.counts:
                value = s.value if s.status != "empty" else "Filled in for the test with enough words to pass the length check of eighty characters."
                kind = s.source.get("kind") or "broker_input"
                rows[s.slot.id] = {"value": value, "status": "approved", "source": {"kind": kind}}
        rows["property.city_state"]["value"] = "Testville, TX"
        state = om_engine.build(dict(f, rows=rows))
        self.assertEqual(state.percent, 100)
        self.assertEqual(state.colour, "green")
        self.assertEqual(state.required_missing(), [])
        self.assertTrue(all(state.slide_status(slide) == "green" for _, slide in state.slides))

    def test_a_changed_number_loses_its_approval(self):
        state = self.state()
        total = state.slots["property.total_sf"]
        rows = {"property.total_sf": {"value": total.value, "status": "approved", "source": total.source}}
        self.assertEqual(self.state(rows=rows).slots["property.total_sf"].status, "approved")
        changed = self.state(rows=rows, units=TEST_UNITS[:3]).slots["property.total_sf"]
        self.assertEqual((changed.status, changed.note), ("auto-filled", "Changed since it was approved"))

    def test_photo_slots_say_how_many_more_are_needed(self):
        grid = self.state(assets=[{"id": 1, "slot_id": "photo.grid", "kind": "exterior"}]).slots["photo.grid"]
        self.assertEqual(grid.status, "empty")
        self.assertEqual(grid.needs, ["3 more exterior or interior photos"])

    def test_per_section_completion_and_slide_colours(self):
        state = self.state()
        self.assertEqual(len([s for s in state.template.sections]), 5)
        for section in state.template.sections:
            self.assertEqual(len(state.completion(section["id"])), 5)
        colours = {state.slide_status(slide) for _, slide in state.slides}
        self.assertLessEqual(colours, {"red", "amber", "green"})
        self.assertIn("red", colours)

    def test_optional_regional_slide_only_when_it_has_a_photo(self):
        self.assertEqual(len(self.state().slides), 18)
        with_photo = self.state(assets=[{"id": 9, "slot_id": "photo.regional_aerial", "kind": "aerial"}])
        self.assertEqual(len(with_photo.slides), 19)

    def test_summary_line(self):
        line = om_engine.summary_line(self.state(), "Larkmoor Flex Court")
        self.assertRegex(line, r"^OM for Larkmoor Flex Court is 0% complete - \d+ items missing$")


class DbTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / "om.db"
        self.deals = seed.seed(self.db_path)
        patcher = mock.patch.object(db, "DB_PATH", self.db_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def state(self, deal="fallowmere"):
        from app import queries
        return om_engine.build(queries.om_facts(self.deals[deal]))


class TestSlotWrites(DbTestCase):
    def test_typed_value_is_broker_provided_then_approved(self):
        deal = self.deals["fallowmere"]
        om_slots.set_value(deal, "property.city_state", "fort worth, tx", USER, db_path=self.db_path)
        slot = self.state().slots["property.city_state"]
        self.assertEqual((slot.status, slot.value, slot.source["kind"]), ("broker-provided", "fort worth, TX", "broker_input"))
        om_slots.approve(deal, [slot], USER, self.db_path)
        approved = self.state().slots["property.city_state"]
        self.assertEqual((approved.status, approved.source["approved_by"]), ("approved", USER))
        om_slots.unapprove(deal, "property.city_state", USER, self.db_path)
        self.assertEqual(self.state().slots["property.city_state"].status, "broker-provided")

    def test_approving_a_calculated_value_then_unapproving_it(self):
        deal = self.deals["fallowmere"]
        total = self.state().slots["property.total_sf"]
        self.assertEqual((total.status, total.value), ("auto-filled", 154600.0))
        om_slots.approve(deal, [total], USER, self.db_path)
        self.assertEqual(self.state().slots["property.total_sf"].status, "approved")
        om_slots.unapprove(deal, "property.total_sf", USER, self.db_path)
        self.assertEqual(self.state().slots["property.total_sf"].status, "auto-filled")

    def test_empty_and_fixed_slots_are_never_approved(self):
        state = self.state()
        skipped = om_slots.approve(self.deals["fallowmere"], [state.slots["photo.hero"], state.slots["disclosures.text"]],
                                   USER, self.db_path)
        self.assertEqual(skipped, ["photo.hero", "disclosures.text"])

    def test_invalid_values_are_refused_with_a_reason(self):
        cases = {"property.city_state": "Fort Worth Texas", "financial.sale_price": "about twelve million",
                 "property.year_built": "old", "property.buildings": "2.5", "property.land_size": "big"}
        for slot_id, raw in cases.items():
            with self.subTest(slot_id):
                with self.assertRaises(om_slots.InvalidValue):
                    om_slots.set_value(self.deals["fallowmere"], slot_id, raw, USER, db_path=self.db_path)

    def test_values_are_normalised(self):
        slots = om_template.load().slots
        self.assertEqual(om_slots.validate(slots["financial.sale_price"], "$12.5M"), 12_500_000)
        self.assertEqual(om_slots.validate(slots["property.year_built"], "built 1998, renovated 2019"), "1998 / 2019")
        self.assertEqual(om_slots.validate(slots["property.land_size"], "9.4 acres"), "9.4 acres")
        self.assertEqual(om_slots.validate(slots["highlights.rare"], "- One\n- Two"), ["One", "Two"])

    def test_fixed_boilerplate_cannot_be_written(self):
        with self.assertRaises(ValueError):
            om_slots.set_value(self.deals["fallowmere"], "disclosures.text", "Anything", USER, db_path=self.db_path)

    def test_a_price_makes_price_per_sf_calculable(self):
        deal = self.deals["fallowmere"]
        self.assertEqual(self.state().slots["financial.price_per_sf"].status, "empty")
        om_slots.set_value(deal, "financial.sale_price", "15,460,000", USER, db_path=self.db_path)
        per_sf = self.state().slots["financial.price_per_sf"]
        self.assertEqual((per_sf.status, per_sf.display), ("auto-filled", "$100.00"))  # 15,460,000 / 154,600 SF

    def test_assumptions_proposed_then_approved(self):
        deal = self.deals["fallowmere"]
        om_slots.set_assumption(deal, "escalation_pct", "3%", "AI", status="proposed", db_path=self.db_path)
        from app import queries
        self.assertEqual(queries.om_facts(deal)["assumptions"]["escalation_pct"]["status"], "proposed")
        om_slots.approve_assumption(deal, "escalation_pct", USER, self.db_path)
        self.assertEqual(queries.om_facts(deal)["assumptions"]["escalation_pct"]["status"], "approved")
        with self.assertRaises(om_slots.InvalidValue):
            om_slots.set_assumption(deal, "occupancy_by_year", "90, 95", USER, db_path=self.db_path)

    def test_every_action_is_logged_for_om_time(self):
        om_slots.set_value(self.deals["fallowmere"], "property.buildings", "2", USER, db_path=self.db_path)
        conn = db.get_connection(self.db_path)
        events = [tuple(r) for r in conn.execute("SELECT action, detail, user FROM om_events")]
        conn.close()
        self.assertEqual(events, [("set", "property.buildings", USER)])


class TestViewingNeverWrites(DbTestCase):
    def test_building_every_deals_om_leaves_the_file_identical(self):
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        from app import queries
        for deal_id in self.deals.values():
            om_engine.build(queries.om_facts(deal_id))
        queries.om_summaries()
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).hexdigest(), before)


class TestSampleDeals(DbTestCase):
    def test_sample_deals_show_low_completion_with_what_they_have_auto_filled(self):
        fallowmere, quillhaven = self.state("fallowmere"), self.state("quillhaven")
        self.assertEqual(fallowmere.slots["property.total_sf"].display, "154,600 SF")
        self.assertEqual(fallowmere.slots["property.leased_pct"].display, "100.0%")
        self.assertEqual(quillhaven.slots["property.total_sf"].status, "empty")
        self.assertGreater(len(quillhaven.required_missing()), len(fallowmere.required_missing()))

    def test_stated_totals_are_saved_for_the_sample_rent_roll(self):
        conn = db.get_connection(self.db_path)
        row = dict(conn.execute("SELECT total_sf, total_annual_rent FROM rent_roll_totals").fetchone())
        conn.close()
        self.assertEqual(row, {"total_sf": 154600.0, "total_annual_rent": 1366485.96})


if __name__ == "__main__":
    unittest.main()
