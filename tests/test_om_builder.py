"""Tests for the OM Builder's interview, client questions, AI drafts, photos, assumptions and settings.

Gemini is always simulated here (FakeGemini counts every request). Fictional data only.
"""

import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image
from pptx import Presentation

import db
import seed
from services import (branding, gemini, om_assets, om_calc, om_drafting, om_engine, om_export, om_interview, om_slots,
                      om_template, qa)

USER = "Avery Sample"


class FakeGemini:
    """Replies in order and counts requests. A reply that is an exception is raised instead."""

    def __init__(self, *replies):
        self.replies, self.calls, self.prompts = list(replies), 0, []
        self.models = self

    def generate_content(self, model=None, contents=None, config=None):
        self.calls += 1
        self.prompts.append(contents)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(text=json.dumps(reply), candidates=[], usage_metadata=None)


def png(size=(400, 300), colour=(120, 150, 170)):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


class DbCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db_path = self.dir / "om.db"
        with mock.patch.object(om_assets, "ASSET_DIR", self.dir / "assets"), \
                mock.patch("sample_om.ASSET_DIR", self.dir / "assets" / "sample"):
            self.deals = seed.seed(self.db_path)
        for target, value in ((db, "DB_PATH"), (om_assets, "ASSET_DIR"), (om_export, "EXPORT_DIR"), (branding, "BRANDING_DIR")):
            patcher = mock.patch.object(target, value, self.db_path if value == "DB_PATH" else self.dir / value.lower())
            patcher.start()
            self.addCleanup(patcher.stop)

    def facts(self, deal="fallowmere"):
        from app import queries
        return queries.om_facts(self.deals[deal])

    def state(self, deal="fallowmere"):
        return om_engine.build(self.facts(deal))


# ---------- the interview and client questions (no AI) ----------

class TestInterview(DbCase):
    def test_questions_come_from_the_template_required_first(self):
        questions = om_interview.questions(self.state())
        required = [q.slot.required for q in questions]
        self.assertEqual(required, sorted(required, reverse=True))
        self.assertTrue(all(q.text for q in questions))
        kinds = {q.slot.id: q.kind for q in questions}
        self.assertEqual(kinds["offering.narrative"], "answer")
        self.assertEqual(kinds["photo.site_plan"], "photo")
        self.assertEqual(kinds["financial.sale_price"], "pricing")
        self.assertEqual(kinds["financial.cash_flow"], "pricing")

    def test_a_skipped_question_moves_to_the_end_and_is_recorded(self):
        first = om_interview.questions(self.state())[0]
        om_interview.skip(self.deals["fallowmere"], first.slot.id, first.text, USER, self.db_path)
        from app import queries
        skipped = {q["slot_id"] for q in queries.om_questions(self.deals["fallowmere"]) if q["status"] == "skipped"}
        questions = om_interview.questions(self.state(), skipped)
        self.assertEqual(questions[-1].slot.id, first.slot.id)
        self.assertTrue(questions[-1].skipped)

    def test_quillhaven_asks_for_the_basics(self):
        ids = [q.slot.id for q in om_interview.questions(self.state("quillhaven"))]
        for slot_id in ("property.address", "property.city_state", "photo.hero", "property.total_sf"):
            self.assertIn(slot_id, ids)


