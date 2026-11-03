"""Adding a property with "+" and renaming a deal with the pencil: validation, the deal_changes log, Undo,
the cover going back for approval, and the new name showing everywhere. No AI is involved. Fictional data only.
"""

from unittest import mock

from services import deals, feed, om_autopilot, om_engine, om_export, om_slots
from tests.test_om_builder import USER
from tests.test_slide_editor import SlideCase


class TestQuickCreate(SlideCase):
    def test_a_name_is_enough_and_spaces_are_trimmed(self):
        deal_id, warning = deals.quick_create("  Larkspur   Yard (test)  ", db_path=self.db_path)
        row = self.table("SELECT name, status, property_type, submarket FROM deals WHERE id = ?", (deal_id,))[0]
        self.assertEqual(row, {"name": "Larkspur Yard (test)", "status": "New", "property_type": None, "submarket": None})
        self.assertIsNone(warning)

    def test_type_and_location_are_optional_and_checked(self):
        deal_id, _ = deals.quick_create("Wrenfield Depot (test)", "Industrial", " Fort Worth, TX ", db_path=self.db_path)
        self.assertEqual(self.table("SELECT property_type, submarket FROM deals WHERE id = ?", (deal_id,))[0],
                         {"property_type": "Industrial", "submarket": "Fort Worth, TX"})
        with self.assertRaisesRegex(ValueError, "Property type must be one of"):
            deals.quick_create("Wrenfield Depot 2 (test)", "Castle", db_path=self.db_path)

    def test_empty_and_too_long_names_are_refused(self):
        for bad in ("", "   ", None):
            with self.assertRaisesRegex(ValueError, "Give the property a name"):
                deals.quick_create(bad, db_path=self.db_path)
        with self.assertRaisesRegex(ValueError, "100 characters or fewer"):
            deals.quick_create("x" * 101, db_path=self.db_path)
        deals.quick_create("x" * 100, db_path=self.db_path)  # exactly the limit is fine

    def test_a_name_already_in_use_is_a_warning_not_a_block(self):
        existing = self.table("SELECT name FROM deals WHERE id = ?", (self.deals["fallowmere"],))[0]["name"]
        deal_id, warning = deals.quick_create(existing.upper(), db_path=self.db_path)
        self.assertIn("already called", warning)
        self.assertEqual(len(self.table("SELECT id FROM deals WHERE id = ?", (deal_id,))), 1)


class TestRename(SlideCase):
    def name(self, deal="fallowmere"):
        return self.table("SELECT name FROM deals WHERE id = ?", (self.deals[deal],))[0]["name"]

    def test_a_rename_is_saved_and_logged(self):
        old = self.name()
        result = deals.update_details(self.deals["fallowmere"], {"name": " Fallowmere Commerce Park (test) "}, USER,
                                      db_path=self.db_path)
        self.assertEqual(result["changed"], ["Property name"])
        self.assertEqual(self.name(), "Fallowmere Commerce Park (test)")
        change = self.table("SELECT field, old_value, new_value, user, reverted_at FROM deal_changes")[0]
        self.assertEqual(change, {"field": "name", "old_value": old, "new_value": "Fallowmere Commerce Park (test)",
                                  "user": USER, "reverted_at": None})
        self.assertTrue(self.table("SELECT * FROM om_events WHERE action = 'renamed'"))

    def test_details_are_logged_one_row_per_field_and_unchanged_fields_are_skipped(self):
        deal = self.deals["quillhaven"]
        before = self.table("SELECT name, property_type FROM deals WHERE id = ?", (deal,))[0]
        result = deals.update_details(deal, {"name": before["name"], "property_type": "Industrial", "submarket": "Springfield, IL"},
                                      USER, db_path=self.db_path)
        self.assertEqual(result["changed"], ["Property type", "Location"])
        self.assertEqual([r["field"] for r in self.table("SELECT field FROM deal_changes ORDER BY id")], ["property_type", "submarket"])

    def test_the_same_checks_as_adding(self):
        for bad, message in (("  ", "Give the property a name"), ("y" * 101, "100 characters or fewer")):
            with self.assertRaisesRegex(ValueError, message):
                deals.update_details(self.deals["fallowmere"], {"name": bad}, USER, db_path=self.db_path)
        result = deals.update_details(self.deals["fallowmere"], {"name": self.name("quillhaven")}, USER, db_path=self.db_path)
        self.assertIn("already called", result["warning"])
        with self.assertRaisesRegex(ValueError, "cannot be changed here"):
            deals.update_details(self.deals["fallowmere"], {"status": "Approved"}, USER, db_path=self.db_path)

    def test_undo_puts_the_old_name_back(self):
        old = self.name()
        result = deals.update_details(self.deals["fallowmere"], {"name": "Renamed (test)"}, USER, db_path=self.db_path)
        self.assertEqual(deals.undo_changes(result["change_ids"], USER, db_path=self.db_path), ["Property name"])
        self.assertEqual(self.name(), old)
        self.assertIsNotNone(self.table("SELECT reverted_at FROM deal_changes WHERE id = ?", (result["change_ids"][0],))[0]["reverted_at"])
        self.assertEqual(deals.undo_changes(result["change_ids"], USER, db_path=self.db_path), [])  # only once

    def test_undo_never_overwrites_a_newer_rename(self):
        first = deals.update_details(self.deals["fallowmere"], {"name": "First (test)"}, USER, db_path=self.db_path)
        deals.update_details(self.deals["fallowmere"], {"name": "Second (test)"}, USER, db_path=self.db_path)
        self.assertEqual(deals.undo_changes(first["change_ids"], USER, db_path=self.db_path), [])
        self.assertEqual(self.name(), "Second (test)")

    def test_renaming_never_calls_gemini_and_never_renames_files(self):
        uploads = self.dir / "uploads"
        deals.save_upload(self.deals["fallowmere"], "rent_roll.csv", b"Unit,SF\n1,100\n", db_path=self.db_path, upload_dir=uploads)
        files = sorted(p.name for p in uploads.rglob("*"))
        with mock.patch("services.gemini.generate", side_effect=AssertionError("Gemini was called")):
            deals.update_details(self.deals["fallowmere"], {"name": "Renamed (test)"}, USER, db_path=self.db_path)
        self.assertEqual(sorted(p.name for p in uploads.rglob("*")), files)


