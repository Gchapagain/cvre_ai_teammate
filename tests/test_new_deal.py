"""Tests for creating deals from uploads and from a description. Gemini is always simulated."""

import csv
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import db
import seed
from services import deals, gemini, new_deal, validation
from tests.test_extraction import (FIELDS, RENT_ROLL, daily_quota_error, fake_client, forbidden_client,
                                   read_source_units)

T12 = seed.T12_FILE


def draft_client(reply, calls=None):
    """A stand-in Gemini client for drafting: replies with the given dict, text or error."""
    def generate_content(**kwargs):
        if calls is not None:
            calls.append(kwargs["contents"])
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(text=reply if isinstance(reply, str) else json.dumps(reply))
    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


class NewDealTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "deals.db"
        self.uploads = Path(self.tmp.name) / "uploads"
        db.init_db(self.db_path)
        self.source = read_source_units()

    def rows(self, sql, params=()):
        conn = db.get_connection(self.db_path)
        result = [dict(row) for row in conn.execute(sql, params)]
        conn.close()
        return result

    def upload(self, files, client, name="Made-up Depot (test)"):
        return new_deal.create_from_uploads(name, "Industrial", "Testville", files, client=client,
                                            db_path=self.db_path, upload_dir=self.uploads)

    def rent_roll_csv(self):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Unit", "Tenant", "SF", "Lease Start", "Lease End",
                         "Monthly Base Rent", "Annual Base Rent", "Rent / SF (Annual)", "Lease Type"])
        writer.writerows([[unit[f] for f in FIELDS] for unit in self.source])
        return buffer.getvalue().encode()