class TestClientMessage(DbCase):
    def test_one_message_grouped_by_topic_with_each_question_once(self):
        state = self.state("quillhaven")
        items = [state.slots[i] for i in ("property.address", "photo.grid", "property.city_state", "photo.features",
                                          "property.year_built")]
        message = om_interview.client_message("Quillhaven Flex Center", items, "Avery Sample", "Jordan")
        self.assertTrue(message.startswith("Hi Jordan,"))
        self.assertIn("Quillhaven Flex Center", message)
        self.assertLess(message.index("Property details"), message.index("Photos"))
        # photo.grid and photo.features share one client question: asked once.
        self.assertEqual(message.count("Could you share a few recent exterior and interior photos"), 1)
        self.assertIn("4. ", message)
        self.assertNotIn("5. ", message)
        self.assertTrue(message.rstrip().endswith("Avery Sample"))

    def test_saving_records_each_question_for_the_client(self):
        state = self.state("quillhaven")
        items = [state.slots["property.address"], state.slots["property.year_built"]]
        om_interview.save_client_questions(self.deals["quillhaven"], items, "message", USER, self.db_path)
        from app import queries
        asked = [(q["slot_id"], q["audience"], q["status"]) for q in queries.om_questions(self.deals["quillhaven"])]
        self.assertEqual(asked, [("property.address", "client", "open"), ("property.year_built", "client", "open")])

    def test_friendlier_uses_one_request_and_keeps_every_question(self):
        message = "Hi there,\n\n1. Address?\n2. Year built?\n\nThank you,\nAvery"
        fake = FakeGemini({"message": "Hello!\n\n1. Could you share the address?\n2. And the year built?\n\nThanks,\nAvery"})
        self.assertIn("Could you share the address", om_interview.friendlier(message, fake))
        self.assertEqual(fake.calls, 1)

    def test_friendlier_is_refused_when_it_drops_a_question_or_adds_a_number(self):
        message = "Hi,\n\n1. Address?\n2. Year built?\n\nThanks"
        with self.assertRaises(gemini.GeminiError):
            om_interview.friendlier(message, FakeGemini({"message": "Hi,\n\n1. Address?\n\nThanks"}))
        with self.assertRaises(gemini.GeminiError):
            om_interview.friendlier(message, FakeGemini({"message": "Hi,\n\n1. Address?\n2. Built after 1990?\n\nThanks"}))


# ---------- reading the client's reply (1 request, simulated) ----------

class TestClientReply(DbCase):
    REPLY = "Hi Avery, the site is about 11.2 acres and it has 3 buildings. Built in 2004, new roofs in 2019."

    def read(self, *replies, deal="quillhaven", text=None):
        fake = FakeGemini(*replies)
        return om_interview.read_reply(self.state(deal), text or self.REPLY, fake), fake

    def test_a_reply_fills_two_items_after_apply(self):
        checked, fake = self.read({"proposals": [
            {"slot_id": "property.land_size", "value": "11.2 acres", "quote": "about 11.2 acres"},
            {"slot_id": "property.buildings", "value": "3", "quote": "3 buildings"}], "unclear": []})
        self.assertEqual(fake.calls, 1)
        self.assertEqual([p["slot_id"] for p in checked.proposals], ["property.land_size", "property.buildings"])
        self.assertEqual(checked.proposals[0]["before"], "(empty)")
        before = self.state("quillhaven").slots["property.land_size"].status
        self.assertEqual(before, "empty")  # nothing saved by reading
        for proposal in checked.proposals:
            om_interview.apply(self.deals["quillhaven"], proposal, USER, db_path=self.db_path)
        state = self.state("quillhaven")
        for slot_id, value in (("property.land_size", "11.2 acres"), ("property.buildings", 3)):
            slot = state.slots[slot_id]
            self.assertEqual((slot.status, slot.value, slot.source["kind"]), ("broker-provided", value, "client_reply"))

    def test_an_ambiguous_reply_proposes_nothing_and_says_why(self):
        checked, _ = self.read({"proposals": [], "unclear": ["'about 3' could be buildings or acres"]},
                               text="There are about 3 of them.")
        self.assertEqual(checked.proposals, [])
        self.assertEqual(checked.unclear, ["'about 3' could be buildings or acres"])

    def test_invalid_values_numbers_not_in_the_reply_and_closed_items_are_left_out(self):
        checked, _ = self.read({"proposals": [
            {"slot_id": "property.year_built", "value": "old", "quote": "Built"},
            {"slot_id": "property.land_size", "value": "12.5 acres", "quote": "about 11.2 acres"},
            {"slot_id": "financial.sale_price", "value": "5000000", "quote": ""},
            {"slot_id": "property.buildings", "value": "3", "quote": "3 buildings"}], "unclear": []})
        self.assertEqual([p["slot_id"] for p in checked.proposals], ["property.buildings"])
        reasons = " ".join(checked.rejected)
        self.assertIn("Year built / renovated: left out", reasons)
        self.assertIn("12.5 is not in the reply", reasons)
        self.assertIn("financial.sale_price", reasons)  # the price is never taken from a client reply

    def test_a_quota_error_saves_nothing(self):
        with self.assertRaises(gemini.GeminiQuotaError):
            self.read(gemini.GeminiQuotaError("Daily limit reached."))
        self.assertEqual(self.state("quillhaven").slots["property.land_size"].status, "empty")

    def test_documents_are_read_or_refused_plainly(self):
        self.assertIn("11.2 acres", om_interview.document_text("survey.txt", b"Site area 11.2 acres"))
        with self.assertRaisesRegex(ValueError, "not supported"):
            om_interview.document_text("survey.docx", b"PK...")
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.encrypt("secret")
        out = io.BytesIO()
        writer.write(out)
        with self.assertRaisesRegex(ValueError, "Needs password"):
            om_interview.document_text("locked.pdf", out.getvalue())


