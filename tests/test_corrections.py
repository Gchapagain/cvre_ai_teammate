"""Tests for resolving flags: editing, recomputing, confirming, undoing, and validation keeping decisions."""

import json
import tempfile
import unittest
from pathlib import Path

import db
import seed
from services import corrections, validation

USER = "Avery Sample"


class CorrectionsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "corrections.db"
        self.deals = seed.seed(self.db_path)
        self.deal_id = self.deals["fallowmere"]
        self.unit = self.unit_row("110")

    def rows(self, sql, params=()):
        conn = db.get_connection(self.db_path)
        result = [dict(r) for r in conn.execute(sql, params)]
        conn.close()
        return result

    def unit_row(self, number, deal_id=None):
        return self.rows("SELECT * FROM rent_roll_units WHERE deal_id = ? AND unit_number = ?", (deal_id or self.deal_id, number))[0]

    def flags(self):
        return self.rows("SELECT * FROM flags WHERE deal_id = ? ORDER BY id", (self.deal_id,))

    def save(self, unit, values, reason="Checked the signed lease.", source=corrections.MANUAL):
        changes, errors = corrections.plan(unit, values)
        self.assertEqual(errors, [])
        return corrections.apply(self.deal_id, unit["id"], changes, reason, USER, source, self.db_path)


class TestPlan(CorrectionsTestCase):
    def test_monthly_rent_recomputes_annual_rent_and_rent_per_sf(self):
        changes, errors = corrections.plan(self.unit, {"monthly_rent": "$2,400.00"})
        self.assertEqual(errors, [])
        self.assertEqual([(c["field"], c["old"], c["new"], c["derived"]) for c in changes], [
            ("monthly_rent", 5421.33, 2400.0, False), ("annual_rent", 65055.96, 28800.0, True), ("rent_per_sf", 20.33, 9.0, True)])
        self.assertEqual(changes[1]["how"], "Recomputed: annual rent = monthly rent x 12")

    def test_annual_rent_recomputes_monthly_rent(self):
        changes, _ = corrections.plan(self.unit, {"annual_rent": "28800"})
        self.assertEqual([(c["field"], c["new"]) for c in changes], [("annual_rent", 28800.0), ("monthly_rent", 2400.0), ("rent_per_sf", 9.0)])

    def test_sf_recomputes_rent_per_sf_only(self):
        changes, _ = corrections.plan(self.unit, {"square_feet": "7,000"})
        self.assertEqual([(c["field"], c["new"]) for c in changes], [("square_feet", 7000), ("rent_per_sf", 9.29)])

    def test_both_rents_given_only_recomputes_rent_per_sf(self):
        changes, _ = corrections.plan(self.unit, {"monthly_rent": "2400", "annual_rent": "30000"})
        self.assertEqual([c["field"] for c in changes], ["monthly_rent", "annual_rent", "rent_per_sf"])
        self.assertEqual(changes[2]["new"], 9.38)

    def test_unchanged_values_produce_no_change(self):
        changes, errors = corrections.plan(self.unit, {"square_feet": "3200", "tenant_name": "Vantor Robotics Lab"})
        self.assertEqual((changes, errors), ([], []))

    def test_invalid_values_are_explained_and_nothing_is_planned_for_them(self):
        for field, raw, words in (("square_feet", "big", "must be a number"), ("lease_end", "next year", "YYYY-MM-DD"),
                                  ("tenant_name", "  ", "cannot be empty"), ("rent_per_sf", "9", "cannot be edited")):
            with self.subTest(field):
                changes, errors = corrections.plan(self.unit, {field: raw})
                self.assertEqual(changes, [])
                self.assertIn(words, errors[0])

    def test_planning_saves_nothing(self):
        before = self.db_path.read_bytes()
        corrections.plan(self.unit, {"monthly_rent": "2400"})
        self.assertEqual(self.db_path.read_bytes(), before)


