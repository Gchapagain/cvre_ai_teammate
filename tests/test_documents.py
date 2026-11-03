"""The Documents tab: upload, type detection, Read it now, locked files and what was read.

Gemini is always simulated. Every file here is made up for the test.
"""

import csv
import hashlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image
from pypdf import PdfWriter

import db
import seed
from services import documents, gemini, om_assets, om_export
from tests.test_app import AppTestCase
from tests.test_extraction import FIELDS, RENT_ROLL, daily_quota_error, fake_client, forbidden_client


def pdf_bytes(text="Made-up test page", password=None):
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    if text:  # a page with words on it, so the content can be checked
        from pypdf.generic import ContentStream, NameObject
        page = writer.pages[0]
        font = {"/Type": "/Font", "/Subtype": "/Type1", "/BaseFont": "/Helvetica"}
        from pypdf.generic import DictionaryObject
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject(
            {NameObject("/F1"): writer._add_object(DictionaryObject({NameObject(k): NameObject(v) for k, v in font.items()}))})})
        stream = ContentStream(None, writer)
        stream.set_data(f"BT /F1 12 Tf 20 200 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    if password:
        writer.encrypt(password)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def png():
    out = io.BytesIO()
    Image.new("RGB", (300, 200), (120, 150, 170)).save(out, "PNG")
    return out.getvalue()


class DocumentsCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db_path = self.dir / "docs.db"
        self.uploads = self.dir / "uploads"
        with mock.patch.object(om_assets, "ASSET_DIR", self.dir / "assets"), mock.patch("sample_om.ASSET_DIR", self.dir / "assets"):
            self.deals = seed.seed(self.db_path)
        for target, name, value in ((db, "DB_PATH", self.db_path), (om_assets, "ASSET_DIR", self.dir / "assets"),
                                    (documents.deals, "UPLOAD_DIR", self.uploads), (om_export, "soffice_path", lambda: None)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.dict(os.environ, {"CBRE_DB_PATH": str(self.db_path)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.deal = self.deals["quillhaven"]

    def add(self, *files):
        return documents.add_documents(self.deal, list(files), db_path=self.db_path)

    def doc(self, document_id):
        conn = db.get_connection(self.db_path)
        try:
            return dict(conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone())
        finally:
            conn.close()

    def rent_roll_csv(self):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Unit", "Tenant", "SF", "Lease Start", "Lease End", "Monthly Base Rent", "Annual Base Rent",
                         "Rent / SF (Annual)", "Lease Type"])
        self.units = [{"unit_number": "A1", "tenant_name": "Made-up Bakery (test)", "square_feet": 2000,
                       "lease_start": "2024-01-01", "lease_end": "2029-12-31", "monthly_rent": 3000, "annual_rent": 36000,
                       "rent_per_sf": 18.0, "lease_type": "NNN"},
                      {"unit_number": "A2", "tenant_name": "Made-up Books (test)", "square_feet": 1500,
                       "lease_start": "2023-06-01", "lease_end": "2028-05-31", "monthly_rent": 2250, "annual_rent": 27000,
                       "rent_per_sf": 18.0, "lease_type": "NNN"}]
        writer.writerows([[u[f] for f in FIELDS] for u in self.units])
        return buffer.getvalue().encode()


class TestUploadAndTypes(DocumentsCase):
    def test_files_are_saved_under_the_deal_as_received_with_a_detected_type(self):
        results = self.add(("quillhaven_rent_roll.csv", self.rent_roll_csv()), ("Q3 BOV final.pdf", pdf_bytes()),
                           ("site notes.docx", b"PK\x03\x04 made-up docx"))
        self.assertEqual([(r["type"], r["status"]) for r in results],
                         [("Rent roll", "Received"), ("BOV", "Received"), ("Other", "Received")])
        for result in results:
            path = Path(self.doc(result["id"])["file_path"])
            self.assertEqual(path.parent, self.uploads / str(self.deal))
            self.assertTrue(path.is_file())

    def test_type_comes_from_the_content_when_the_name_says_nothing(self):
        self.assertEqual(documents.detect_type("upload1.xlsx", RENT_ROLL.read_bytes(), RENT_ROLL), "Rent roll")
        self.assertEqual(documents.detect_type("scan.pdf", pdf_bytes("Appraisal report for a made-up property")), "Appraisal")
        self.assertEqual(documents.detect_type("t12_2025.xlsx", b"PK"), "T-12")
        self.assertEqual(documents.detect_type("Offering Memorandum.pdf", pdf_bytes(None)), "OM")
        self.assertEqual(documents.detect_type("front.JPG", b"..."), "Photo")

    def test_photos_go_to_the_om_photo_sorter(self):
        result = self.add(("front.png", png()))[0]
        self.assertEqual((result["type"], result["status"]), ("Photo", "Reference only"))
        self.assertEqual(len(om_assets.assets(self.deal, self.db_path)), 1)

    def test_too_large_and_unsupported_files_get_a_friendly_message_and_are_not_saved(self):
        with mock.patch.object(documents, "MAX_BYTES", 10):
            big, odd = self.add(("big.pdf", pdf_bytes()), ("notes.exe", b"x"))
        self.assertIn("the limit is", big["message"])
        self.assertIn("Not added", odd["message"])
        self.assertIsNone(big["status"])
        self.assertFalse((self.uploads / str(self.deal) / "big.pdf").exists())

    def test_the_broker_can_change_the_type(self):
        result = self.add(("misc.pdf", pdf_bytes()))[0]
        documents.set_type(result["id"], "Appraisal", self.db_path)
        self.assertEqual(self.doc(result["id"])["doc_type"], "Appraisal")
        with self.assertRaises(documents.DocumentError):
            documents.set_type(result["id"], "Spreadsheet", self.db_path)


class TestReadItNow(DocumentsCase):
    def test_a_received_rent_roll_is_read_with_one_request(self):
        result = self.add(("quillhaven_rent_roll.csv", self.rent_roll_csv()))[0]
        calls = []
        client = fake_client(self.units)
        original = client.models.generate_content
        client.models.generate_content = lambda **kw: calls.append(1) or original(**kw)
        summary = documents.read_now(result["id"], client, self.db_path)
        self.assertEqual((summary["units_saved"], len(calls)), (2, 1))
        doc = self.doc(result["id"])
        self.assertEqual((doc["status"], doc["used_for"]), ("Read", "Rent roll"))
        conn = db.get_connection(self.db_path)
        status = conn.execute("SELECT status FROM deals WHERE id = ?", (self.deal,)).fetchone()["status"]
        units = [dict(r) for r in conn.execute("SELECT * FROM rent_roll_units WHERE document_id = ?", (result["id"],))]
        flags = [dict(r) for r in conn.execute("SELECT * FROM flags WHERE deal_id = ?", (self.deal,))]
        conn.close()
        self.assertEqual(status, "Needs Review")
        self.assertEqual(documents.what_we_read(doc, units, flags, []), "2 units extracted, 0 flagged.")

    def test_a_quota_error_leaves_the_file_received(self):
        result = self.add(("quillhaven_rent_roll.csv", self.rent_roll_csv()))[0]
        from types import SimpleNamespace

        def refuse(**kwargs):
            raise daily_quota_error()
        with self.assertRaisesRegex(documents.DocumentError, "quota is used up"):
            documents.read_now(result["id"], SimpleNamespace(models=SimpleNamespace(generate_content=refuse)), self.db_path)
        self.assertEqual(self.doc(result["id"])["status"], "Received")

    def test_only_a_received_rent_roll_with_a_file_can_be_read(self):
        bov = self.add(("bov.pdf", pdf_bytes()))[0]
        with self.assertRaises(documents.DocumentError):
            documents.read_now(bov["id"], forbidden_client(), self.db_path)
        conn = db.get_connection(self.db_path)
        no_file = conn.execute("SELECT id FROM documents WHERE deal_id = ? AND file_path IS NULL", (self.deal,)).fetchone()["id"]
        conn.execute("UPDATE documents SET doc_type = 'Rent roll' WHERE id = ?", (no_file,))
        conn.commit()
        conn.close()
        with self.assertRaisesRegex(documents.DocumentError, "not on this server"):
            documents.read_now(no_file, forbidden_client(), self.db_path)


class TestLockedFiles(DocumentsCase):
    def test_a_locked_pdf_needs_a_password_and_a_wrong_one_is_refused_kindly(self):
        result = self.add(("bov_locked.pdf", pdf_bytes(password="made-up-secret")))[0]
        self.assertEqual(result["status"], "Needs password")
        with self.assertRaisesRegex(documents.DocumentError, "did not open"):
            documents.unlock(result["id"], "wrong", self.db_path)
        self.assertEqual(self.doc(result["id"])["status"], "Needs password")

    def test_the_right_password_unlocks_a_copy_and_is_never_saved(self):
        result = self.add(("bov_locked.pdf", pdf_bytes("Broker opinion of value (test)", password="made-up-secret")))[0]
        documents.unlock(result["id"], "made-up-secret", self.db_path)
        doc = self.doc(result["id"])
        self.assertEqual(doc["status"], "Received")
        self.assertTrue(doc["file_path"].endswith("(unlocked).pdf"))
        self.assertIsNotNone(documents.pdf_text(Path(doc["file_path"]).read_bytes()))  # opens without a password
        self.assertNotIn(b"made-up-secret", self.db_path.read_bytes())

    def test_locked_office_files_are_detected(self):
        result = self.add(("rent_roll.xlsx", documents.OLE_MAGIC + b"made-up encrypted package"))[0]
        self.assertEqual(result["status"], "Needs password")
        with self.assertRaisesRegex(documents.DocumentError, "Only PDFs"):
            documents.unlock(result["id"], "anything", self.db_path)


class TestWhatWeRead(DocumentsCase):
    def test_lines_come_only_from_saved_rows(self):
        base = {"id": 1, "filename": "f", "file_path": "x", "used_for": None}
        self.assertEqual(documents.what_we_read(dict(base, status="Needs password", doc_type="BOV"), [], [], []),
                         "Locked: needs a password before it can be read.")
        self.assertEqual(documents.what_we_read(dict(base, status="Reference only", doc_type="BOV"), [], [], []),
                         "Reference only - not used for numbers.")
        self.assertEqual(documents.what_we_read(dict(base, status="Received", doc_type="Rent roll"), [], [], []), "Not read yet.")
        self.assertIn("not built yet", documents.what_we_read(dict(base, status="Received", doc_type="T-12"), [], [], []))
        units = [{"id": 5, "document_id": 1}, {"id": 6, "document_id": 1}, {"id": 7, "document_id": 2}]
        flags = [{"rent_roll_unit_id": 6, "status": "open"}, {"rent_roll_unit_id": 7, "status": "open"}]
        self.assertEqual(documents.what_we_read(dict(base, status="Read", doc_type="Rent roll"), units, flags, []),
                         "2 units extracted, 1 flagged.")

    def test_summary_line(self):
        docs = [{"status": "Read"}, {"status": "Read"}, {"status": "Needs password"}]
        self.assertEqual(documents.summary_line(docs), "3 documents: 2 read, 1 needs a password")
        self.assertEqual(documents.summary_line([]), "No documents yet.")

    def test_sample_fallowmere_rent_roll_reads_as_extracted(self):
        from app import queries
        deal = self.deals["fallowmere"]
        rent_roll = next(d for d in queries.deal_documents(deal) if d["doc_type"] == "Rent roll")
        line = documents.what_we_read(rent_roll, queries.deal_units(deal), queries.deal_flags(deal), [])
        self.assertEqual(line, "12 units extracted, 1 flagged.")

    def test_viewing_never_changes_the_database(self):
        from app import om_status, queries
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        for deal in self.deals.values():
            docs = queries.deal_documents(deal)
            documents.summary_line(docs)
            for doc in docs:
                documents.what_we_read(doc, queries.deal_units(deal), queries.deal_flags(deal), queries.deal_t12_with_documents(deal))
                documents.size_text(doc)
            om_status.state(deal)
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).hexdigest(), before)


