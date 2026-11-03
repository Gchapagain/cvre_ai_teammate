"""Stage 1: crisp previews and photos that are never cropped unless the broker asks.

Previews are drawn from a PDF made in code (no LibreOffice needed). Photos are made in code. No AI. Fictional data only.
"""

import io
from unittest import mock

import pymupdf
from PIL import Image
from pptx import Presentation

from services import om_assets, om_export
from tests.test_om_builder import USER, png
from tests.test_slide_editor import SlideCase, jpeg

STONE = (231, 227, 218)


def letter_pdf(path):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=11 * 72, height=8.5 * 72)
        page.insert_text((72, 72), "Fictional test page", fontsize=24)
        pdf.save(path)
    return path


class TestCrispPreview(SlideCase):
    def test_pages_render_at_200_dpi_as_png_and_are_cached(self):
        with mock.patch.object(om_export, "EXPORT_DIR", self.dir / "exports"):
            pages = om_export.page_images(letter_pdf(self.dir / "page.pdf"))
            with Image.open(pages[0]) as image:
                self.assertGreaterEqual(image.width, 2000)
                self.assertEqual(image.format, "PNG")
            stamp = pages[0].stat().st_mtime_ns
            self.assertEqual(om_export.page_images(self.dir / "page.pdf")[0].stat().st_mtime_ns, stamp)  # drawn once

    def test_thumbnails_are_made_once_from_the_same_render(self):
        with mock.patch.object(om_export, "EXPORT_DIR", self.dir / "exports"):
            pages = om_export.page_images(letter_pdf(self.dir / "page.pdf"))
            thumbs = om_export.thumbnails(pages)
            with Image.open(thumbs[0]) as image:
                self.assertEqual(image.width, om_export.THUMB_WIDTH)
            stamp = thumbs[0].stat().st_mtime_ns
            self.assertEqual(om_export.thumbnails(pages)[0].stat().st_mtime_ns, stamp)


class TestOriginalsAndCopies(SlideCase):
    def test_the_original_upload_is_kept_untouched_and_the_copy_is_only_shrunk(self):
        deal = self.new_deal()
        big, small = jpeg((4000, 3000)), png((1200, 800))
        ids, _ = om_assets.add_photos(deal, [("big.jpg", big), ("small.png", small)], USER, db_path=self.db_path)
        rows = {a["id"]: a for a in om_assets.assets(deal, self.db_path)}
        for asset_id, data in zip(ids, (big, small)):
            self.assertEqual(om_assets.full_path(rows[asset_id]["original_path"]).read_bytes(), data)
        with Image.open(om_assets.full_path(rows[ids[0]]["file_path"])) as copy:
            self.assertEqual((copy.size, copy.format), ((2400, 1800), "JPEG"))
        with Image.open(om_assets.full_path(rows[ids[1]]["file_path"])) as copy:
            self.assertEqual((copy.size, copy.format), ((1200, 800), "PNG"))  # never enlarged; a graphic stays PNG

    def test_a_large_powerpoint_gets_a_plain_warning(self):
        path = self.dir / "deck.pptx"
        path.write_bytes(b"x" * 2048)
        self.assertIsNone(om_export.size_warning(path))
        with mock.patch.object(om_export, "LARGE_FILE_MB", 0.001):
            self.assertIn("large to email", om_export.size_warning(path))