class TestApply(CorrectionsTestCase):
    def test_a_fix_is_saved_logged_and_the_flag_is_corrected_not_deleted(self):
        result = self.save(self.unit, {"monthly_rent": "2400"})
        self.assertEqual(len(result["cleared"]), 1)
        self.assertEqual((result["still"], result["new"]), ([], []))
        unit = self.unit_row("110")
        self.assertEqual((unit["monthly_rent"], unit["annual_rent"], unit["rent_per_sf"]), (2400.0, 28800.0, 9.0))
        edits = self.rows("SELECT * FROM edits ORDER BY id")
        self.assertEqual([(e["field"], json.loads(e["old_value"]), json.loads(e["new_value"]), e["derived"]) for e in edits],
                         [("monthly_rent", 5421.33, 2400.0, 0), ("annual_rent", 65055.96, 28800.0, 1), ("rent_per_sf", 20.33, 9.0, 1)])
        self.assertEqual({(e["source"], e["user"]) for e in edits}, {("Manual", USER)})
        self.assertEqual(edits[0]["reason"], "Checked the signed lease.")
        self.assertEqual(len({e["batch_id"] for e in edits}), 1)
        flag = self.flags()[0]
        self.assertEqual((flag["status"], flag["resolved_by"]), ("corrected", USER))
        event = self.rows("SELECT * FROM deal_events")[0]
        self.assertEqual((event["kind"], event["user"], event["source"]), ("edit", USER, "Manual"))
        self.assertIn("Unit 110 Monthly rent: 5,421.33 -> 2,400", event["detail"])

    def test_a_fix_that_does_not_go_far_enough_is_still_flagged(self):
        result = self.save(self.unit, {"monthly_rent": "5000"})
        self.assertEqual(len(result["still"]), 1)
        self.assertEqual(self.flags()[0]["status"], "open")

    def test_a_fix_that_causes_a_new_problem_opens_a_new_flag(self):
        result = self.save(self.unit, {"lease_end": "2020-01-01"})
        self.assertEqual(len(result["new"]), 1)
        self.assertIn("ends on 2020-01-01", result["new"][0])
        self.assertEqual([f["rule"] for f in self.flags() if f["status"] == "open"],
                         ["rent_per_sf_above_2x_average", "lease_end_before_start"])

    def test_a_reason_is_required_and_nothing_empty_is_saved(self):
        changes, _ = corrections.plan(self.unit, {"monthly_rent": "2400"})
        with self.assertRaises(ValueError):
            corrections.apply(self.deal_id, self.unit["id"], changes, "  ", USER, db_path=self.db_path)
        with self.assertRaises(ValueError):
            corrections.apply(self.deal_id, self.unit["id"], [], "reason", USER, db_path=self.db_path)
        self.assertEqual(self.rows("SELECT id FROM edits"), [])

    def test_a_unit_from_another_deal_is_refused(self):
        other = self.unit_row("A", self.deals["brindlewick"])
        changes, _ = corrections.plan(other, {"tenant_name": "Somebody"})
        with self.assertRaises(ValueError):
            corrections.apply(self.deal_id, other["id"], changes, "reason", USER, db_path=self.db_path)

    def test_originals_show_the_extracted_value_and_who_changed_it(self):
        self.save(self.unit, {"monthly_rent": "2400"})
        self.save(self.unit_row("110"), {"monthly_rent": "2500"}, reason="Second look.")
        info = corrections.originals(self.deal_id, self.db_path)[(self.unit["id"], "monthly_rent")]
        self.assertEqual((info["original"], info["user"], info["reason"], info["source"]), (5421.33, USER, "Second look.", "Manual"))


class TestUndo(CorrectionsTestCase):
    def test_undo_restores_every_value_logs_and_re_checks(self):
        result = self.save(self.unit, {"monthly_rent": "2400"})
        corrections.undo(result["batch_id"], USER, self.db_path)
        unit = self.unit_row("110")
        self.assertEqual((unit["monthly_rent"], unit["annual_rent"], unit["rent_per_sf"]), (5421.33, 65055.96, 20.33))
        self.assertTrue(all(e["reverted_at"] for e in self.rows("SELECT * FROM edits")))
        self.assertEqual([e["kind"] for e in self.rows("SELECT kind FROM deal_events ORDER BY id")], ["edit", "undo"])
        flags = self.flags()
        self.assertEqual([(f["status"], f["resolved_by"]) for f in flags], [("open", None)])  # the same row, open again
        self.assertEqual(corrections.originals(self.deal_id, self.db_path), {})

    def test_undo_twice_and_out_of_order_are_refused(self):
        first = self.save(self.unit, {"monthly_rent": "2400"})
        second = self.save(self.unit_row("110"), {"monthly_rent": "2500"})
        with self.assertRaises(ValueError) as caught:
            corrections.undo(first["batch_id"], USER, self.db_path)
        self.assertIn("Undo the later change first", str(caught.exception))
        corrections.undo(second["batch_id"], USER, self.db_path)
        with self.assertRaises(ValueError):
            corrections.undo(second["batch_id"], USER, self.db_path)
        corrections.undo(first["batch_id"], USER, self.db_path)
        self.assertEqual(self.unit_row("110")["monthly_rent"], 5421.33)


