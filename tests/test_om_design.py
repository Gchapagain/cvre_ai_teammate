"""The Editorial OM design (services/om_design.py): the template's slides, native PowerPoint objects only,
fonts and theme, draft and client-ready marks, table pagination, never-cropped photos and text that is too long.

No AI. Photos and data are made up in code.
"""

from pptx import Presentation
from pptx.enum.dml import MSO_LINE
from pptx.opc.constants import RELATIONSHIP_TYPE as RT

from services import om_design, om_engine, om_export, om_template
from tests.test_om import TEST_UNITS, facts
from tests.test_om_export import ExportCase, slide_texts

SLIDES = ["cover", "disclosures", "contents", "divider_exec", "offering", "highlights", "divider_property", "features",
          "site_plan", "photos", "divider_market", "location", "regional", "divider_financial", "pricing", "cash_flow",
          "divider_tenant", "rent_roll", "back_cover"]


def every_shape(path):
    for number, slide in enumerate(Presentation(path).slides, start=1):
        for shape in slide.shapes:
            yield number, shape


class TestTemplate(ExportCase):
    def test_the_editorial_template_lists_its_slides_and_layouts_in_order(self):
        template = om_template.load()
        self.assertEqual(template.id, "om_v2_editorial")
        self.assertEqual([s.id for s in template.slides], SLIDES)
        self.assertEqual({s.layout for s in template.slides} - set(om_design.LAYOUTS), {"rent_roll"})
        self.assertEqual([s["number"] for s in template.sections], ["I", "II", "III", "IV", "V"])
        self.assertTrue(all(s.get("description") for s in template.sections))


class TestNativeObjects(ExportCase):
    def test_every_word_is_editable_text_and_the_only_pictures_are_the_photos(self):
        data = self.complete_facts()
        path = self.build(data, "final")
        pictures = [shape for _, shape in every_shape(path) if shape.shape_type == 13]
        self.assertEqual(len(pictures), len([a for a in data["assets"] if a["slot_id"]]))  # no picture of text
        text = "\n".join(slide_texts(path))
        self.assertIn("Investment Highlights", text)
        self.assertIn("Tenant Rent Roll", text)
        tables = [shape for _, shape in every_shape(path) if shape.has_table]
        self.assertEqual(len(tables), 2)  # the cash flow and the rent roll are real tables

    def test_only_georgia_and_arial_and_nothing_below_the_type_scale(self):
        path = self.build(self.complete_facts())
        fonts, sizes = set(), set()
        for _, shape in every_shape(path):
            frames = [shape.text_frame] if shape.has_text_frame else []
            if shape.has_table:
                frames += [cell.text_frame for row in shape.table.rows for cell in row.cells]
            for frame in frames:
                for para in frame.paragraphs:
                    for run in para.runs:
                        if run.text.strip():
                            fonts.add(run.font.name)
                            sizes.add(run.font.size.pt)
        self.assertEqual(fonts, {"Georgia", "Arial"})
        self.assertGreaterEqual(min(sizes), om_design.SIZE["footer"])

    def test_the_theme_uses_georgia_arial_and_our_palette_and_there_are_no_animations(self):
        path = self.build(self.complete_facts())
        deck = Presentation(path)
        theme = deck.slide_master.part.part_related_by(RT.THEME).blob.decode()
        self.assertIn('typeface="Georgia"', theme)
        self.assertIn('typeface="Arial"', theme)
        self.assertIn(om_design.PALETTE["forest"], theme)
        for slide in deck.slides:
            xml = slide._element.xml
            self.assertNotIn("<p:transition", xml)
            self.assertNotIn("<p:timing", xml)

    def test_no_shape_carries_the_default_theme_shadow(self):
        path = self.build(self.complete_facts())
        self.assertFalse(any(shape._element.find("{http://schemas.openxmlformats.org/presentationml/2006/main}style")
                             is not None for _, shape in every_shape(path) if shape.shape_type in (1, 9)))


