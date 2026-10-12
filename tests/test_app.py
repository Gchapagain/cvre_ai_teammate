"""Tests that drive the Streamlit app with Streamlit's own test tool. No browser, no Gemini calls."""

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
from streamlit.testing.v1 import AppTest

import db
import seed
from services import gemini, qa
from tests.test_extraction import daily_quota_error, gemini_error

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
        for status in ("Needs Review", "Extracting", "Approved"):
            self.assertIn(f">{status}</span>", text)
        self.assertIn("1 anomaly", text)

    def test_the_deal_name_is_the_only_button_on_each_card(self):
        labels = {button.key: button.label for button in self.app.button}
        self.assertEqual(labels, {
            "sign_out": "Sign out",
            f"open_deal_{self.deals['fallowmere']}": "Fallowmere Industrial Park (SAMPLE - fictional)",
            f"open_deal_{self.deals['quillhaven']}": "Quillhaven Flex Center (SAMPLE - fictional)",
            f"open_deal_{self.deals['brindlewick']}": "Brindlewick Retail Row (SAMPLE - fictional)",
        })
        self.assertNotIn("Open deal", [button.label for button in self.app.button])

    def test_clicking_a_deal_name_opens_that_deal(self):
        self.open_deal("brindlewick")
        self.assertEqual(self.app.session_state["deal_id"], self.deals["brindlewick"])
        self.assertIn("Brindlewick Retail Row", self.page_text())