class TestDocumentsTab(AppTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_the_tab_lists_every_document_with_a_summary(self):
        self.open_deal("fallowmere")
        self.assertFalse(self.app.exception)
        text = self.page_text()
        self.assertIn("2 documents: 2 read", text)
        self.assertIn("12 units extracted, 1 flagged.", text)
        self.assertNotIn("Documents: coming in a later step.", text)
        self.assertEqual(len([c for c in self.app.get("download_button") if c.key.startswith("doc_dl_")]), 2)

    def test_a_received_file_without_a_file_says_so_and_offers_no_read(self):
        self.open_deal("quillhaven")
        text = self.page_text()
        self.assertIn("Not read yet", text)
        self.assertFalse([b for b in self.app.button if b.key and b.key.startswith("doc_read_")])

    def test_feed_document_items_open_the_documents_tab_on_that_file(self):
        from app import nav
        with mock.patch.dict(self.app.session_state.filtered_state if False else {}, {}):
            pass
        self.app.session_state["page"] = "home"
        self.app.run()
        keys = [b.key for b in self.app.button if b.key and "_doc_" in b.key and b.key.startswith("feedbtn_")]
        self.assertTrue(keys, "a feed card for the unread Quillhaven rent roll")
        self.app.button(key=keys[0]).click().run()
        self.assertEqual(self.app.session_state["deal_id"], self.deals["quillhaven"])
        self.assertTrue(self.app.session_state["deal_tabs"].startswith("Documents"))
        self.assertFalse(self.app.exception)
        del nav
