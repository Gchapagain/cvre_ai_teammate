"""The OM slide-by-slide editor: slides in the template's order, plain-words needs, photo slots (upload, camera,
replace, remove, choose), the cover crop, "Draft with AI" for one slide and the folded bulk upload.

Gemini is always simulated (FakeGemini counts requests). The camera is simulated with a JPEG made in code.
Fictional data only.
"""

import io
from unittest import mock

from PIL import Image

import db
from services import deals, om_assets, om_drafting, om_export, om_slides, om_template
from tests.test_om_builder import DRAFT, USER, DbCase, FakeGemini, png


def jpeg(size=(1200, 900), colour=(90, 120, 100)):
    """What st.camera_input hands over: a JPEG picture."""
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "JPEG")
    return out.getvalue()


class SlideCase(DbCase):
    def new_deal(self, name="Larkspur Yard (test)"):
        return deals.quick_create(name, db_path=self.db_path)[0]

    def state_of(self, deal_id):
        from app import queries
        from services import om_engine
        return om_engine.build(queries.om_facts(deal_id))

    def table(self, sql, params=()):
        conn = db.get_connection(self.db_path)
        try:
            return [dict(r) for r in conn.execute(sql, params)]
        finally:
            conn.close()


class TestSlideList(SlideCase):
    def test_slides_come_from_the_template_in_its_order(self):
        rows = om_slides.rows(self.state())
        template = [s.id for s in om_template.load().slides if not s.only_if_filled]
        self.assertEqual([r.slide.id for r in rows], template)
        self.assertEqual([r.number for r in rows], list(range(1, len(rows) + 1)))
        self.assertEqual(rows[0].slide.title, "Cover")

    def test_a_new_deals_cover_says_in_plain_words_what_it_needs(self):
        state = self.state_of(self.new_deal())
        cover = om_slides.rows(state)[0]
        line = om_slides.needs_line(cover.number, cover.slide, state)
        self.assertTrue(line.startswith("Slide 1 - Cover: "), line)
        self.assertIn("add 1 photo (cover photo: exterior or aerial)", line)
        self.assertIn("write street address", line)
        self.assertEqual(cover.colour, "red")
        self.assertEqual(cover.badges, ["needs text", "needs a photo"])
        self.assertNotIn("cover.title", [i.slot.id for i in cover.items])  # fixed wording is not shown to fill

    def test_text_slides_offer_draft_with_ai_and_number_slides_do_not(self):
        rows = {r.slide.id: r for r in om_slides.rows(self.state())}
        self.assertTrue(any(om_slides.can_draft(i) for i in rows["offering"].items))
        self.assertFalse(any(om_slides.can_draft(i) for i in rows["pricing"].items))
        self.assertIn("needs numbers", om_slides.badges(self.state(), rows["pricing"].slide))  # no price yet

    def test_draft_with_ai_writes_only_that_slides_text_with_one_request(self):
        fake = FakeGemini(DRAFT)
        result = om_drafting.draft_all_text(self.deals["fallowmere"], self.facts(), self.state(), USER, client=fake,
                                            db_path=self.db_path, only={"offering.narrative", "photo.offering"})
        self.assertEqual(fake.calls, 1)
        self.assertEqual(result["saved"], ["The Offering"])
        state = self.state()
        self.assertEqual(state.slots["offering.narrative"].status, "ai-draft")
        self.assertEqual(state.slots["highlights.upside"].status, "empty")  # another slide: untouched


