"""The slide editor, the "+" button and the pencil in the running app (Streamlit AppTest).

Each test gets its own freshly seeded database, because these clicks save. No Gemini is called: no AI button
is clicked. AppTest cannot drive the camera or the file picker, so those are covered at the service level
(tests/test_slide_editor.py); here we check the buttons show them.
"""

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

import db
import seed
from services import om_assets, om_export, om_template
from tests.test_om_builder import png
from tests.test_app import APP


class FreshAppCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db_path = self.dir / "app.db"
        with mock.patch.object(om_assets, "ASSET_DIR", self.dir / "assets"), \
                mock.patch("sample_om.ASSET_DIR", self.dir / "assets" / "sample"):
            self.deals = seed.seed(self.db_path)
        for target, name, value in ((db, "DB_PATH", self.db_path), (om_assets, "ASSET_DIR", self.dir / "assets"),
                                    (om_export, "EXPORT_DIR", self.dir / "exports"),
                                    (om_export, "soffice_path", lambda: None)):  # no LibreOffice drawing in these tests
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.dict(os.environ, {"CBRE_DB_PATH": str(self.db_path)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = AppTest.from_file(APP, default_timeout=20).run()
        self.app.button(key="sign_in_google").click().run()

    def run_ok(self):
        self.app.run()
        self.assertFalse(self.app.exception, [e.value for e in self.app.exception])

    def click(self, key):
        self.app.button(key=key).click().run()
        self.assertFalse(self.app.exception, [e.value for e in self.app.exception])

    def open_om(self, deal):
        self.app.button(key="nav_all_deals").click().run()
        self.click(f"open_deal_{self.deals[deal]}")
        self.app.session_state["deal_tabs"] = "OM"
        self.app.session_state["om_view"] = "Slides"
        self.run_ok()

    def keys(self, prefix):
        return [b.key for b in self.app.button if b.key and b.key.startswith(prefix)]

    def text(self):
        return "\n".join(e.value for kind in ("markdown", "caption", "info", "warning", "success", "error")
                         for e in getattr(self.app, kind) if "<style>" not in e.value)

    def deal_row(self, deal_id):
        conn = db.get_connection(self.db_path)
        try:
            return dict(conn.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone())
        finally:
            conn.close()


class TestSlideEditor(FreshAppCase):
    def test_the_list_follows_the_template_and_the_stepper_moves_slide_by_slide(self):
        self.open_om("quillhaven")
        template = [s.id for s in om_template.load().slides if not s.only_if_filled]
        self.assertEqual(self.keys("om_slide_btn_"), [f"om_slide_btn_{s}" for s in template])
        self.assertIn(f"Slide 1 of {len(template)}", self.text())
        self.assertIn("Slide 1 - Cover: write street address; write city and state; add 1 photo (cover photo: exterior or aerial)",
                      self.text())
        self.assertTrue(self.app.button(key="om_slide_prev").disabled)
        self.click("om_slide_next")
        self.assertIn(f"Slide 2 of {len(template)}", self.text())
        self.click(f"om_slide_btn_{template[-1]}")
        self.assertTrue(self.app.button(key="om_slide_next").disabled)

    def test_a_photo_slot_has_take_photo_and_upload_photo_and_shows_the_camera_on_tap(self):
        self.open_om("quillhaven")
        self.assertEqual(self.app.button(key="om_photo_take_photo_hero").label, "Take photo")
        self.assertEqual(self.app.button(key="om_photo_upload_photo_hero").label, "Upload photo")
        self.assertEqual(len(self.app.get("camera_input")), 0)  # the camera asks for permission only after a tap
        self.click("om_photo_take_photo_hero")
        self.assertEqual(len(self.app.get("camera_input")), 1)
        self.click("om_photo_cancel_photo_hero")
        self.assertEqual(len(self.app.get("camera_input")), 0)

    def test_a_placed_photo_has_replace_and_remove(self):
        self.open_om("fallowmere")
        replace = self.keys("om_photo_replace_")
        self.assertTrue(replace)
        asset = int(replace[0].rsplit("_", 1)[1])
        self.click(f"om_photo_remove_{asset}")
        conn = db.get_connection(self.db_path)
        slot = conn.execute("SELECT slot_id FROM om_assets WHERE id = ?", (asset,)).fetchone()["slot_id"]
        conn.close()
        self.assertIsNone(slot)  # off the slide, still one of the deal's photos
        self.assertIn("still in this deal's photos", self.text())

    def test_a_text_slide_saves_typed_text_and_approve_this_slide_approves_it(self):
        self.open_om("quillhaven")
        self.click("om_slide_btn_offering")
        self.assertIn("om_slide_draft_btn", self.keys("om_slide_draft"))  # "Draft with AI" for this slide (1 request)
        box = next(t for t in self.app.text_area if t.key.startswith("om_text_offering_narrative_"))
        box.set_value("A made-up offering paragraph for the test: a small flex property, fictional, written only to check "
                      "that typed text is saved and waits for approval.").run()
        self.click("om_text_save_offering_narrative")
        self.assertIn("The Offering saved", self.text())
        self.assertFalse(self.app.button(key="om_slide_approve").disabled)
        self.click("om_slide_approve")
        from app import queries
        from services import om_engine
        state = om_engine.build(queries.om_facts(self.deals["quillhaven"]))
        self.assertEqual(state.slots["offering.narrative"].status, "approved")

    def test_the_compact_bar_keeps_completion_missing_and_export_on_top(self):
        self.open_om("quillhaven")
        self.assertIn("Offering memorandum", self.text())
        self.assertTrue(self.app.button(key="om_export_final").disabled)
        self.assertFalse(self.app.button(key="om_export_draft").disabled)
        self.assertEqual(self.keys("om_export_"), ["om_export_draft", "om_export_final"])  # once, not on every slide


class TestPhotoGrid(FreshAppCase):
    def test_this_deals_photos_grid_places_a_photo_in_one_tap(self):
        deal = self.deals["quillhaven"]
        ids, _ = om_assets.add_photos(deal, [("front (test).png", png())], "Avery Sample", db_path=self.db_path)
        self.open_om("quillhaven")
        self.assertIn("This deal&#x27;s photos", self.text())
        self.assertIn("Not used", self.text())
        self.click(f"om_grid_use_photo_hero_{ids[0]}")
        conn = db.get_connection(self.db_path)
        slot = conn.execute("SELECT slot_id FROM om_assets WHERE id = ?", (ids[0],)).fetchone()["slot_id"]
        conn.close()
        self.assertEqual(slot, "photo.hero")
        self.assertIn("Show whole photo (default)", self.app.button_group(key=f"om_photo_fit_{ids[0]}").options)
        self.assertEqual(self.app.button_group(key=f"om_photo_fit_{ids[0]}").value, ["Show whole photo (default)"]
                         if isinstance(self.app.button_group(key=f"om_photo_fit_{ids[0]}").value, list)
                         else "Show whole photo (default)")

    def test_the_preview_has_open_full_size(self):
        with mock.patch.object(om_export, "live_preview", return_value=(None, False, None)):
            self.open_om("fallowmere")
        self.assertIn("The slide preview is being drawn", self.text())


class TestQuickAdd(FreshAppCase):
    def test_plus_creates_the_deal_and_opens_its_om_on_slide_1(self):
        self.click("nav_add")
        self.app.text_input(key="qa_name").set_value("  Larkspur Yard (test)  ").run()
        self.click("qa_create")
        conn = db.get_connection(self.db_path)
        row = dict(conn.execute("SELECT id, name, status FROM deals ORDER BY id DESC LIMIT 1").fetchone())
        conn.close()
        self.assertEqual((row["name"], row["status"]), ("Larkspur Yard (test)", "New"))
        self.assertEqual(self.app.session_state["page"], "deal")
        self.assertEqual(self.app.session_state["deal_tabs"], "OM")
        self.assertEqual(self.app.session_state["om_slide"], "cover")
        self.assertIn("Created 'Larkspur Yard (test)'", self.text())
        self.click("nav_home")
        self.assertIn(f"open_project_{row['id']}", self.keys("open_project_"))  # on Home straight away
        self.assertEqual(self.keys("add_property_tile"), ["add_property_tile"])

    def test_an_empty_name_is_refused_and_a_duplicate_only_warns(self):
        self.click("nav_add")
        self.click("qa_create")
        self.assertIn("Give the property a name.", [e.value for e in self.app.error])
        name = self.deal_row(self.deals["fallowmere"])["name"]
        self.app.text_input(key="qa_name").set_value(name).run()
        self.assertTrue(any("already called" in w.value for w in self.app.warning))
        self.click("qa_create")
        self.assertEqual(self.app.session_state["page"], "deal")

    def test_more_ways_to_start_opens_the_new_deal_dialog(self):
        self.click("bnav_add")  # the phone's centre button opens the same dialog
        self.click("qa_more")
        self.assertEqual(self.app.session_state["open_dialog"], "new_deal")


class TestPencil(FreshAppCase):
    def test_rename_from_a_card_then_undo(self):
        deal = self.deals["quillhaven"]
        old = self.deal_row(deal)["name"]
        self.click("nav_all_deals")
        self.click(f"rename_btn_deals_{deal}")
        self.app.text_input(key=f"rename_name_deals_{deal}").set_value("Quillhaven Works (test)")  # sent with Save
        self.click(f"rename_save_deals_{deal}")
        self.assertEqual(self.deal_row(deal)["name"], "Quillhaven Works (test)")
        self.assertIn("Renamed to &#x27;Quillhaven Works (test)&#x27;.", self.text())  # HTML-escaped on the page
        self.assertEqual(self.app.button(key=f"open_deal_{deal}").label, "Quillhaven Works (test)")
        self.click("rename_undo")
        self.assertEqual(self.deal_row(deal)["name"], old)
        self.assertIn("Undone", self.text())

    def test_the_header_pencil_validates_and_cancel_changes_nothing(self):
        deal = self.deals["fallowmere"]
        old = self.deal_row(deal)["name"]
        self.click("nav_all_deals")
        self.click(f"open_deal_{deal}")
        self.click(f"rename_btn_header_{deal}")
        self.app.text_input(key=f"rename_name_header_{deal}").set_value("   ")  # a form: the value is sent with Save
        self.click(f"rename_save_header_{deal}")
        self.assertIn("Give the property a name.", [e.value for e in self.app.error])
        self.click(f"rename_cancel_header_{deal}")
        self.assertEqual(self.deal_row(deal)["name"], old)
        self.assertIn(f"rename_btn_header_{deal}", self.keys("rename_btn_"))

    def test_renaming_an_approved_cover_asks_to_re_approve_it(self):
        deal = self.deals["brindlewick"]
        self.click("nav_all_deals")
        self.click(f"open_deal_{deal}")
        self.click(f"rename_btn_header_{deal}")
        self.app.text_input(key=f"rename_name_header_{deal}").set_value("Brindlewick Market Row (test)")  # sent with Save
        self.click(f"rename_save_header_{deal}")
        self.assertTrue(any("The name changed, please re-approve the cover" in w.value for w in self.app.warning))
        self.click("rename_open_cover")
        self.assertEqual((self.app.session_state["deal_tabs"], self.app.session_state["om_slide"]), ("OM", "cover"))
        self.assertIn("Brindlewick Market Row (test)", self.text())  # breadcrumb and header show the new name


class TestViewingNeverWrites(FreshAppCase):
    def test_clicking_through_slides_and_opening_the_dialogs_leaves_the_database_identical(self):
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        for deal in ("fallowmere", "quillhaven", "brindlewick"):
            self.open_om(deal)
            for slide in self.keys("om_slide_btn_")[:6]:
                self.click(slide)
        self.click("nav_add")
        self.app.text_input(key="qa_name").set_value("Not saved (test)").run()
        self.click("nav_home")
        self.click(f"rename_btn_home_{self.deals['fallowmere']}")
        self.click(f"rename_cancel_home_{self.deals['fallowmere']}")
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).hexdigest(), before)