class TestReadAnswer(unittest.TestCase):
    def test_the_ai_puts_an_answer_in_format_with_one_request(self):
        slot = om_template.load().slots["property.year_built"]
        fake = FakeGemini({"value": "1998 / 2019"})
        self.assertEqual(om_interview.read_answer(slot, "it went up in 98, roof redone 2019, 1998 really", fake), "1998 / 2019")
        self.assertEqual(fake.calls, 1)

    def test_a_number_the_person_did_not_write_is_refused(self):
        slot = om_template.load().slots["property.buildings"]
        with self.assertRaises(om_slots.InvalidValue):
            om_interview.read_answer(slot, "a few buildings", FakeGemini({"value": "4"}))


# ---------- AI drafts and assumptions ----------

DRAFT = {"offering": "A fully leased industrial park with 12 units and 154,600 SF of space offered for sale today.",
         "upside": ["Leases roll over the next few years", "In-place rents can move to market"],
         "location_building": ["Three buildings", "Dock-high loading"],
         "rare": ["Fully leased small-bay industrial is hard to find"],
         "location": "Close to major roads and a large regional workforce, based only on the research a person accepted for this test."}


class TestDraftAllText(DbCase):
    def draft(self, reply, deal="fallowmere"):
        fake = FakeGemini(reply)
        result = om_drafting.draft_all_text(self.deals[deal], self.facts(deal), self.state(deal), USER, fake, self.db_path)
        return result, fake

    def test_one_request_saves_ai_drafts_that_wait_for_approval(self):
        result, fake = self.draft(DRAFT)
        self.assertEqual(fake.calls, 1)
        self.assertEqual(set(result["saved"]), {"The Offering", "Highlights: immediate upside",
                                                "Highlights: location and building", "Highlights: rare opportunity"})
        state = self.state()
        self.assertEqual(state.slots["offering.narrative"].status, "ai-draft")
        self.assertEqual(state.slots["highlights.upside"].value, DRAFT["upside"])
        self.assertFalse(state.slots["offering.narrative"].approved)

    def test_without_accepted_research_the_location_becomes_a_question(self):
        result, _ = self.draft(DRAFT)
        self.assertEqual(self.state().slots["location.narrative"].status, "empty")
        self.assertIn("No accepted research", result["questions"][0])

    def test_with_accepted_research_the_location_is_drafted(self):
        conn = db.get_connection(self.db_path)
        with conn:
            conn.execute("INSERT INTO research_findings (deal_id, topic, summary, sources, status, simulated) "
                         "VALUES (?, 'Demand', 'Large regional workforce near major roads (test).', '[]', 'accepted', 0)",
                         (self.deals["fallowmere"],))
        conn.close()
        result, fake = self.draft(DRAFT)
        self.assertIn("Location overview", result["saved"])
        self.assertIn("Large regional workforce", str(fake.prompts[0]))

    def test_simulated_research_is_never_used(self):
        conn = db.get_connection(self.db_path)
        with conn:
            conn.execute("INSERT INTO research_findings (deal_id, topic, summary, sources, status, simulated) "
                         "VALUES (?, 'Demand', 'SIMULATED demo finding.', '[]', 'accepted', 1)", (self.deals["fallowmere"],))
        conn.close()
        result, fake = self.draft(DRAFT)
        self.assertNotIn("SIMULATED demo finding", str(fake.prompts[0]))
        self.assertNotIn("Location overview", result["saved"])

    def test_a_piece_with_a_made_up_number_is_dropped(self):
        result, _ = self.draft(dict(DRAFT, offering="A park with 14 units offered at an 8% return for buyers seeking yield."))
        self.assertNotIn("The Offering", result["saved"])
        self.assertIn("The Offering: not saved", result["dropped"][0])
        self.assertEqual(self.state().slots["offering.narrative"].status, "empty")

    def test_a_persons_own_text_and_approved_text_are_never_replaced(self):
        om_slots.set_value(self.deals["fallowmere"], "offering.narrative", "My own words about this park, " * 4, USER,
                           db_path=self.db_path)
        result, _ = self.draft(DRAFT)
        self.assertIn("The Offering", result["skipped"])
        self.assertTrue(self.state().slots["offering.narrative"].value.startswith("My own words"))

    def test_nothing_to_draft_uses_no_request(self):
        result, fake = self.draft(DRAFT, deal="brindlewick")
        self.assertEqual(fake.calls, 0)
        self.assertEqual(result["saved"], [])