class TestPhotoSlots(SlideCase):
    def test_an_upload_and_a_camera_photo_fill_a_slot_and_wait_for_approval(self):
        deal = self.new_deal()
        om_assets.add_to_slot(deal, "photo.hero", "front.png", png(), USER, db_path=self.db_path)
        hero = self.state_of(deal).slots["photo.hero"]
        self.assertEqual((hero.status, len(hero.photos)), ("broker-provided", 1))
        self.assertEqual(hero.photos[0]["kind"], "exterior")  # the slot's own kind: no sorting step
        om_assets.add_to_slot(deal, "photo.offering", "camera-photo.jpg", jpeg(), USER, db_path=self.db_path)
        om_assets.add_to_slot(deal, "photo.offering", "camera-photo.jpg", jpeg(colour=(10, 20, 30)), USER, db_path=self.db_path)
        offering = self.state_of(deal).slots["photo.offering"]
        self.assertEqual((offering.status, len(offering.photos)), ("broker-provided", 2))

    def test_a_full_slot_asks_to_replace_or_remove_first(self):
        deal = self.new_deal()
        om_assets.add_to_slot(deal, "photo.hero", "one.png", png(), USER, db_path=self.db_path)
        with self.assertRaisesRegex(ValueError, "Replace or remove one first"):
            om_assets.add_to_slot(deal, "photo.hero", "two.png", png(), USER, db_path=self.db_path)

    def test_replace_swaps_the_photo_and_keeps_the_old_one_in_the_deal(self):
        deal = self.new_deal()
        old = om_assets.add_to_slot(deal, "photo.hero", "old.png", png(), USER, db_path=self.db_path)
        new = om_assets.add_to_slot(deal, "photo.hero", "new.jpg", jpeg(), USER, replace_id=old, db_path=self.db_path)
        hero = self.state_of(deal).slots["photo.hero"]
        self.assertEqual([a["id"] for a in hero.photos], [new])
        kept = {a["id"]: a["slot_id"] for a in om_assets.assets(deal, self.db_path)}
        self.assertEqual(kept, {old: None, new: "photo.hero"})

    def test_remove_takes_it_off_the_slide_and_choose_puts_it_back(self):
        deal = self.new_deal()
        photo = om_assets.add_to_slot(deal, "photo.hero", "front.png", png(), USER, db_path=self.db_path)
        om_assets.take_off_slot(deal, photo, USER, db_path=self.db_path)
        self.assertEqual(self.state_of(deal).slots["photo.hero"].status, "empty")
        om_assets.use_on_slot(deal, "photo.site_plan", photo, USER, db_path=self.db_path)
        site = self.state_of(deal).slots["photo.site_plan"]
        self.assertEqual(len(site.photos), 1)
        self.assertEqual(site.photos[0]["kind"], "site_plan")  # the broker chose the slot: it takes the slot's kind

    def test_a_file_that_is_not_a_picture_is_refused_and_nothing_is_placed(self):
        deal = self.new_deal()
        with self.assertRaisesRegex(ValueError, "not a readable picture"):
            om_assets.add_to_slot(deal, "photo.hero", "fake.jpg", b"not a picture", USER, db_path=self.db_path)
        self.assertEqual(om_assets.assets(deal, self.db_path), [])

    def test_only_photo_slots_take_photos(self):
        with self.assertRaisesRegex(ValueError, "not a photo slot"):
            om_assets.add_to_slot(self.new_deal(), "offering.narrative", "x.png", png(), USER, db_path=self.db_path)

    def test_the_preview_is_cut_to_the_frame_the_slide_uses(self):
        cover = om_template.load().slots["photo.hero"]
        ratio = om_export.photo_ratio("cover", cover)
        self.assertAlmostEqual(ratio, (11 - 4.6) / 8.5)
        grid = om_template.load().slots["photo.grid"]
        self.assertAlmostEqual(om_export.photo_ratio("photo_grid", grid), ((9.8 - 0.15) / 2) / ((6.05 - 0.15) / 2))
        with Image.open(io.BytesIO(om_assets.cover_crop(io.BytesIO(png((1600, 900))), ratio))) as image:
            self.assertAlmostEqual(image.width / image.height, ratio, places=2)


class TestManyPhotosAtOnce(SlideCase):
    def test_the_plan_saves_nothing_and_place_them_follows_it(self):
        deal = self.new_deal()
        ids, _ = om_assets.add_photos(deal, [("a.png", png()), ("b.png", png(colour=(1, 2, 3)))], USER, db_path=self.db_path)
        fake = FakeGemini({"photos": [{"index": 1, "kind": "aerial", "description": "from above"},
                                      {"index": 2, "kind": "exterior", "description": "front"}]})
        proposals, requests = om_assets.sort_photos(deal, client=fake, db_path=self.db_path)
        self.assertEqual((requests, fake.calls), (1, 1))
        before = om_assets.assets(deal, self.db_path)
        plan = om_assets.plan_placement(deal, proposals, self.db_path)
        self.assertEqual(om_assets.assets(deal, self.db_path), before)  # proposing never writes
        # The cover prefers an exterior shot, so the aerial goes to the highlights' aerial slot.
        self.assertEqual({p["asset_id"]: p["slot_id"] for p in plan}, {ids[0]: "photo.highlights_aerial", ids[1]: "photo.hero"})
        self.assertEqual(om_assets.apply_plan(deal, plan, USER, self.db_path), 2)
        placed = {a["id"]: (a["kind"], a["slot_id"]) for a in om_assets.assets(deal, self.db_path)}
        self.assertEqual(placed, {ids[0]: ("aerial", "photo.highlights_aerial"), ids[1]: ("exterior", "photo.hero")})


class TestNoAiWithoutAClick(SlideCase):
    def test_photos_and_slots_never_call_gemini(self):
        deal = self.new_deal()
        with mock.patch("services.gemini.generate", side_effect=AssertionError("Gemini was called")):
            photo = om_assets.add_to_slot(deal, "photo.hero", "camera-photo.jpg", jpeg(), USER, db_path=self.db_path)
            om_assets.take_off_slot(deal, photo, USER, db_path=self.db_path)
            om_assets.use_on_slot(deal, "photo.hero", photo, USER, db_path=self.db_path)
            om_slides.rows(self.state_of(deal))
        events = [e["action"] for e in self.table("SELECT action FROM om_events WHERE deal_id = ?", (deal,))]
        self.assertEqual(events.count("photo_placed"), 2)  # every photo action is in the OM's "Every update" log
        self.assertIn("photo_unplaced", events)