class TestDraftAndFinal(ExportCase):
    def test_a_draft_has_the_corner_tag_and_dashed_placeholders(self):
        path = self.build(facts())
        mark = om_template.boilerplate()["draft_mark"]
        self.assertTrue(all(mark in page for page in slide_texts(path)))
        dashed = [s for _, s in every_shape(path) if s.shape_type == 1 and s.line.fill.type is not None
                  and s.line.dash_style == MSO_LINE.DASH]
        self.assertTrue(dashed)
        self.assertIn("Needs: the sale price (broker)", "\n".join(slide_texts(path)))  # calculated: says what it needs

    def test_client_ready_has_no_tag_and_no_placeholders(self):
        path = self.build(self.complete_facts(), "final")
        text = "\n".join(slide_texts(path))
        self.assertNotIn(om_template.boilerplate()["draft_mark"], text)
        self.assertNotIn("Add photo", text)
        self.assertNotIn("Add text", text)
        dashed = [s for _, s in every_shape(path) if s.shape_type == 1 and s.line.fill.type is not None
                  and s.line.dash_style == MSO_LINE.DASH]
        self.assertEqual(dashed, [])


class TestTablesAndText(ExportCase):
    def long_roll(self, count=20):
        units = []
        for i in range(count):
            unit = dict(TEST_UNITS[i % len(TEST_UNITS)])
            unit["unit_number"] = str(i + 1)
            units.append(unit)
        return units

    def test_a_long_rent_roll_runs_on_with_its_header_and_one_totals_row(self):
        path = self.build(facts(units=self.long_roll()))
        pages = [p for p in slide_texts(path) if "Tenant Rent Roll" in p]
        self.assertEqual(len(pages), 2)
        self.assertIn("(continued)", pages[1])
        for page in pages:
            self.assertIn("Lease start", page)  # the header is repeated
        self.assertNotIn("Total", pages[0].split("Tenant Rent Roll", 1)[1].replace("Total SF", ""))
        self.assertIn("20 units", pages[1])

    def test_text_too_long_is_reported_and_blocks_the_client_ready_export_never_shrunk(self):
        data = self.complete_facts()
        data["rows"]["offering.narrative"] = {"value": "A made-up sentence about the property for the test. " * 40,
                                              "status": "approved", "source": {"kind": "broker_input", "detail": "Typed"}}
        state = om_engine.build(data)
        problems = dict(om_design.too_long(state))
        self.assertIn("offering.narrative", problems)
        self.assertIn("too long", problems["offering.narrative"])
        self.assertTrue(any("too long" in b for b in om_export.final_blockers(state)))

    def test_a_short_text_fits(self):
        self.assertEqual(om_design.too_long(om_engine.build(self.complete_facts())), [])


class TestPhotos(ExportCase):
    def test_section_openers_show_a_photo_only_when_the_broker_added_one(self):
        path = self.build(self.complete_facts(), "final")
        deck = Presentation(path)
        opener = deck.slides[3]  # I Executive Summary, no divider photo
        self.assertFalse([s for s in opener.shapes if s.shape_type == 13])
        self.assertNotIn("Add photo", "\n".join(s.text_frame.text for s in opener.shapes if s.has_text_frame))

    def test_justified_rows_show_every_photo_whole_inside_the_area(self):
        cells = om_design.justified([1.5, 0.7, 1.0], 1.0, 1.85, 9.4, 5.75)
        for x, y, w, h in cells:
            self.assertGreaterEqual(x, 1.0 - 1e-6)
            self.assertLessEqual(x + w, 10.4 + 1e-6)
            self.assertLessEqual(y + h, 1.85 + 5.75 + 1e-6)
        ratios = [(w - 2 * om_design.MAT) / (h - 2 * om_design.MAT - om_design.CAPTION) for _, _, w, h in cells]
        for got, want in zip(ratios, [1.5, 0.7, 1.0]):
            self.assertAlmostEqual(got, want, places=3)  # same shape as the photo: nothing cut
