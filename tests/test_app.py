"""Tests that drive the Streamlit app with Streamlit's own test tool. No browser, no Gemini calls."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

import db
import seed

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


class AppTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.db_path = Path(cls.tmp.name) / "app.db"
        cls.deals = seed.seed(cls.db_path)

    def setUp(self):
        patcher = mock.patch.object(db, "DB_PATH", self.db_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = AppTest.from_file(APP, default_timeout=15).run()

    def sign_in(self, role="Analyst", provider="google"):
        self.app.radio(key="login_role").set_value(role).run()
        self.app.button(key=f"sign_in_{provider}").click().run()

    def open_deal(self, name):
        self.app.button(key=f"open_deal_{self.deals[name]}").click().run()

    def page_text(self):
        """All markdown, headings, captions and messages on the page as one string."""
        parts = []
        for kind in ("title", "header", "subheader", "markdown", "caption", "info", "warning", "error"):
            parts += [element.value for element in getattr(self.app, kind)]
        return "\n".join(parts)


class TestLogin(AppTestCase):
    def test_sign_in_buttons_are_locked_until_a_role_is_chosen(self):
        self.assertFalse(self.app.exception)
        self.assertIsNone(self.app.radio(key="login_role").value)
        self.assertTrue(self.app.button(key="sign_in_google").disabled)
        self.assertTrue(self.app.button(key="sign_in_microsoft").disabled)
        self.assertNotIn("user", self.app.session_state)

    def test_role_options(self):
        self.assertEqual(self.app.radio(key="login_role").options, ["Agent", "Analyst", "Administrator"])

    def test_choosing_a_role_unlocks_both_buttons(self):
        self.app.radio(key="login_role").set_value("Agent").run()
        self.assertFalse(self.app.button(key="sign_in_google").disabled)
        self.assertFalse(self.app.button(key="sign_in_microsoft").disabled)

    def test_page_says_it_is_a_demo_login(self):
        self.assertIn("Demo login", self.page_text())
        self.assertIn("(demo)", self.app.button(key="sign_in_google").label)

    def test_each_role_signs_in_as_its_demo_user(self):
        for role, provider in (("Agent", "google"), ("Analyst", "microsoft"), ("Administrator", "google")):
            with self.subTest(role):
                self.app = AppTest.from_file(APP, default_timeout=15).run()
                self.sign_in(role, provider)
                self.assertFalse(self.app.exception)
                self.assertEqual(self.app.session_state["user"]["role"], role)
                self.assertIn(f"{role} · demo login", self.page_text())

    def test_sign_out_returns_to_the_locked_login(self):
        self.sign_in()
        self.app.button(key="sign_out").click().run()
        self.assertNotIn("user", self.app.session_state)
        self.assertTrue(self.app.button(key="sign_in_google").disabled)


class TestDashboard(AppTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_stat_cards(self):
        text = self.page_text()
        for label in ("Active deals", "Needs review", "Time saved", "Anomalies"):
            self.assertIn(label, text)
        self.assertIn("Not measured yet", text)
        self.assertIn("Real timings arrive with the accuracy report", text)

    def test_stat_numbers_come_from_the_database(self):
        from app import queries
        self.assertEqual(queries.dashboard_stats(), {"active_deals": 2, "needs_review": 1, "anomalies": 1})

    def test_every_deal_has_a_card_with_its_status(self):
        text = self.page_text()
        for name in ("Fallowmere Industrial Park", "Quillhaven Flex Center", "Brindlewick Retail Row"):
            self.assertIn(name, text)
        for status in ("Needs Review", "Extracting", "Approved"):
            self.assertIn(f">{status}</span>", text)
        self.assertIn("1 anomaly", text)
        for deal_id in self.deals.values():
            self.assertFalse(self.app.button(key=f"open_deal_{deal_id}").disabled)


class TestDealWorkspace(AppTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_four_tabs(self):
        self.open_deal("fallowmere")
        self.assertFalse(self.app.exception)
        self.assertEqual([tab.label for tab in self.app.tabs], ["Review", "Documents", "Data", "Ask AI"])
        later = [message.value for message in self.app.info]
        self.assertEqual(later, [f"{name}: coming in a later step." for name in ("Documents", "Data", "Ask AI")])

    def test_review_shows_the_anomaly_banner_for_unit_110(self):
        self.open_deal("fallowmere")
        text = self.page_text()
        self.assertIn("1 anomaly found", text)
        self.assertIn("Unit 110 rent/SF is $20.33", text)
        self.assertIn("Flagged, not hidden", text)

    def test_review_table_shows_all_units_and_marks_only_unit_110(self):
        self.open_deal("fallowmere")
        table = self.app.dataframe[0].value
        self.assertEqual(len(table), 12)
        self.assertEqual(list(table[table["Flag"] == "Flagged"]["Unit"]), ["110"])
        self.assertEqual(float(table[table["Unit"] == "110"]["Rent / SF"].iloc[0]), 20.33)

    def test_only_the_flagged_row_is_highlighted(self):
        from app.views import deal
        from app import queries
        deal_id = self.deals["fallowmere"]
        table = deal.units_table(queries.deal_units(deal_id), queries.deal_flags(deal_id))
        styles = deal._styled(table)._compute().ctx
        highlighted_rows = {row for (row, _column) in styles}
        self.assertEqual([table.iloc[row]["Unit"] for row in highlighted_rows], ["110"])

    def test_approved_deal_shows_no_anomalies(self):
        self.open_deal("brindlewick")
        self.assertIn("No anomalies found", self.page_text())
        table = self.app.dataframe[0].value
        self.assertEqual(len(table), 5)
        self.assertEqual(set(table["Flag"]), {""})

    def test_extracting_deal_says_there_are_no_numbers_yet(self):
        self.open_deal("quillhaven")
        self.assertFalse(self.app.exception)
        self.assertIn("No numbers yet", self.page_text())
        self.assertEqual(len(self.app.dataframe), 0)

    def test_back_button_returns_to_the_dashboard(self):
        self.open_deal("fallowmere")
        self.app.button(key="back_to_deals").click().run()
        self.assertIn("Active deals", self.page_text())


class TestAppNeverChangesData(AppTestCase):
    def test_a_full_visit_leaves_the_database_file_identical(self):
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        self.sign_in()
        for name in self.deals:
            self.open_deal(name)
            self.app.button(key="back_to_deals").click().run()
        self.app.button(key="sign_out").click().run()
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).hexdigest(), before)

    def test_database_is_opened_read_only(self):
        import sqlite3
        from app import queries
        conn = queries._connect()
        self.addCleanup(conn.close)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("DELETE FROM deals")


class TestNoSampleData(unittest.TestCase):
    def test_missing_database_shows_instructions_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "missing.db"
            with mock.patch.object(db, "DB_PATH", missing):
                app = AppTest.from_file(APP, default_timeout=15).run()
            self.assertFalse(app.exception)
            self.assertIn("no sample data yet", app.warning[0].value)
            self.assertIn("seed.py --reset", app.code[0].value)
            self.assertEqual(len(app.button), 0)
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
