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

    def test_broker_is_the_only_role(self):
        self.conn.execute("INSERT INTO users (email, full_name, role) VALUES ('a@example.com', 'A', 'Broker')")
        for role in ("Agent", "Analyst", "Administrator", "broker"):
            with self.subTest(role):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute("INSERT INTO users (email, full_name, role) VALUES (?, 'B', ?)", (f"{role}@example.com", role))

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



class TestPaths(unittest.TestCase):
    def test_relative_paths_are_taken_from_the_project_folder(self):
        self.assertEqual(db.project_path("sample_data/demo.db"), db.PROJECT_ROOT / "sample_data" / "demo.db")
        self.assertEqual(db.project_path("/tmp/elsewhere.db"), Path("/tmp/elsewhere.db"))

    def test_the_committed_demo_database_is_fresh_sample_data(self):
        conn = db.get_connection(db.PROJECT_ROOT / "sample_data" / "demo.db")
        deals = [r["name"] for r in conn.execute("SELECT name FROM deals ORDER BY id")]
        users = [tuple(r) for r in conn.execute("SELECT full_name, role FROM users")]
        edits = conn.execute("SELECT COUNT(*) FROM edits").fetchone()[0]
        conn.close()
        self.assertEqual(len(deals), 3)
        self.assertTrue(all("SAMPLE - fictional" in name for name in deals))
        self.assertEqual(users, [("Avery Sample", "Broker")])
        self.assertEqual(edits, 0)

    def test_the_committed_demo_database_is_at_the_current_schema_version(self):
        conn = db.get_connection(db.PROJECT_ROOT / "sample_data" / "demo.db")
        try:
            self.assertEqual(db.schema_version(conn), db.SCHEMA_VERSION)
        finally:
            conn.close()


class TestSchemaVersion(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / "old.db"

    def version(self):
        conn = db.get_connection(self.db_path)
        try:
            return db.schema_version(conn)
        finally:
            conn.close()

    def test_a_new_database_records_the_current_version(self):
        db.init_db(self.db_path)
        self.assertEqual(self.version(), db.SCHEMA_VERSION)

    def test_a_version_0_database_gets_the_photo_column_and_keeps_its_deals(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE deals (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, property_type TEXT, "
                     "submarket TEXT, address TEXT, status TEXT NOT NULL DEFAULT 'New', owner_user_id INTEGER, "
                     "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                     "approved_by TEXT, approved_at TEXT)")
        conn.execute("INSERT INTO deals (name) VALUES ('Old Sample Deal')")
        conn.commit()
        conn.close()
        self.assertEqual(self.version(), 0)
        db.init_db(self.db_path)
        conn = db.get_connection(self.db_path)
        try:
            row = dict(conn.execute("SELECT name, photo_path FROM deals").fetchone())
        finally:
            conn.close()
        self.assertEqual(row, {"name": "Old Sample Deal", "photo_path": None})
        self.assertEqual(self.version(), db.SCHEMA_VERSION)


class TestOldThreeRoleUsersTable(unittest.TestCase):
    OLD = """CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, full_name TEXT NOT NULL,
             role TEXT NOT NULL CHECK (role IN ('Agent', 'Analyst', 'Administrator')), password_hash TEXT,
             created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""

    def test_agents_become_brokers_and_unused_other_roles_go(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            conn = sqlite3.connect(path)
            conn.execute(self.OLD)
            conn.executemany("INSERT INTO users (email, full_name, role) VALUES (?, ?, ?)", [
                ("demo.agent@example.com", "Avery Sample", "Agent"), ("demo.analyst@example.com", "Noor Sample", "Analyst"),
                ("demo.admin@example.com", "Sam Sample", "Administrator")])
            conn.execute("CREATE TABLE deals (id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner_user_id INTEGER REFERENCES users(id))")
            conn.execute("INSERT INTO deals (name, owner_user_id) VALUES ('Made-up deal owned by the admin', 3)")
            conn.commit()
            conn.close()
            db.init_db(path)
            db.init_db(path)  # running it twice is harmless
            conn = db.get_connection(path)
            users = [dict(r) for r in conn.execute("SELECT id, full_name, role FROM users ORDER BY id")]
            deal = dict(conn.execute("SELECT owner_user_id FROM deals").fetchone())
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'users'").fetchone()["sql"]
            problems = conn.execute("PRAGMA foreign_key_check").fetchall()
            conn.close()
        # Avery stays (as Broker), Noor is removed, Sam is kept as a Broker because a deal points at them.
        self.assertEqual(users, [{"id": 1, "full_name": "Avery Sample", "role": "Broker"},
                                 {"id": 3, "full_name": "Sam Sample", "role": "Broker"}])
        self.assertEqual(deal, {"owner_user_id": 3})
        self.assertNotIn("Analyst", sql)
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