class TestConfirm(CorrectionsTestCase):
    def test_confirm_keeps_the_flag_visible_and_changes_no_data(self):
        before = self.unit_row("110")
        flag_id = self.flags()[0]["id"]
        corrections.confirm_flag(flag_id, "Special lease - verified", "Lab fit-out premium in the signed lease.", USER, self.db_path)
        flag = self.flags()[0]
        self.assertEqual((flag["status"], flag["resolved_by"], flag["resolution_reason"], flag["resolution_note"]),
                         ("confirmed", USER, "Special lease - verified", "Lab fit-out premium in the signed lease."))
        self.assertTrue(flag["resolved_at"])
        self.assertEqual(self.unit_row("110"), before)
        self.assertEqual(self.rows("SELECT id FROM edits"), [])
        self.assertEqual(self.rows("SELECT kind FROM deal_events"), [{"kind": "confirmed"}])

    def test_a_reason_and_a_note_are_required(self):
        flag_id = self.flags()[0]["id"]
        for reason, note in (("Made up reason", "note"), ("Other", ""), (None, "note")):
            with self.subTest(reason=reason, note=note):
                with self.assertRaises(ValueError):
                    corrections.confirm_flag(flag_id, reason, note, USER, self.db_path)
        self.assertEqual(self.flags()[0]["status"], "open")


class TestValidationKeepsDecisions(CorrectionsTestCase):
    def test_a_confirmed_flag_with_an_unchanged_value_stays_confirmed(self):
        flag_id = self.flags()[0]["id"]
        corrections.confirm_flag(flag_id, "Source file is right", "Checked.", USER, self.db_path)
        validation.validate_deal(self.deal_id, self.db_path)
        validation.validate_deal(self.deal_id, self.db_path)
        flags = self.flags()
        self.assertEqual([(f["id"], f["status"], f["resolution_note"]) for f in flags], [(flag_id, "confirmed", "Checked.")])

    def test_another_edit_elsewhere_keeps_the_confirmation(self):
        flag_id = self.flags()[0]["id"]
        corrections.confirm_flag(flag_id, "Source file is right", "Checked.", USER, self.db_path)
        self.save(self.unit_row("101"), {"tenant_name": "Northfield Pallet Company"})
        self.assertEqual(self.flags()[0]["status"], "confirmed")

    def test_a_changed_value_that_no_longer_fires_is_corrected_and_kept(self):
        flag_id = self.flags()[0]["id"]
        self.save(self.unit, {"monthly_rent": "2400"})
        flags = self.flags()
        self.assertEqual([(f["id"], f["status"]) for f in flags], [(flag_id, "corrected")])
        self.assertIn("no longer fires", flags[0]["resolution_reason"])

    def test_a_confirmed_flag_whose_value_changes_but_still_fires_is_reopened(self):
        corrections.confirm_flag(self.flags()[0]["id"], "Source file is right", "Checked.", USER, self.db_path)
        self.save(self.unit, {"monthly_rent": "5300"})
        flag = self.flags()[0]
        self.assertEqual((flag["status"], flag["resolved_by"], flag["actual_value"]), ("open", None, "19.88"))

    def test_a_change_that_creates_a_new_problem_opens_a_new_flag(self):
        self.save(self.unit_row("101"), {"lease_end": "2021-01-01"})
        opened = [f for f in self.flags() if f["unit_number"] == "101"]
        self.assertEqual([(f["rule"], f["status"]) for f in opened], [("lease_end_before_start", "open")])

    def test_a_corrected_problem_that_comes_back_is_reopened_and_the_timeline_keeps_the_story(self):
        flag_id = self.flags()[0]["id"]
        self.save(self.unit, {"monthly_rent": "2400"})
        self.save(self.unit_row("110"), {"monthly_rent": "5421.33"})
        self.assertEqual([(f["id"], f["status"], f["resolution_reason"]) for f in self.flags()], [(flag_id, "open", None)])
        self.assertEqual([e["kind"] for e in self.rows("SELECT kind FROM deal_events ORDER BY id")], ["edit", "edit"])

    def test_rerunning_validation_never_deletes_a_flag(self):
        for _ in range(3):
            validation.validate_deal(self.deal_id, self.db_path)
        self.assertEqual(len(self.flags()), 1)


