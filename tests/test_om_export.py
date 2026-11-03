"""Tests for the OM export (PowerPoint master, PDF made from it). No Gemini calls. Fictional data only.

The PDF test runs only where LibreOffice is installed; everything else checks the PowerPoint itself.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image
from pptx import Presentation

import db
import seed
from services import om_calc, om_engine, om_export, om_template
from tests.test_om import APPROVED_ASSUMPTIONS, TEST_UNITS, USER, facts

ANSWERS = {
    "property.address": "12 Imaginary Lane", "property.city_state": "Springfield, IL", "property.buildings": 1,
    "property.land_size": 2.5, "property.year_built": "1998 / 2019",
    "offering.narrative": "A made-up flex building offered for the test. " * 3,
    "highlights.upside": ["Made-up point one", "Made-up point two"],
    "highlights.location_building": ["Made-up point three", "Made-up point four"],
    "highlights.rare": ["Made-up point five"],
    "location.narrative": "A made-up location for the test, close to made-up roads and made-up demand. " * 2,
    "financial.sale_price": 2_400_000.0,
}


def slide_texts(path):
    """Every piece of text on each slide (text boxes, shapes and table cells)."""
    pages = []
    for slide in Presentation(path).slides:
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                texts.append(shape.text_frame.text)
            if shape.has_table:
                texts += [cell.text for row in shape.table.rows for cell in row.cells]
        pages.append("\n".join(texts))
    return pages


class ExportCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def photos(self):
        """One made-up PNG per photo the template needs."""
        assets, number = [], 0
        for slot in om_template.load().slots.values():
            if slot.type != "photo" or not slot.required:
                continue
            for position in range(slot.count):
                number += 1
                path = self.dir / f"photo_{number}.png"
                Image.new("RGB", (300, 200), (120, 150, 170)).save(path)
                assets.append({"id": number, "file_path": str(path), "kind": slot.photo_kinds[0], "slot_id": slot.id,
                               "position": position, "sample": 1})
        return assets

    def complete_facts(self, **changes):
        """Every required slot filled and approved, the way a person would leave a finished OM."""
        rows = {slot_id: {"value": value, "status": "broker-provided", "source": {"kind": "broker_input", "detail": "Typed"}}
                for slot_id, value in ANSWERS.items()}
        data = facts(rows=rows, assets=self.photos(), assumptions=APPROVED_ASSUMPTIONS, price=ANSWERS["financial.sale_price"])
        data.update(changes)
        for state in om_engine.build(data).waiting():
            data["rows"][state.slot.id] = {"value": state.value, "status": "approved", "source": state.source}
        return data

    def build(self, data, kind="draft"):
        path = self.dir / f"om_{kind}.pptx"
        om_export.build_pptx(om_engine.build(data), data, kind, path)
        return path


class TestDraft(ExportCase):
    def test_a_draft_always_builds_with_the_draft_mark_on_every_slide(self):
        pages = slide_texts(self.build(facts()))
        self.assertEqual(len(pages), 18)
        mark = om_template.boilerplate()["draft_mark"]
        self.assertTrue(all(mark in page for page in pages))

    def test_empty_slots_are_dashed_placeholders_that_name_what_to_add(self):
        path = self.build(facts())
        text = "\n".join(slide_texts(path))
        self.assertIn("Add photo: exterior or aerial", text)
        self.assertIn("Add: Sale price", text)
        from pptx.enum.dml import MSO_LINE
        dashed = [shape for shape in Presentation(path).slides[0].shapes
                  if shape.shape_type == 1 and shape.line.fill.type is not None and shape.line.dash_style == MSO_LINE.DASH]
        self.assertTrue(dashed)  # a dashed outline, no fill, no shadow

    def test_numbers_on_the_slides_are_the_calculated_ones(self):
        data = facts(assumptions=APPROVED_ASSUMPTIONS, price=2_400_000.0,
                     rows={"financial.sale_price": {"value": 2_400_000.0, "status": "broker-provided",
                                                    "source": {"kind": "broker_input"}}})
        text = "\n".join(slide_texts(self.build(data)))
        for calc in (om_calc.total_sf(data), om_calc.price_per_sf(data), om_calc.cap_rate(data, 4), om_calc.leased_pct(data)):
            self.assertIn(calc.display, text)
        self.assertIn("$2,400,000", text)
        noi = dict(om_calc.cash_flow(data).value)["Net operating income"]
        self.assertIn(om_calc.money(noi[5]), text)

    def test_the_fixed_disclosures_appear_word_for_word(self):
        text = "\n".join(slide_texts(self.build(facts())))
        for paragraph in om_template.boilerplate()["legal"]:
            self.assertIn(paragraph, text)
            self.assertTrue(paragraph.startswith("PLACEHOLDER"))
        self.assertIn("Replace with CBRE-approved legal text", text)

    def test_optional_items_that_are_unknown_are_left_off(self):
        text = "\n".join(slide_texts(self.build(facts())))
        self.assertNotIn("Bay doors", text)
        self.assertNotIn("Clear height", text)

    def test_the_footer_names_the_property_and_city_with_page_numbers(self):
        data = facts(rows={"property.city_state": {"value": "Springfield, IL", "status": "broker-provided",
                                                   "source": {"kind": "broker_input"}}})
        pages = slide_texts(self.build(data))
        self.assertIn("Larkmoor Flex Court (test - fictional) | Springfield, IL", pages[1])
        self.assertIn("\n2\n", f"\n{pages[1]}\n")
        self.assertIn("\n18\n", f"\n{pages[17]}\n")

    def test_slides_are_letter_landscape(self):
        deck = Presentation(self.build(facts()))
        self.assertEqual((deck.slide_width.inches, deck.slide_height.inches), (11, 8.5))

    def test_a_long_rent_roll_continues_on_the_next_slide(self):
        units = [dict(TEST_UNITS[0], unit_number=str(n)) for n in range(1, 21)]
        pages = slide_texts(self.build(facts(units=units)))
        self.assertEqual(len(pages), 19)
        self.assertIn("Tenant Rent Roll (continued)", "\n".join(pages))

    def test_zero_shows_as_a_dash_and_negatives_in_brackets(self):
        self.assertEqual(om_export._money_cell(-0.0, "Vacancy allowance"), "-")
        self.assertEqual(om_export._money_cell(-1200, "Vacancy allowance"), "($1,200)")
        self.assertEqual(om_export._money_cell(95, "Occupancy %"), "95.0%")


class TestFinal(ExportCase):
    def test_final_is_refused_until_everything_is_approved(self):
        path = self.dir / "final.pptx"
        with self.assertRaises(om_export.ExportError) as caught:
            om_export.build_pptx(om_engine.build(facts()), facts(), "final", path)
        self.assertIn("100% approved", str(caught.exception))
        self.assertFalse(path.exists())

    def test_a_finished_om_exports_clean_with_no_draft_mark_or_missing_box(self):
        data = self.complete_facts()
        self.assertEqual(om_engine.build(data).percent, 100)
        self.assertEqual(om_export.final_blockers(om_engine.build(data)), [])
        text = "\n".join(slide_texts(self.build(data, "final")))
        self.assertNotIn("MISSING", text)
        self.assertNotIn(om_template.boilerplate()["draft_mark"], text)
        self.assertIn("12 Imaginary Lane", text)

    def test_an_approved_number_that_changes_blocks_the_final_again(self):
        data = self.complete_facts()
        data["price"] = 2_500_000.0
        data["rows"]["financial.sale_price"] = {"value": 2_500_000.0, "status": "broker-provided",
                                               "source": {"kind": "broker_input"}}
        blockers = om_export.final_blockers(om_engine.build(data))
        self.assertIn("Sale price needs your approval", blockers)
        self.assertIn("Price per SF needs your approval", blockers)


class TestExportFiles(ExportCase):
    def setUp(self):
        super().setUp()
        self.db_path = self.dir / "om.db"
        self.deals = seed.seed(self.db_path)
        patcher = mock.patch.object(db, "DB_PATH", self.db_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def export(self, **kwargs):
        from app import queries
        deal_id = self.deals["fallowmere"]
        return om_export.export(deal_id, queries.om_facts(deal_id), "draft", USER, db_path=self.db_path,
                                out_dir=self.dir / "exports", **kwargs)

    def test_files_are_named_by_deal_version_and_kind_and_logged(self):
        with mock.patch.object(om_export, "to_pdf", side_effect=om_export.ExportError("no PDF here")):
            first, second = self.export(), self.export()
        self.assertEqual(first["pptx"].name, "Fallowmere_Industrial_Park_SAMPLE_fictional_OM_v1_draft.pptx")
        self.assertEqual(second["version"], 2)
        conn = db.get_connection(self.db_path)
        rows = [dict(r) for r in conn.execute("SELECT * FROM om_exports ORDER BY id")]
        events = conn.execute("SELECT COUNT(*) FROM om_events WHERE action = 'export'").fetchone()[0]
        conn.close()
        self.assertEqual([(r["version"], r["kind"], r["format"]) for r in rows], [(1, "draft", "pptx"), (2, "draft", "pptx")])
        self.assertEqual(rows[0]["created_by"], USER)
        self.assertTrue(json.loads(rows[0]["unapproved"]))
        self.assertEqual(events, 2)

    def test_without_libreoffice_the_powerpoint_is_still_made_and_the_reason_is_plain(self):
        with mock.patch.object(om_export, "soffice_path", return_value=None):
            result = self.export()
        self.assertTrue(result["pptx"].exists())
        self.assertIsNone(result["pdf"])
        self.assertIn("PDF needs LibreOffice", result["pdf_error"])

    @unittest.skipUnless(om_export.soffice_path(), "LibreOffice is not installed")
    def test_the_pdf_is_made_from_the_powerpoint_with_one_page_per_slide(self):
        import pymupdf
        result = self.export()
        self.assertTrue(result["pdf"].exists())
        with pymupdf.open(result["pdf"]) as pdf:
            self.assertEqual(pdf.page_count, result["slides"])
            self.assertAlmostEqual(pdf[0].rect.width / 72, 11, places=1)
            self.assertIn("DRAFT - NOT FOR DISTRIBUTION", pdf[0].get_text())


class TestPreviews(ExportCase):
    def test_page_previews_are_drawn_once_and_cached(self):
        import pymupdf
        pdf_path = self.dir / "tiny.pdf"
        with pymupdf.open() as pdf:
            pdf.new_page(width=792, height=612).insert_text((72, 72), "Made-up page")
            pdf.save(pdf_path)
        with mock.patch.object(om_export, "EXPORT_DIR", self.dir / "exports"):
            first = om_export.page_images(pdf_path, zoom=0.5)
            with mock.patch("pymupdf.open", side_effect=AssertionError("should use the cache")):
                second = om_export.page_images(pdf_path, zoom=0.5)
        self.assertEqual(len(first), 1)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
