"""The OM tab in the running app (Streamlit AppTest): every view renders, and a person's clicks save.

No Gemini: AI buttons are either not clicked or their service is replaced with a canned result.
"""

import tempfile
from pathlib import Path
from unittest import mock

from services import om_export
from tests.test_app import AppTestCase


class OmTabCase(AppTestCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(om_export, "EXPORT_DIR", Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sign_in()

    def open_view(self, deal, view):
        self.open_deal(deal)
        self.app.session_state["om_view"] = view
        self.app.run()
        self.assertFalse(self.app.exception, [e.value for e in self.app.exception])

    def keys(self, prefix, kind="button"):
        return [w.key for w in getattr(self.app, kind) if w.key and w.key.startswith(prefix)]


class TestOmViews(OmTabCase):
    def test_every_view_renders_for_every_sample_deal(self):
        for deal in ("fallowmere", "quillhaven", "brindlewick"):
            for view in ("Checklist", "Slides", "Photos", "Pricing", "Client", "Export"):
                with self.subTest(deal=deal, view=view):
                    self.open_view(deal, view)

    def test_the_slide_navigator_lists_every_slide_with_its_colour(self):
        self.open_view("fallowmere", "Slides")
        labels = [b.label for b in self.app.button if b.key and b.key.startswith("om_slide_")]
        self.assertEqual(len(labels), 18)
        self.assertTrue(labels[0].startswith("🔴 1. Cover") or labels[0].startswith("🟢 1. Cover"))
        self.assertTrue(any(label.startswith("🔴") for label in labels))
        self.app.button(key="om_slide_rent_roll").click().run()
        self.assertEqual(self.app.session_state["om_slide"], "rent_roll")

    def test_client_ready_export_is_locked_until_100_percent(self):
        self.open_view("quillhaven", "Export")
        self.assertTrue(self.app.button(key="om_export_final").disabled)
        self.open_view("brindlewick", "Export")
        self.assertFalse(self.app.button(key="om_export_final").disabled)


class TestOmInterview(OmTabCase):
    def test_typing_an_answer_saves_it_waiting_for_approval_then_approve_section(self):
        self.open_view("quillhaven", "Checklist")
        self.assertIn("Help me finish the OM", self.page_text())
        boxes = self.keys("om_answer_", "text_area")
        while not boxes:  # move to the first question you can type an answer to
            self.app.button(key="om_q_next").click().run()
            boxes = self.keys("om_answer_", "text_area")
        slot_id = boxes[0].removeprefix("om_answer_").replace("_", ".", 1)
        answer = {"property.address": "7 Example Court (test)", "property.city_state": "Springfield, IL"}.get(slot_id, "Made up answer for the test")
        self.app.text_area(key=boxes[0]).set_value(answer).run()
        self.app.button(key="om_q_save").click().run()
        self.assertFalse(self.app.exception)
        from app import queries
        from services import om_engine
        state = om_engine.build(queries.om_facts(self.deals["quillhaven"]))
        self.assertEqual(state.slots[slot_id].status, "broker-provided")
        section = state.slots[slot_id].section
        self.app.button(key=f"om_approve_section_{section}").click().run()
        state = om_engine.build(queries.om_facts(self.deals["quillhaven"]))
        self.assertEqual(state.slots[slot_id].status, "approved")

    def test_ask_the_client_builds_one_message_and_records_it(self):
        self.open_view("quillhaven", "Client")
        message = self.app.code[0].value
        self.assertTrue(message.startswith("Hi there,"))
        self.assertIn("Property details", message)
        self.assertIn("never sends anything to a client", self.page_text())
        self.app.button(key="om_client_sent").click().run()
        from app import queries
        asked = [q for q in queries.om_questions(self.deals["quillhaven"]) if q["audience"] == "client"]
        self.assertTrue(asked)

    def test_the_price_is_typed_by_the_broker_and_price_per_sf_follows(self):
        self.open_view("fallowmere", "Pricing")
        self.app.text_input(key="om_price_text").set_value("15,460,000").run()
        self.app.button(key="om_price_save").click().run()
        from app import queries
        from services import om_engine
        state = om_engine.build(queries.om_facts(self.deals["fallowmere"]))
        self.assertEqual(state.slots["financial.sale_price"].display, "$15,460,000")
        self.assertEqual(state.slots["financial.price_per_sf"].display, "$100.00")

    def test_draft_all_text_reports_what_the_ai_did(self):
        result = {"saved": ["The Offering"], "dropped": ["Highlights: rare opportunity: not saved, because 9 is not in the deal's data."],
                  "skipped": [], "questions": ["No accepted research for Alliance yet, so the AI did not write the location."]}
        with mock.patch("services.om_drafting.draft_all_text", return_value=result) as draft:
            self.open_view("fallowmere", "Checklist")
            self.app.button(key="om_draft_all").click().run()
        self.assertEqual(draft.call_count, 1)
        info = " ".join(i.value for i in self.app.info)
        self.assertIn("Drafted: The Offering.", info)
        self.assertIn("not saved, because 9", info)
        self.assertIn("No accepted research", info)