class TestAssumptions(DbCase):
    REPLY = {"assumptions": [
        {"key": "market_rent_psf", "value": 9.25, "why": "Close to the in-place average."},
        {"key": "escalation_pct", "value": 3, "why": "Common in the leases."},
        {"key": "occupancy_by_year", "value": [100, 95, 95, 95, 95], "why": "Fully leased now."},
        {"key": "expense_growth_pct", "value": 3, "why": "No basis; a placeholder to check."},
        {"key": "vacancy_pct", "value": 150, "why": "Bad value."},
        {"key": "management_fee_pct", "value": 3, "why": "Matches the T-12 share."}]}

    def test_proposals_are_saved_as_proposed_and_never_used_until_approved(self):
        deal = self.deals["fallowmere"]
        fake = FakeGemini(self.REPLY)
        result = om_drafting.propose_assumptions(deal, self.facts(), USER, fake, self.db_path)
        self.assertEqual(fake.calls, 1)
        self.assertEqual(len(result["saved"]), 5)
        self.assertIn("Vacancy allowance", result["dropped"][0])
        facts = self.facts()
        self.assertTrue(all(a["status"] == "proposed" for a in facts["assumptions"].values()))
        self.assertIn("AI proposal", facts["assumptions"]["market_rent_psf"]["source"]["detail"])
        self.assertFalse(om_calc.cash_flow(facts).ready)
        for key in facts["assumptions"]:
            om_slots.approve_assumption(deal, key, USER, self.db_path)
        om_slots.set_assumption(deal, "vacancy_pct", "5", USER, db_path=self.db_path)
        self.assertTrue(om_calc.cash_flow(self.facts()).ready)

    def test_the_ai_is_never_asked_for_a_price(self):
        fake = FakeGemini(self.REPLY)
        om_drafting.propose_assumptions(self.deals["fallowmere"], self.facts(), USER, fake, self.db_path)
        self.assertIn("Never propose a price", fake.prompts[0])


# ---------- photos ----------