class TestApprovedDealsAreLocked(CorrectionsTestCase):
    def test_edits_undo_and_confirmations_are_refused_on_an_approved_deal(self):
        result = self.save(self.unit, {"monthly_rent": "2400"})
        flag_id = self.flags()[0]["id"]
        conn = db.get_connection(self.db_path)
        with conn:
            conn.execute("UPDATE deals SET status = 'Approved' WHERE id = ?", (self.deal_id,))
        conn.close()
        changes, _ = corrections.plan(self.unit_row("110"), {"monthly_rent": "2500"})
        with self.assertRaises(corrections.Locked):
            corrections.apply(self.deal_id, self.unit["id"], changes, "reason", USER, db_path=self.db_path)
        with self.assertRaises(corrections.Locked):
            corrections.undo(result["batch_id"], USER, self.db_path)
        validation.validate_deal(self.deal_id, self.db_path)
        with self.assertRaises((corrections.Locked, ValueError)):
            corrections.confirm_flag(flag_id, "Other", "note", USER, self.db_path)


if __name__ == "__main__":
    unittest.main()


class TestApproval(CorrectionsTestCase):
    def deal(self):
        return self.rows("SELECT status, approved_by, approved_at FROM deals WHERE id = ?", (self.deal_id,))[0]

    def resolve(self):
        corrections.confirm_flag(self.flags()[0]["id"], "Special lease - verified", "Checked the lease.", USER, self.db_path)

    def test_approval_is_refused_while_a_flag_is_open(self):
        with self.assertRaises(ValueError) as caught:
            corrections.approve(self.deal_id, USER, self.db_path)
        self.assertIn("still open", str(caught.exception))
        self.assertEqual(self.deal()["status"], "Needs Review")

    def test_approve_records_who_and_when_and_logs_it(self):
        self.save(self.unit_row("101"), {"tenant_name": "Northfield Pallet Company"})
        self.resolve()
        summary = corrections.approval_summary(self.deal_id, self.db_path)
        self.assertEqual((len(summary["confirmed"]), len(summary["corrected"]), len(summary["edits"])), (1, 0, 1))
        self.assertEqual((summary["edits"][0]["old"], summary["edits"][0]["new"]), ("Northfield Pallet Co.", "Northfield Pallet Company"))
        corrections.approve(self.deal_id, USER, self.db_path)
        deal = self.deal()
        self.assertEqual((deal["status"], deal["approved_by"]), ("Approved", USER))
        self.assertTrue(deal["approved_at"])
        event = self.rows("SELECT * FROM deal_events WHERE kind = 'approved'")[0]
        self.assertEqual(event["detail"], "1 flag(s) confirmed, 0 corrected, 1 value(s) changed.")

    def test_reverted_edits_are_not_in_the_summary(self):
        result = self.save(self.unit_row("101"), {"tenant_name": "Northfield Pallet Company"})
        corrections.undo(result["batch_id"], USER, self.db_path)
        self.assertEqual(corrections.approval_summary(self.deal_id, self.db_path)["edits"], [])

    def test_reopen_needs_a_reason_unlocks_and_keeps_the_history(self):
        self.resolve()
        corrections.approve(self.deal_id, USER, self.db_path)
        with self.assertRaises(ValueError):
            corrections.reopen(self.deal_id, "  ", USER, self.db_path)
        corrections.reopen(self.deal_id, "Owner sent a corrected rent roll.", USER, self.db_path)
        deal = self.deal()
        self.assertEqual((deal["status"], deal["approved_by"], deal["approved_at"]), ("Needs Review", None, None))
        events = self.rows("SELECT kind, reason FROM deal_events ORDER BY id")
        self.assertEqual([e["kind"] for e in events], ["confirmed", "approved", "reopened"])
        self.assertEqual(events[-1]["reason"], "Owner sent a corrected rent roll.")
        self.save(self.unit_row("101"), {"tenant_name": "Northfield Pallet Company"})  # editing works again

    def test_reopening_a_deal_that_is_not_approved_is_refused(self):
        with self.assertRaises(ValueError):
            corrections.reopen(self.deal_id, "reason", USER, self.db_path)

    def test_the_sample_approved_deal_records_its_approver(self):
        deal = self.rows("SELECT status, approved_by FROM deals WHERE id = ?", (self.deals["brindlewick"],))[0]
        self.assertEqual(deal, {"status": "Approved", "approved_by": "Avery Sample"})
