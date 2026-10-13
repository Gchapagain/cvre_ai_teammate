"""Check the parts of the schema that the rest of the app relies on."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

import db

EXPECTED_TABLES = {
    "deals", "rent_roll_units", "t12_line_items", "valuation_outputs", "drafts",
    "users", "documents", "research_jobs", "research_sources", "research_briefs", "flags", "deal_notes", "research_findings",
}


class SchemaTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db_path = Path(self.tmp.name) / "test.db"
        db.init_db(db_path)
        self.conn = db.get_connection(db_path)
        self.addCleanup(self.conn.close)
        self.deal_id = self.conn.execute("INSERT INTO deals (name) VALUES ('Sample Deal')").lastrowid

    def columns(self, table):
        return {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}

    def add_document(self, status):
        self.conn.execute(
            "INSERT INTO documents (deal_id, filename, status) VALUES (?, 'file.pdf', ?)",
            (self.deal_id, status),
        )


class TestSchema(SchemaTestCase):
    def test_all_tables_exist(self):
        rows = self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        self.assertLessEqual(EXPECTED_TABLES, {row["name"] for row in rows})

    def test_documents_has_the_columns_from_the_brief(self):
        expected = {"deal_id", "filename", "source", "received_at", "status", "used_for"}
        self.assertLessEqual(expected, self.columns("documents"))

    def test_documents_accepts_only_the_four_statuses(self):
        for status in ("Received", "Read", "Reference only", "Needs password"):
            self.add_document(status)
        for status in ("Uploaded", "Extracted", "Failed", "read", "received", ""):
            with self.subTest(status):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.add_document(status)

    def test_documents_status_is_required(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO documents (deal_id, filename) VALUES (?, 'file.pdf')", (self.deal_id,)
            )

    def test_flags_has_every_part_of_a_flag(self):
        expected = {"deal_id", "unit_number", "rule", "field", "actual_value", "threshold", "message"}
        self.assertLessEqual(expected, self.columns("flags"))

    def test_flags_must_belong_to_a_real_deal(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO flags (deal_id, rule, message) VALUES (9999, 'rule', 'message')")

    def test_deleting_a_deal_deletes_its_flags(self):
        self.conn.execute(
            "INSERT INTO flags (deal_id, rule, message) VALUES (?, 'rule', 'message')", (self.deal_id,)
        )
        self.conn.execute("DELETE FROM deals WHERE id = ?", (self.deal_id,))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM flags").fetchone()[0], 0)

    def test_old_flag_columns_are_gone(self):
        for table in ("rent_roll_units", "t12_line_items"):
            with self.subTest(table):
                self.assertFalse({"is_flagged", "flag_reason"} & self.columns(table))

    def test_research_sources_stores_published_and_retrieved_dates(self):
        job_id = self.conn.execute(
            "INSERT INTO research_jobs (query) VALUES ('industrial sample submarket')"
        ).lastrowid
        self.conn.execute(
            "INSERT INTO research_sources (job_id, url, tier, published_date) VALUES (?, ?, 1, ?)",
            (job_id, "https://example.gov/report", "2026-08-15"),
        )
        row = self.conn.execute("SELECT published_date, retrieved_at FROM research_sources").fetchone()
        self.assertEqual(row["published_date"], "2026-08-15")
        self.assertTrue(row["retrieved_at"])


if __name__ == "__main__":
    unittest.main()