class TestPhotos(DbCase):
    def test_photos_are_checked_resized_and_saved_and_a_bad_file_never_stops_the_others(self):
        saved, problems = om_assets.add_photos(self.deals["quillhaven"], [
            ("front.png", png((4000, 3000))), ("notes.txt", b"hello"), ("broken.jpg", b"\xff\xd8 not really")], USER,
            db_path=self.db_path)
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(problems), 2)
        row = om_assets.assets(self.deals["quillhaven"], self.db_path)[0]
        with Image.open(om_assets.full_path(row["file_path"])) as image:
            self.assertEqual(max(image.size), om_assets.MAX_SIDE)

    def test_sort_proposes_kinds_with_one_request_per_batch_and_changes_nothing(self):
        deal = self.deals["quillhaven"]
        saved, _ = om_assets.add_photos(deal, [(f"p{i}.png", png()) for i in range(10)], USER, db_path=self.db_path)
        fake = FakeGemini({"photos": [{"index": i, "kind": "exterior", "description": "front"} for i in range(1, 9)]},
                          {"photos": [{"index": 1, "kind": "aerial", "description": "from above"},
                                      {"index": 2, "kind": "unsure", "description": "?"}]})
        proposals, requests = om_assets.sort_photos(deal, fake, self.db_path)
        self.assertEqual((requests, fake.calls, len(proposals)), (2, 2, 9))
        self.assertTrue(all(a["kind"] is None for a in om_assets.assets(deal, self.db_path)))
        om_assets.apply_kinds(deal, proposals, USER, self.db_path)
        kinds = [a["kind"] for a in om_assets.assets(deal, self.db_path)]
        self.assertEqual((kinds.count("exterior"), kinds.count("aerial"), kinds.count(None)), (8, 1, 1))

    def test_place_fills_slots_by_kind_and_the_count_shows_what_is_still_needed(self):
        deal = self.deals["quillhaven"]
        om_assets.add_photos(deal, [(f"e{i}.png", png()) for i in range(3)], USER, kind="exterior", db_path=self.db_path)
        om_assets.add_photos(deal, [("a.png", png())], USER, kind="aerial", db_path=self.db_path)
        placed = om_assets.auto_place(deal, USER, self.db_path)
        self.assertEqual(placed, 4)
        state = self.state("quillhaven")
        self.assertEqual(state.slots["photo.hero"].status, "broker-provided")
        self.assertEqual(state.slots["photo.highlights_aerial"].status, "broker-provided")
        needs = " ".join(om_assets.needs_summary(state))
        self.assertIn("Photo page: needs 4 more exterior or interior photos", needs)

    def test_a_photo_of_the_wrong_kind_is_refused_for_a_slot(self):
        deal = self.deals["quillhaven"]
        saved, _ = om_assets.add_photos(deal, [("inside.png", png())], USER, kind="interior", db_path=self.db_path)
        with self.assertRaisesRegex(ValueError, "aerial"):
            om_assets.place(deal, saved[0], "photo.highlights_aerial", USER, self.db_path)

    def test_missing_sample_drawings_are_drawn_again(self):
        rows = om_assets.assets(self.deals["brindlewick"], self.db_path)
        path = om_assets.full_path(rows[0]["file_path"])
        path.unlink()
        om_assets.ensure_sample_files(rows)
        self.assertTrue(path.exists())


# ---------- settings, logo, time, chat ----------

class TestSettingsAndLogo(DbCase):
    def test_the_logo_is_saved_outside_git_and_shown_on_the_cover(self):
        email = "demo.broker@example.com"
        self.assertIsNone(branding.logo_path(email))
        branding.save_logo(email, "logo.png", png((600, 200), (20, 60, 40)))
        facts = self.facts("brindlewick")
        self.assertEqual(facts["logo"], branding.logo_path(email))
        path = self.dir / "om.pptx"
        om_export.build_pptx(om_engine.build(facts), facts, "final", path)
        cover = Presentation(path).slides[0]
        self.assertEqual(sum(1 for s in cover.shapes if s.shape_type == 13), 2)  # the hero photo and the logo
        branding.remove_logo(email)
        self.assertIsNone(branding.logo_path(email))

    def test_a_bad_logo_is_refused(self):
        with self.assertRaises(ValueError):
            branding.save_logo("demo.broker@example.com", "logo.gif", b"GIF89a")

    def test_brindlewick_exports_client_ready(self):
        facts = self.facts("brindlewick")
        result = om_export.export(self.deals["brindlewick"], facts, "final", USER, want_pdf=False, db_path=self.db_path,
                                  out_dir=self.dir / "exports")
        self.assertEqual(result["pptx"].name, "Brindlewick_Retail_Row_SAMPLE_fictional_OM_v1_final.pptx")
        self.assertEqual(result["completion"], 100)


class TestTimeAndChat(DbCase):
    def test_time_counts_sessions_from_clicks_without_claiming_time_saved(self):
        start = datetime(2026, 10, 1, 9, 0)
        events = [{"created_at": (start + timedelta(minutes=m)).isoformat(sep=" ")} for m in (0, 4, 10, 90, 92)]
        self.assertEqual(om_engine.time_spent(events), (12, 2))
        self.assertEqual(om_engine.time_spent([]), (0, 0))

    def test_the_chat_can_answer_om_questions_from_the_checklist(self):
        data = qa.load_deal_data(self.deals["fallowmere"], self.db_path)
        context = qa.build_context(data)
        self.assertIn("OM completion: 55% approved", context)
        self.assertIn("Missing: The Offering", context)
        self.assertIn(qa.OM_SOURCE, qa.allowed_sources(data))

    def test_viewing_the_om_writes_nothing(self):
        import hashlib
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        for deal in self.deals:
            om_interview.questions(self.state(deal))
            qa.load_deal_data(self.deals[deal], self.db_path)
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