class TestCoverReapproval(SlideCase):
    def test_an_approved_cover_waits_for_approval_again_after_a_rename(self):
        deal = self.deals["brindlewick"]
        self.assertEqual(self.state("brindlewick").slots["property.name"].status, "approved")
        self.assertEqual(self.state("brindlewick").percent, 100)
        result = deals.update_details(deal, {"name": "Brindlewick Market Row (test)"}, USER, db_path=self.db_path)
        self.assertEqual(result["reapprove"], ["Cover", "Property Features"])
        state = self.state("brindlewick")
        name = state.slots["property.name"]
        self.assertEqual((name.status, name.value), ("auto-filled", "Brindlewick Market Row (test)"))
        self.assertEqual(name.note, "Changed since it was approved")
        self.assertEqual(state.slide_status(state.slides[0][1]), "amber")
        self.assertLess(state.percent, 100)
        self.assertTrue(om_export.final_blockers(state))  # client-ready export is locked again

    def test_the_ai_teammate_never_re_approves_the_new_name_by_itself(self):
        deals.update_details(self.deals["brindlewick"], {"name": "Brindlewick Market Row (test)"}, USER, db_path=self.db_path)
        om_autopilot.step_approve(self.deals["brindlewick"], self.state("brindlewick"), self.db_path)
        self.assertEqual(self.state("brindlewick").slots["property.name"].status, "auto-filled")

    def test_undo_brings_the_approval_back_because_the_name_matches_again(self):
        result = deals.update_details(self.deals["brindlewick"], {"name": "Brindlewick Market Row (test)"}, USER,
                                      db_path=self.db_path)
        deals.undo_changes(result["change_ids"], USER, db_path=self.db_path)
        self.assertEqual(self.state("brindlewick").slots["property.name"].status, "approved")

    def test_a_name_the_broker_typed_into_the_om_follows_the_rename(self):
        deal = self.deals["fallowmere"]
        old = self.table("SELECT name FROM deals WHERE id = ?", (deal,))[0]["name"]
        om_slots.set_value(deal, "property.name", old, USER, db_path=self.db_path)
        om_slots.approve(deal, [self.state().slots["property.name"]], USER, self.db_path)
        result = deals.update_details(deal, {"name": "Fallowmere Commerce Park (test)"}, USER, db_path=self.db_path)
        self.assertTrue(result["reapprove"])
        name = self.state().slots["property.name"]
        self.assertEqual((name.status, name.value), ("broker-provided", "Fallowmere Commerce Park (test)"))

    def test_a_different_om_name_chosen_on_purpose_is_left_alone(self):
        deal = self.deals["fallowmere"]
        om_slots.set_value(deal, "property.name", "Fallowmere Logistics (marketing name, test)", USER, db_path=self.db_path)
        result = deals.update_details(deal, {"name": "Fallowmere Commerce Park (test)"}, USER, db_path=self.db_path)
        self.assertEqual(result["reapprove"], [])
        self.assertEqual(self.state().slots["property.name"].value, "Fallowmere Logistics (marketing name, test)")


class TestTheNewNameShowsEverywhere(SlideCase):
    def test_om_footer_export_file_and_home_feed_use_the_new_name(self):
        deal = self.deals["fallowmere"]
        deals.update_details(deal, {"name": "Fallowmere Commerce Park (test)"}, USER, db_path=self.db_path)
        state = self.state()
        self.assertTrue(om_export.footer_text(state).startswith("Fallowmere Commerce Park (test) | "))
        self.assertTrue(om_export.file_stem(self.facts()["deal"]["name"], 1, "draft").startswith("Fallowmere_Commerce_Park_test_OM"))
        self.assertIn("Fallowmere Commerce Park (test)", om_engine.summary_line(state, self.facts()["deal"]["name"]))
        from app import queries
        from datetime import datetime
        items = feed.build(queries.feed_rows(), datetime.now())
        self.assertTrue(any("Fallowmere Commerce Park (test)" in (i.message + " " + (i.deal_name or "")) for i in items))