class TestDealWrites(NewDealTestCase):
    def test_create_deal_saves_what_it_was_given(self):
        deal_id = deals.create_deal("  Made-up Tower  ", "Office", " Testville ", db_path=self.db_path)
        self.assertEqual(self.rows("SELECT name, property_type, submarket, status FROM deals WHERE id = ?", (deal_id,)),
                         [{"name": "Made-up Tower", "property_type": "Office", "submarket": "Testville", "status": "New"}])

    def test_blank_fields_are_stored_as_empty_not_guessed(self):
        deal_id = deals.create_deal("Made-up Tower", None, "", db_path=self.db_path)
        row = self.rows("SELECT property_type, submarket, address FROM deals WHERE id = ?", (deal_id,))[0]
        self.assertEqual(row, {"property_type": None, "submarket": None, "address": None})

    def test_a_deal_needs_a_name(self):
        for name in ("", "   ", None):
            with self.assertRaises(ValueError):
                deals.create_deal(name, db_path=self.db_path)
        self.assertEqual(self.rows("SELECT id FROM deals"), [])

    def test_upload_is_saved_to_disk_and_recorded_as_received(self):
        deal_id = deals.create_deal("Made-up Tower", db_path=self.db_path)
        document_id, path = deals.save_upload(deal_id, "rent roll.xlsx", b"file bytes", self.db_path, self.uploads)
        self.assertEqual(path.read_bytes(), b"file bytes")
        self.assertEqual(path.parent, self.uploads / str(deal_id))
        document = self.rows("SELECT * FROM documents WHERE id = ?", (document_id,))[0]
        self.assertEqual((document["filename"], document["source"], document["status"], document["file_path"]),
                         ("rent roll.xlsx", "Upload", "Received", str(path)))

    def test_uploads_cannot_escape_their_folder_or_overwrite_each_other(self):
        deal_id = deals.create_deal("Made-up Tower", db_path=self.db_path)
        _, first = deals.save_upload(deal_id, "../../evil.xlsx", b"one", self.db_path, self.uploads)
        _, second = deals.save_upload(deal_id, "evil.xlsx", b"two", self.db_path, self.uploads)
        self.assertEqual(first.parent, self.uploads / str(deal_id))
        self.assertNotEqual(first, second)
        self.assertEqual((first.read_bytes(), second.read_bytes()), (b"one", b"two"))

    def test_notes_are_saved_exactly_and_must_have_a_valid_source(self):
        deal_id = deals.create_deal("Made-up Tower", db_path=self.db_path)
        deals.add_note(deal_id, "Owner wants to sell by Q2.\nRoof replaced 2024.", "Recording", self.db_path)
        deals.add_note(deal_id, "Typed one", "Typed", self.db_path)
        notes = self.rows("SELECT text, source FROM deal_notes ORDER BY id")
        self.assertEqual(notes, [{"text": "Owner wants to sell by Q2.\nRoof replaced 2024.", "source": "Recording"},
                                 {"text": "Typed one", "source": "Typed"}])
        for text, source in (("", "Typed"), ("   ", "Typed"), ("Fine", "Audio")):
            with self.assertRaises(ValueError):
                deals.add_note(deal_id, text, source, self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            deals.add_note(9999, "No such deal", "Typed", self.db_path)

    def test_deleting_a_deal_deletes_its_notes(self):
        deal_id = deals.create_deal("Made-up Tower", db_path=self.db_path)
        deals.add_note(deal_id, "A note", "Typed", self.db_path)
        conn = db.get_connection(self.db_path)
        with conn:
            conn.execute("DELETE FROM deals WHERE id = ?", (deal_id,))
        conn.close()
        self.assertEqual(self.rows("SELECT id FROM deal_notes"), [])


class TestClassify(NewDealTestCase):
    def test_sample_files(self):
        self.assertEqual(new_deal.classify(RENT_ROLL), new_deal.RENT_ROLL)
        self.assertEqual(new_deal.classify(T12), new_deal.T12)

    def test_csv_rent_roll_and_junk(self):
        rent_roll = Path(self.tmp.name) / "roll.csv"
        rent_roll.write_bytes(self.rent_roll_csv())
        junk = Path(self.tmp.name) / "junk.xlsx"
        junk.write_bytes(b"not a spreadsheet")
        notes = Path(self.tmp.name) / "notes.csv"
        notes.write_text("just,some,words\n1,2,3\n")
        self.assertEqual(new_deal.classify(rent_roll), new_deal.RENT_ROLL)
        self.assertEqual(new_deal.classify(junk), new_deal.UNKNOWN)
        self.assertEqual(new_deal.classify(notes), new_deal.UNKNOWN)


class TestCreateFromUploads(NewDealTestCase):
    def files(self, *paths):
        return [(path.name, path.read_bytes()) for path in paths]

    def test_rent_roll_and_t12_upload(self):
        messages = []
        result = new_deal.create_from_uploads(
            "Made-up Depot (test)", "Industrial", "Testville", self.files(RENT_ROLL, T12),
            client=fake_client(self.source), db_path=self.db_path, upload_dir=self.uploads, progress=messages.append)
        deal_id = result["deal_id"]
        self.assertEqual((result["read"], result["units_saved"], result["flags_raised"]), (True, 12, 1))
        self.assertEqual(self.rows("SELECT name, status FROM deals"), [{"name": "Made-up Depot (test)", "status": "Needs Review"}])
        documents = self.rows("SELECT filename, doc_type, source, status FROM documents ORDER BY id")
        self.assertEqual(documents, [
            {"filename": "rent_roll.xlsx", "doc_type": "Rent roll", "source": "Upload", "status": "Read"},
            {"filename": "t12.xlsx", "doc_type": "T-12", "source": "Upload", "status": "Received"},
        ])
        self.assertEqual([f["message"] for f in result["files"]], ["Read: 12 units, 1 flag.", new_deal.T12_NOT_BUILT])
        self.assertTrue((self.uploads / str(deal_id) / "rent_roll.xlsx").exists())
        self.assertTrue((self.uploads / str(deal_id) / "t12.xlsx").exists())
        self.assertEqual(self.rows("SELECT unit_number, rule FROM flags"),
                         [{"unit_number": "110", "rule": validation.RULE_RENT_OUTLIER}])
        self.assertEqual(self.rows("SELECT id FROM t12_line_items"), [])
        self.assertIn("Reading rent_roll.xlsx with the AI...", messages)

    def test_every_uploaded_rent_roll_value_is_saved_as_the_file_has_it(self):
        self.upload(self.files(RENT_ROLL), fake_client(self.source))
        saved = self.rows(f"SELECT {', '.join(FIELDS)} FROM rent_roll_units ORDER BY id")
        checked = 0
        for expected, actual in zip(self.source, saved, strict=True):
            for field_name in FIELDS:
                self.assertEqual(actual[field_name], expected[field_name])
                checked += 1
        self.assertEqual(checked, 108)

    def test_quota_used_up_still_creates_the_deal_and_keeps_the_file(self):
        with mock.patch.object(gemini.time, "sleep"):
            result = self.upload(self.files(RENT_ROLL), fake_client_error(daily_quota_error()))
        self.assertFalse(result["read"])
        self.assertIn("daily quota is used up", result["files"][0]["message"])
        self.assertTrue(result["files"][0]["message"].startswith("Saved, not read:"))
        self.assertNotIn("Nothing was saved", result["files"][0]["message"])
        self.assertEqual(self.rows("SELECT status FROM deals"), [{"status": "Extracting"}])
        self.assertEqual(self.rows("SELECT status FROM documents"), [{"status": "Received"}])
        self.assertEqual(self.rows("SELECT id FROM rent_roll_units"), [])
        self.assertTrue((self.uploads / str(result["deal_id"]) / "rent_roll.xlsx").exists())

    def test_a_bad_ai_reply_still_creates_the_deal(self):
        result = self.upload(self.files(RENT_ROLL), draft_client("Sure! Here you go"))
        self.assertFalse(result["read"])
        self.assertEqual(self.rows("SELECT status FROM documents"), [{"status": "Received"}])

    def test_t12_only_upload_never_calls_gemini(self):
        result = self.upload(self.files(T12), forbidden_client())
        self.assertFalse(result["read"])
        self.assertEqual(self.rows("SELECT doc_type, status FROM documents"), [{"doc_type": "T-12", "status": "Received"}])
        self.assertEqual(self.rows("SELECT status FROM deals"), [{"status": "Extracting"}])

    def test_only_the_first_rent_roll_is_read(self):
        calls = []
        client = draft_client({"units": self.source}, calls)
        result = self.upload([("a.xlsx", RENT_ROLL.read_bytes()), ("b.xlsx", RENT_ROLL.read_bytes())], client)
        self.assertEqual(len(calls), 1)
        self.assertEqual([f["message"] for f in result["files"]], ["Read: 12 units, 1 flag.", new_deal.ONE_RENT_ROLL])
        self.assertEqual(self.rows("SELECT filename, status FROM documents ORDER BY id"),
                         [{"filename": "a.xlsx", "status": "Read"}, {"filename": "b.xlsx", "status": "Received"}])

    def test_csv_rent_roll_is_read(self):
        result = self.upload([("roll.csv", self.rent_roll_csv())], fake_client(self.source))
        self.assertEqual((result["read"], result["units_saved"]), (True, 12))

    def test_unrecognised_file_is_kept_and_not_sent_to_gemini(self):
        result = self.upload([("holiday.xlsx", b"not a spreadsheet")], forbidden_client())
        self.assertEqual(result["files"][0]["message"], new_deal.NOT_RECOGNISED)
        self.assertEqual(self.rows("SELECT doc_type, status FROM documents"), [{"doc_type": None, "status": "Received"}])

    def test_a_deal_without_a_name_creates_nothing(self):
        with self.assertRaises(ValueError):
            self.upload(self.files(RENT_ROLL), forbidden_client(), name="  ")
        self.assertEqual(self.rows("SELECT id FROM deals"), [])
        self.assertFalse(self.uploads.exists())


def fake_client_error(error):
    return draft_client(error)


DESCRIPTION = "Oakmere Depot is a 40,000 sf warehouse in Fort Worth with three tenants. Roof was replaced in 2024."


class TestDraftFromDescription(NewDealTestCase):
    def draft(self, reply, description=DESCRIPTION, calls=None):
        return new_deal.draft_from_description(description, client=draft_client(reply, calls))

    def test_stated_facts_are_kept(self):
        draft = self.draft({"name": "Oakmere Depot", "property_type": "Industrial", "location": "Fort Worth",
                            "facts": ["40,000 sf warehouse.", "Three tenants.", "Roof replaced in 2024."]})
        self.assertEqual((draft.name, draft.property_type, draft.location), ("Oakmere Depot", "Industrial", "Fort Worth"))
        self.assertEqual(draft.facts, ["40,000 sf warehouse.", "Three tenants.", "Roof replaced in 2024."])
        self.assertEqual(draft.removed, [])

    def test_an_invented_name_or_location_is_left_blank(self):
        draft = self.draft({"name": "Fort Worth Logistics Center", "property_type": "Industrial",
                            "location": "Dallas-Fort Worth Metroplex", "facts": []})
        self.assertEqual((draft.name, draft.location), ("", ""))
        self.assertEqual(len(draft.removed), 2)

    def test_unknowns_stay_blank(self):
        draft = self.draft({"name": None, "property_type": None, "location": None, "facts": []},
                           description="Something on the east side, details to follow.")
        self.assertEqual((draft.name, draft.property_type, draft.location, draft.facts), ("", None, "", []))

    def test_a_fact_with_a_number_that_was_not_given_is_removed(self):
        draft = self.draft({"name": "Oakmere Depot", "property_type": "Industrial", "location": "Fort Worth",
                            "facts": ["40,000 sf warehouse.", "Rent is about $8.50 per SF.", "Built in 1998."]})
        self.assertEqual(draft.facts, ["40,000 sf warehouse."])
        self.assertEqual(len(draft.removed), 2)

    def test_a_property_type_outside_the_list_is_left_blank(self):
        draft = self.draft({"name": None, "property_type": "Warehouse", "location": None, "facts": []})
        self.assertIsNone(draft.property_type)

    def test_matching_ignores_case_and_spacing(self):
        draft = self.draft({"name": "oakmere  depot", "property_type": None, "location": "FORT WORTH", "facts": []})
        self.assertEqual((draft.name, draft.location), ("oakmere  depot", "FORT WORTH"))

    def test_prompt_holds_the_description_and_the_no_guessing_rule(self):
        calls = []
        self.draft({"name": None, "property_type": None, "location": None, "facts": []}, calls=calls)
        self.assertIn(DESCRIPTION, calls[0])
        self.assertIn("Never guess", calls[0])

    def test_empty_description_does_not_call_gemini(self):
        for text in ("", "   ", None):
            with self.assertRaises(ValueError):
                new_deal.draft_from_description(text, client=forbidden_client())

    def test_quota_and_bad_replies_raise_errors(self):
        with mock.patch.object(gemini.time, "sleep"):
            with self.assertRaises(gemini.GeminiQuotaError):
                self.draft(daily_quota_error())
        for bad in ("not json", '{"name": "x"}'):
            with self.assertRaises(gemini.GeminiError):
                self.draft(bad)

    def test_drafting_saves_nothing(self):
        before = self.db_path.read_bytes()
        self.draft({"name": "Oakmere Depot", "property_type": "Industrial", "location": "Fort Worth", "facts": ["Three tenants."]})
        self.assertEqual(self.db_path.read_bytes(), before)
        self.assertEqual(self.rows("SELECT id FROM deals"), [])


class TestCreateFromDraft(NewDealTestCase):
    def test_saves_the_checked_draft_and_its_notes(self):
        deal_id = new_deal.create_from_draft("Oakmere Depot", "Industrial", "Fort Worth", "Three tenants.\nRoof 2024.",
                                             self.db_path)
        self.assertEqual(self.rows("SELECT name, property_type, submarket, status FROM deals"),
                         [{"name": "Oakmere Depot", "property_type": "Industrial", "submarket": "Fort Worth", "status": "New"}])
        self.assertEqual(self.rows("SELECT deal_id, text, source FROM deal_notes"),
                         [{"deal_id": deal_id, "text": "Three tenants.\nRoof 2024.", "source": "Typed"}])

    def test_no_notes_means_no_note_row(self):
        new_deal.create_from_draft("Oakmere Depot", None, "", "  ", self.db_path)
        self.assertEqual(self.rows("SELECT id FROM deal_notes"), [])


if __name__ == "__main__":
    unittest.main()


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


class TestPhoto(NewDealTestCase):
    def setUp(self):
        super().setUp()
        self.deal_id = deals.create_deal("Photo Sample Deal (test)", db_path=self.db_path)

    def set_photo(self, filename, data):
        return deals.set_photo(self.deal_id, filename, data, db_path=self.db_path, upload_dir=self.uploads)

    def photo_path(self):
        return self.rows("SELECT photo_path FROM deals WHERE id = ?", (self.deal_id,))[0]["photo_path"]

    def test_a_new_deal_has_no_photo(self):
        self.assertIsNone(self.photo_path())

    def test_a_png_is_saved_and_the_deal_points_at_it(self):
        path = self.set_photo("front.png", PNG)
        self.assertEqual(path.read_bytes(), PNG)
        self.assertEqual(self.photo_path(), str(path))

    def test_a_second_photo_never_overwrites_the_first(self):
        first, second = self.set_photo("a.png", PNG), self.set_photo("b.jpg", JPEG)
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists())
        self.assertEqual(self.photo_path(), str(second))

    def test_refuses_other_types_fakes_and_large_files_and_saves_nothing(self):
        cases = {"rent_roll.xlsx": PNG, "drawing.svg": b"<svg/>", "fake.png": b"not really a picture",
                 "fake.jpg": PNG, "huge.png": PNG + b"\x00" * deals.PHOTO_MAX_BYTES}
        for filename, data in cases.items():
            with self.subTest(filename):
                with self.assertRaises(ValueError):
                    self.set_photo(filename, data)
        self.assertIsNone(self.photo_path())
        self.assertFalse((self.uploads / str(self.deal_id) / "photos").exists()
                         and any((self.uploads / str(self.deal_id) / "photos").iterdir()))


class TestPictures(unittest.TestCase):
    def test_each_illustrated_type_has_its_own_picture_and_others_share_one(self):
        from app import images
        for property_type, name in (("Industrial", "industrial"), ("Flex", "flex"), ("Retail", "retail"),
                                    ("Office", "other"), (None, "other")):
            with self.subTest(property_type):
                path = images.illustration_path(property_type)
                self.assertEqual(path.name, f"{name}.svg")
                self.assertTrue(path.read_text().startswith("<svg"))

    def test_no_picture_uses_an_outside_source(self):
        from app import images
        for path in images.ILLUSTRATIONS.glob("*.svg"):
            with self.subTest(path.name):
                self.assertNotIn("http://", path.read_text().replace("http://www.w3.org/2000/svg", ""))
                self.assertNotIn("https://", path.read_text())

    def test_a_missing_photo_falls_back_to_the_illustration(self):
        from app import images
        uri, is_photo = images.picture({"photo_path": "uploads/gone/photo_1.png", "property_type": "Retail"})
        self.assertFalse(is_photo)
        self.assertTrue(uri.startswith("data:image/svg+xml;base64,"))