class TestNeverCroppedByDefault(SlideCase):
    def picture(self, deal, fit=None, size=(900, 1600)):
        asset = om_assets.add_to_slot(deal, "photo.hero", "tall.jpg", jpeg(size), USER, db_path=self.db_path)
        if fit:
            om_assets.set_fit(deal, asset, fit, USER, db_path=self.db_path)
        out = self.dir / "deck.pptx"
        from app import queries
        from services import om_engine
        facts = queries.om_facts(deal)
        om_export.build_pptx(om_engine.build(facts), facts, "draft", out)
        cover = Presentation(out).slides[0]
        return next(shape for shape in cover.shapes if shape.shape_type == 13)  # the photo

    def test_a_portrait_photo_is_shown_whole(self):
        pic = self.picture(self.new_deal())
        self.assertEqual((pic.crop_left, pic.crop_right, pic.crop_top, pic.crop_bottom), (0, 0, 0, 0))
        self.assertAlmostEqual(pic.width / pic.height, 900 / 1600, places=2)

    def test_fill_crops_only_when_the_broker_chose_it(self):
        pic = self.picture(self.new_deal(), fit="fill", size=(1600, 900))
        self.assertGreater(pic.crop_left + pic.crop_right + pic.crop_top + pic.crop_bottom, 0)

    def test_the_editor_preview_shows_the_whole_photo_on_the_backing(self):
        tall = io.BytesIO(jpeg((900, 1600), colour=(20, 60, 40)))
        with Image.open(io.BytesIO(om_assets.preview(tall, 16 / 9))) as frame:
            self.assertEqual(frame.getpixel((5, frame.height // 2)), STONE)  # the sides are backing, not photo
            self.assertNotEqual(frame.getpixel((frame.width // 2, frame.height // 2)), STONE)
        tall.seek(0)
        with Image.open(io.BytesIO(om_assets.preview(tall, 16 / 9, fit="fill"))) as frame:
            self.assertNotEqual(frame.getpixel((5, frame.height // 2)), STONE)  # Fill: photo to the edges

    def test_fit_takes_only_whole_or_fill(self):
        deal = self.new_deal()
        asset = om_assets.add_to_slot(deal, "photo.hero", "a.jpg", jpeg(), USER, db_path=self.db_path)
        with self.assertRaises(ValueError):
            om_assets.set_fit(deal, asset, "stretch", USER, db_path=self.db_path)


class TestResolutionChip(SlideCase):
    def test_low_resolution_is_flagged_for_the_frame_size_but_never_blocked(self):
        frame = (6.4, 8.5)  # the cover photo frame, inches
        self.assertEqual(om_assets.resolution((2400, 1800), frame)[0], "Good")
        label, dpi = om_assets.resolution((480, 360), frame)
        self.assertEqual(label, "Low resolution")
        self.assertLess(dpi, om_assets.GOOD_DPI)
        deal = self.new_deal()
        om_assets.add_to_slot(deal, "photo.hero", "small.png", png((480, 360)), USER, db_path=self.db_path)  # still allowed
        self.assertEqual(self.state_of(deal).slots["photo.hero"].status, "broker-provided")

    def test_filling_a_frame_needs_more_pixels_than_showing_the_photo_whole(self):
        whole = om_assets.resolution((1600, 900), (6.4, 8.5), "whole")[1]
        fill = om_assets.resolution((1600, 900), (6.4, 8.5), "fill")[1]
        self.assertLess(fill, whole)


class TestThumbnailsStayThumbnails(SlideCase):
    def test_pages_never_include_their_thumbnails(self):
        with mock.patch.object(om_export, "EXPORT_DIR", self.dir / "exports"):
            pdf = letter_pdf(self.dir / "page.pdf")
            for _ in range(3):
                pages = om_export.page_images(pdf)
                om_export.thumbnails(pages, width=180)
                om_export.thumbnails(pages)
            self.assertEqual([p.name for p in om_export.page_images(pdf)], ["page-01.png"])


class TestPreviewCacheKey(SlideCase):
    def test_the_preview_is_redrawn_when_a_photo_fit_or_the_design_changes(self):
        deal = self.new_deal()
        asset = om_assets.add_to_slot(deal, "photo.hero", "a.jpg", jpeg(), USER, db_path=self.db_path)
        from app import queries
        from services import om_engine
        key = lambda: om_export._state_key(om_engine.build(queries.om_facts(deal)), queries.om_facts(deal))
        before = key()
        om_assets.set_fit(deal, asset, "fill", USER, db_path=self.db_path)
        self.assertNotEqual(key(), before)
        after_fit = key()
        with mock.patch.object(om_export, "design_fingerprint", return_value="a-new-design"):
            self.assertNotEqual(key(), after_fit)