class TestDealWorkspace(AppTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_four_tabs(self):
        self.open_deal("fallowmere")
        self.assertFalse(self.app.exception)
        self.assertEqual([tab.label for tab in self.app.tabs], ["Review", "Documents", "Data", "Ask AI"])
        self.assertIn("Documents: coming in a later step.", [message.value for message in self.app.info])

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


class TestDataTabDownloads(AppTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def downloads(self):
        """Every download button on the page as {key: element}."""
        return {element.key: element for element in self.app.get("download_button")}

    def test_fallowmere_offers_rent_roll_and_t12_as_csv_and_excel(self):
        self.open_deal("fallowmere")
        self.assertFalse(self.app.exception)
        self.assertEqual(set(self.downloads()), {
            "download_rent_roll_csv", "download_rent_roll_xlsx", "download_t12_csv", "download_t12_xlsx",
        })
        text = self.page_text()
        self.assertIn("fallowmere_industrial_park_rent_roll.csv", text)
        self.assertIn("fallowmere_industrial_park_t12.xlsx", text)
        self.assertIn("Draft narrative: none yet", text)

    def test_deal_without_a_t12_only_offers_the_rent_roll(self):
        self.open_deal("brindlewick")
        self.assertEqual(set(self.downloads()), {"download_rent_roll_csv", "download_rent_roll_xlsx"})
        self.assertIn("T-12: nothing saved for this deal yet.", self.page_text())

    def test_deal_with_no_numbers_offers_no_downloads(self):
        self.open_deal("quillhaven")
        self.assertFalse(self.app.exception)
        self.assertEqual(self.downloads(), {})

    def test_draft_download_appears_when_a_draft_exists(self):
        conn = db.get_connection(self.db_path)
        with conn:
            draft_id = conn.execute(
                "INSERT INTO drafts (deal_id, draft_type, title, body) VALUES (?, 'Pricing narrative', 'Made-up title', 'Made-up body.')",
                (self.deals["brindlewick"],),
            ).lastrowid
        conn.close()
        try:
            self.open_deal("brindlewick")
            self.assertIn("download_draft", self.downloads())
            self.assertIn("brindlewick_retail_row_draft_narrative.txt", self.page_text())
        finally:
            conn = db.get_connection(self.db_path)
            with conn:
                conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
            conn.close()


def reply_client(calls, answer, found=True, sources=("rent_roll.xlsx",)):
    """A stand-in Gemini client that records each prompt and gives one fixed reply."""
    def generate_content(**kwargs):
        calls.append(kwargs["contents"])
        if isinstance(answer, Exception):
            raise answer
        text = json.dumps({"answer": answer, "found_in_deal": found, "sources": list(sources)})
        return type("Reply", (), {"text": text})()
    return type("Client", (), {"models": type("Models", (), {"generate_content": staticmethod(generate_content)})()})()


class TestAskAiTab(AppTestCase):
    def setUp(self):
        super().setUp()
        self.calls = []
        # Skip the wait between retries. (time.sleep itself is left alone: the test tool uses it.)
        no_wait = mock.patch.object(gemini, "RETRY_WAIT_SECONDS", 0)
        no_wait.start()
        self.addCleanup(no_wait.stop)
        self.sign_in()

    def use_gemini(self, answer, **options):
        patcher = mock.patch.object(gemini, "get_client", lambda: reply_client(self.calls, answer, **options))
        patcher.start()
        self.addCleanup(patcher.stop)

    def ask(self, question, deal="fallowmere"):
        key = f"chat_input_{self.deals[deal]}"
        self.app.chat_input(key=key).set_value(question).run()
        return self.app.session_state[f"chat_{self.deals[deal]}"]

    def test_opening_the_tab_does_not_contact_gemini(self):
        self.use_gemini(AssertionError("Gemini must not be called before a message is sent"))
        self.open_deal("fallowmere")
        self.assertFalse(self.app.exception)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.app.session_state[f"chat_{self.deals['fallowmere']}"], [])

    def test_web_search_switch_is_shown_but_disabled(self):
        self.open_deal("fallowmere")
        toggle = self.app.toggle(key=f"web_search_{self.deals['fallowmere']}")
        self.assertTrue(toggle.disabled)
        self.assertFalse(toggle.value)
        self.assertIn("Web search: coming in a later step.", self.page_text())

    def test_an_answer_from_the_deal_is_labelled_and_sourced(self):
        self.use_gemini("Unit 110 pays 20.33 per SF.")
        self.open_deal("fallowmere")
        messages = self.ask("What does unit 110 pay per SF?")
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual([m["role"] for m in messages], ["user", "assistant"])
        self.assertEqual(messages[1]["label"], qa.LABEL_FROM_DEAL)
        self.assertEqual(messages[1]["sources"], ["rent_roll.xlsx"])
        text = self.page_text()
        self.assertIn(">From this deal</span>", text)
        self.assertIn("Unit 110 pays 20.33 per SF.", text)
        self.assertIn("Source: rent_roll.xlsx", text)

    def test_a_question_the_deal_cannot_answer(self):
        self.use_gemini("The cap rate is probably 6%.", found=False, sources=())
        self.open_deal("fallowmere")
        messages = self.ask("What cap rate should we use?")
        self.assertEqual(messages[1]["label"], qa.LABEL_NOT_VERIFIED)
        self.assertEqual(messages[1]["text"], "I don't have that in this deal.")
        self.assertIn(">Not verified</span>", self.page_text())
        self.assertNotIn("6%", self.page_text())

    def test_daily_quota_shows_a_friendly_message_and_does_not_crash(self):
        self.use_gemini(daily_quota_error())
        self.open_deal("fallowmere")
        messages = self.ask("What is the total annual rent?")
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(messages[1]["label"], "No answer")
        self.assertIn("daily quota is used up", messages[1]["text"])
        self.assertIn("3h52m", messages[1]["text"])
        self.assertIn(">No answer</span>", self.page_text())

    def test_rate_limit_shows_a_friendly_message_after_three_tries(self):
        self.use_gemini(gemini_error(429, "RESOURCE_EXHAUSTED"))
        self.open_deal("fallowmere")
        messages = self.ask("What is the total annual rent?")
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.calls), 3)
        self.assertIn("busy or rate-limited", messages[1]["text"])

    def test_missing_key_or_unexpected_failure_does_not_crash(self):
        for failure in (gemini.GeminiError("GEMINI_API_KEY is not set."), RuntimeError("network down")):
            with self.subTest(type(failure).__name__):
                with mock.patch.object(gemini, "get_client", side_effect=failure):
                    self.app = AppTest.from_file(APP, default_timeout=15).run()
                    self.sign_in()
                    self.open_deal("fallowmere")
                    messages = self.ask("What is the total annual rent?")
                self.assertFalse(self.app.exception)
                self.assertEqual(messages[1]["label"], "No answer")
                self.assertNotIn("network down", messages[1]["text"])

    def test_each_deal_has_its_own_chat_and_only_its_own_data(self):
        self.use_gemini("There are 5 units.", sources=("brindlewick_rent_roll.xlsx",))
        self.open_deal("brindlewick")
        self.ask("How many units?", deal="brindlewick")
        self.assertIn("Pemberly Sock Emporium", self.calls[0])
        self.assertNotIn("Vantor Robotics Lab", self.calls[0])
        self.app.button(key="back_to_deals").click().run()
        self.open_deal("fallowmere")
        self.assertEqual(self.app.session_state[f"chat_{self.deals['fallowmere']}"], [])

    def test_deal_with_no_numbers_answers_without_calling_gemini(self):
        self.use_gemini(AssertionError("Gemini must not be called for a deal with no data"))
        self.open_deal("quillhaven")
        messages = self.ask("What is the NOI?", deal="quillhaven")
        self.assertEqual(self.calls, [])
        self.assertEqual(messages[1]["label"], qa.LABEL_NOT_VERIFIED)
        self.assertIn("I don't have that in this deal.", messages[1]["text"])


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
