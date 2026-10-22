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
from services import gemini, qa, transcribe
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

    def sign_in(self, provider="google"):
        self.app.button(key=f"sign_in_{provider}").click().run()

    def open_deal(self, name):
        self.app.button(key=f"open_deal_{self.deals[name]}").click().run()

    def page_text(self):
        """All markdown, headings, captions and messages on the page as one string."""
        parts = []
        for kind in ("title", "header", "subheader", "markdown", "caption", "info", "warning", "error"):
            parts += [element.value for element in getattr(self.app, kind)]
        return "\n".join(part for part in parts if "<style>" not in part)  # leave out the stylesheet


class TestLogin(AppTestCase):
    def test_no_role_step_and_both_buttons_work_straight_away(self):
        self.assertFalse(self.app.exception)
        self.assertEqual([b.key for b in self.app.button], ["sign_in_google", "sign_in_microsoft"])
        self.assertFalse(self.app.button(key="sign_in_google").disabled)
        self.assertFalse(self.app.button(key="sign_in_microsoft").disabled)
        text = self.page_text()
        for gone in ("Step 1", "Step 2", "Choose a role", "Analyst", "Administrator", "Agent"):
            self.assertNotIn(gone, text)

    def test_an_old_database_without_a_broker_says_to_re_seed(self):
        conn = db.get_connection(self.db_path)
        with conn:
            conn.execute("DELETE FROM users")
        conn.close()
        self.app = AppTest.from_file(APP, default_timeout=15).run()
        self.assertIn("seed.py --reset", self.app.warning[0].value)
        self.assertTrue(self.app.button(key="sign_in_google").disabled)
        seed.seed(self.db_path)  # put the shared test database back

    def test_card_text(self):
        text = self.page_text()
        for expected in ("Welcome back", "Sign in to review your deals.", "Broker sign-in",
                         "Demo login. No real sign-in happens yet."):
            self.assertIn(expected, text)
        self.assertEqual(self.app.button(key="sign_in_google").label, "Continue with Google")
        self.assertEqual(self.app.button(key="sign_in_microsoft").label, "Continue with Microsoft")

    def test_left_panel_has_the_brand_tagline_and_three_points(self):
        text = self.page_text()
        for expected in ("CBRE AI Teammate", "The AI drafts, flags and cites. A person always approves.",
                         "Flags problems, never hides them", "Cites where every number came from",
                         "A person approves every result"):
            self.assertIn(expected, text)

    def test_either_button_signs_in_as_the_demo_broker(self):
        for provider in ("google", "microsoft"):
            with self.subTest(provider):
                self.app = AppTest.from_file(APP, default_timeout=15).run()
                self.sign_in(provider)
                self.assertFalse(self.app.exception)
                self.assertEqual(self.app.session_state["user"],
                                 {"email": "demo.broker@example.com", "full_name": "Avery Sample", "role": "Broker"})
                self.assertIn('<span class="role-badge">Broker</span>', self.page_text())

    def test_sign_out_returns_to_the_login(self):
        self.sign_in()
        self.app.button(key="sign_out").click().run()
        self.assertNotIn("user", self.app.session_state)
        self.assertIn("Broker sign-in", self.page_text())


class TestDashboard(AppTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def deal_buttons(self):
        return [button.key for button in self.app.button if button.key.startswith("open_deal_")]

    def deal_keys(self, *names):
        return [f"open_deal_{self.deals[name]}" for name in names]

    def click_stat(self, name):
        self.app.button(key=f"statbtn_{name}").click().run()
        self.assertFalse(self.app.exception)

    def test_stat_cards(self):
        labels = [self.app.button(key=f"statbtn_{name}").label for name in ("active", "review", "time", "anomalies")]
        self.assertEqual(labels, ["Active deals", "Needs review", "Time saved", "Anomalies"])
        self.assertIn("Not measured yet", self.page_text())

    def test_nothing_is_filtered_at_first(self):
        self.assertEqual(self.deal_buttons(), self.deal_keys("fallowmere", "quillhaven", "brindlewick"))
        self.assertNotIn("Showing:", self.page_text())
        self.assertNotIn("clear_filter", [button.key for button in self.app.button])

    def test_active_deals_card_shows_only_deals_not_yet_approved(self):
        self.click_stat("active")
        self.assertEqual(self.deal_buttons(), self.deal_keys("fallowmere", "quillhaven"))
        self.assertIn("Showing: Active deals (2)", self.page_text())

    def test_needs_review_card_shows_only_deals_needing_review(self):
        self.click_stat("review")
        self.assertEqual(self.deal_buttons(), self.deal_keys("fallowmere"))
        self.assertIn("Showing: Needs Review (1)", self.page_text())

    def test_anomalies_card_shows_only_deals_with_flags(self):
        self.click_stat("anomalies")
        self.assertEqual(self.deal_buttons(), self.deal_keys("fallowmere"))
        self.assertIn("Showing: Anomalies (1)", self.page_text())

    def test_clear_button_resets_the_filter(self):
        self.click_stat("review")
        self.assertEqual(self.app.button(key="clear_filter").label, "Clear")
        self.app.button(key="clear_filter").click().run()
        self.assertEqual(len(self.deal_buttons()), 3)
        self.assertNotIn("Showing:", self.page_text())
        self.assertNotIn("show_all_deals", [button.key for button in self.app.button])

    def test_page_title_is_all_deals(self):
        self.assertEqual([header.value for header in self.app.header], ["All deals"])

    def test_top_bar_links_go_home_and_clear_the_filter(self):
        for key in ("nav_home", "nav_all_deals"):
            with self.subTest(key):
                self.click_stat("review")
                self.open_deal("fallowmere")
                self.app.button(key=key).click().run()
                self.assertFalse(self.app.exception)
                self.assertEqual([header.value for header in self.app.header], ["All deals"])
                self.assertIsNone(self.app.session_state["deal_filter"])
                self.assertEqual(len(self.deal_buttons()), 3)

    def test_top_bar_links_also_clear_a_filter_from_the_dashboard(self):
        self.click_stat("anomalies")
        self.app.button(key="nav_all_deals").click().run()
        self.assertEqual(len(self.deal_buttons()), 3)

    def test_clicking_the_selected_card_again_clears_it(self):
        self.click_stat("review")
        self.click_stat("review")
        self.assertEqual(len(self.deal_buttons()), 3)

    def test_switching_cards_switches_the_filter(self):
        self.click_stat("review")
        self.click_stat("active")
        self.assertEqual(self.app.session_state["deal_filter"], "active")
        self.assertEqual(len(self.deal_buttons()), 2)

    def test_time_saved_card_opens_an_explanation_and_filters_nothing(self):
        self.click_stat("time")
        text = self.page_text()
        self.assertIn("Time saved is not measured yet.", text)
        self.assertIn("accuracy report", text)
        self.assertEqual(len(self.deal_buttons()), 3)
        self.app.button(key="close_time_saved").click().run()
        self.assertNotIn("Time saved is not measured yet.", self.page_text())

    def test_a_filtered_deal_still_opens(self):
        self.click_stat("anomalies")
        self.open_deal("fallowmere")
        self.assertIn("Extracted fields", self.page_text())

    def test_filter_rules(self):
        from app.views import dashboard
        deals = [
            {"id": 1, "status": "Needs Review", "flag_count": 0},
            {"id": 2, "status": "Extracting", "flag_count": 2},
            {"id": 3, "status": "Approved", "flag_count": 1},
            {"id": 4, "status": "Approved", "flag_count": 0},
        ]
        ids = lambda name: [deal["id"] for deal in dashboard.filter_deals(deals, name)]
        self.assertEqual(ids("active"), [1, 2])
        self.assertEqual(ids("review"), [1])
        self.assertEqual(ids("anomalies"), [2, 3])
        self.assertEqual(ids(None), [1, 2, 3, 4])
        self.assertEqual(ids("time"), [1, 2, 3, 4])

    def test_stat_numbers_come_from_the_database(self):
        from app import queries
        self.assertEqual(queries.dashboard_stats(), {"active_deals": 2, "needs_review": 1, "anomalies": 1})

    def test_every_deal_has_a_card_with_its_status(self):
        text = self.page_text()
        for status in ("Needs Review", "Extracting", "Approved"):
            self.assertIn(f">{status}</span>", text)
        self.assertIn("1 anomaly", text)

    def test_the_deal_name_is_the_only_button_on_each_card(self):
        labels = {button.key: button.label for button in self.app.button if not button.key.startswith("statbtn_")}
        self.assertEqual(labels, {
            "nav_home": "CBRE AI Teammate",
            "nav_all_deals": "All deals",
            "nav_connections": "Connections",
            "new_deal": "New deal",
            "sign_out": "Sign out",
            "open_assistant": "Ask the AI Teammate",
            f"open_deal_{self.deals['fallowmere']}": "Fallowmere Industrial Park (SAMPLE - fictional)",
            f"open_deal_{self.deals['quillhaven']}": "Quillhaven Flex Center (SAMPLE - fictional)",
            f"open_deal_{self.deals['brindlewick']}": "Brindlewick Retail Row (SAMPLE - fictional)",
        })
        self.assertNotIn("Open deal", [button.label for button in self.app.button])

    def test_deals_needing_attention_come_first(self):
        order = [button.key for button in self.app.button if button.key.startswith("open_deal_")]
        self.assertEqual(order, [f"open_deal_{self.deals[name]}" for name in ("fallowmere", "quillhaven", "brindlewick")])
        text = self.page_text()
        self.assertLess(text.index("Needs your attention (1)"), text.index("Other deals (2)"))

    def test_card_accent_follows_the_deal(self):
        from app import queries
        from app.views import dashboard
        kinds = {deal["name"].split()[0]: dashboard.card_kind(deal) for deal in queries.list_deals()}
        self.assertEqual(kinds, {"Fallowmere": "flagged", "Quillhaven": "plain", "Brindlewick": "plain"})
        self.assertEqual(dashboard.card_kind({"flag_count": 0, "status": "Needs Review"}), "review")

    def test_header_shows_the_name_once_with_a_role_badge(self):
        text = self.page_text()
        self.assertEqual(text.count("Avery Sample"), 1)
        self.assertEqual(text.count("Broker"), 1)
        self.assertIn('<span class="user-name">Avery Sample</span><span class="role-badge">Broker</span>', text)
        self.assertEqual(self.app.button(key="nav_home").label, "CBRE AI Teammate")

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
        self.assertEqual([tab.label for tab in self.app.tabs],
                         ["Review", "Documents :gray-badge[2]", "Data", "Recommendations", ":material/auto_awesome: Ask AI"])
        self.assertIn("Documents: coming in a later step.", [message.value for message in self.app.info])

    def test_review_shows_a_decision_card_for_the_open_flag(self):
        self.open_deal("fallowmere")
        text = self.page_text()
        self.assertIn("1 flag to resolve", text)
        self.assertIn("Unit 110 · rent/SF is more than 2x the average of the other units", text)
        self.assertIn("Unit 110 rent/SF is $20.33", text)
        self.assertIn('Value: <span class="num">20.33</span> · Limit: <span class="num">17.19</span>', text)
        self.assertEqual(self.app.button(key=f"fix_btn_{self.flag_id()}").label, "This is wrong - fix it")
        self.assertEqual(self.app.button(key=f"confirm_btn_{self.flag_id()}").label, "This is correct - confirm it")

    def flag_id(self):
        conn = db.get_connection(self.db_path)
        flag_id = conn.execute("SELECT id FROM flags WHERE unit_number = '110'").fetchone()["id"]
        conn.close()
        return flag_id

    def test_review_table_shows_all_units_and_marks_only_unit_110(self):
        self.open_deal("fallowmere")
        table = self.app.dataframe[0].value
        self.assertEqual(len(table), 12)
        self.assertEqual(list(table[table["Flag"] == "Flagged"]["Unit"]), ["110"])
        self.assertEqual(float(table[table["Unit"] == "110"]["Rent / SF"].iloc[0]), 20.33)

    def test_only_the_flagged_row_is_highlighted(self):
        from app.views import review
        from app import queries
        deal_id = self.deals["fallowmere"]
        table = review.units_table(queries.deal_units(deal_id), queries.deal_flags(deal_id))
        styles = review._styled(table)._compute().ctx
        highlighted_rows = {row for (row, _column) in styles}
        self.assertEqual([table.iloc[row]["Unit"] for row in highlighted_rows], ["110"])

    def test_header_card_shows_saved_facts_and_the_source_chip(self):
        self.open_deal("fallowmere")
        text = self.page_text()
        self.assertIn('<span class="chip">from rent_roll.xlsx</span>', text)
        self.assertIn("12 units · 154,600 SF · Extracted", text)
        self.assertIn(">Needs Review</span>", text)

    def test_extracted_fields_say_how_many_units_were_read(self):
        self.open_deal("fallowmere")
        self.assertIn("12 of 12 units read", self.page_text())

    def test_deal_snapshot_is_calculated_and_never_guesses(self):
        self.open_deal("fallowmere")
        text = self.page_text()
        for label, value in (("Total SF", "154,600"), ("Units", "12"), ("Average rent / SF", "$8.84"),
                             ("Flagged units", "1"), ("Net operating income", "$1,244,311.44"),
                             ("Time in review", "Not measured yet")):
            self.assertIn(f'<div class="k">{label}</div>', text)
            self.assertIn(f'">{value}</div>', text)
        self.assertIn("Weighted avg lease term left", text)
        self.assertNotIn('<div class="k">Occupancy', text)
        self.assertNotIn('<div class="k">Cap rate', text)

    def test_deal_without_a_t12_says_needs_t12(self):
        self.open_deal("brindlewick")
        self.assertIn('<div class="v muted">Needs T-12</div>', self.page_text())

    def test_key_takeaways_are_shown(self):
        self.open_deal("fallowmere")
        text = self.page_text()
        self.assertIn("Harbor &amp; Pine Distribution is the largest tenant: 22,000 SF, 14.2% of the 154,600 SF total.", text)
        self.assertIn("Unit 110 is flagged: rent/SF is more than 2x the average of the other units.", text)
        self.assertIn("Each line is calculated from the rent roll rows, not written by the AI.", text)

    def test_where_this_came_from_names_the_document_rows_and_rule(self):
        self.open_deal("fallowmere")
        text = self.page_text()
        self.assertIn("12 rows extracted from rent_roll.xlsx (first sheet), source: Sample data.", text)
        self.assertIn("Flag on unit 110: validation rule rent_per_sf_above_2x_average (actual 20.33, limit 17.19).", text)
        self.assertIn("Accuracy has not been measured yet, so no match rate is shown.", text)

    def test_no_unmeasured_accuracy_claims_and_no_deploy_button(self):
        self.open_deal("fallowmere")
        text = self.page_text().lower()
        for claim in ("high confidence", "% matched", "96%"):
            self.assertNotIn(claim, text)
        self.assertNotIn("Deploy", [button.label for button in self.app.button])

    def test_narrative_buttons_exist_and_are_locked_without_a_draft(self):
        self.open_deal("fallowmere")
        labels = {key: self.app.button(key=key) for key in ("draft_flag", "draft_edit", "draft_approve")}
        self.assertEqual([b.label for b in labels.values()], ["Flag for producer", "Edit", "Approve"])
        self.assertTrue(all(button.disabled for button in labels.values()))
        self.assertEqual(self.app.button(key="draft_generate").label, "Generate draft")
        self.assertFalse(self.app.button(key="draft_generate").disabled)
        download = [d for d in self.app.get("download_button") if d.key == "review_download"][0]
        self.assertEqual(download.label, "Download")

    def test_link_jumps_to_the_documents_tab(self):
        self.open_deal("fallowmere")
        self.app.button(key="go_documents").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["deal_tabs"], "Documents :gray-badge[2]")

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

    def test_breadcrumb_shows_all_deals_then_the_deal_name(self):
        self.open_deal("brindlewick")
        self.assertEqual(self.app.button(key="back_to_deals").label, "All deals")
        self.assertIn('<span class="sep">›</span><span class="here">Brindlewick Retail Row (SAMPLE - fictional)</span>',
                      self.page_text())

    def test_back_button_returns_to_the_dashboard(self):
        self.open_deal("fallowmere")
        self.app.button(key="back_to_deals").click().run()
        self.assertIn("Needs your attention", self.page_text())


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
            "review_download",
        })
        text = self.page_text()
        self.assertIn("fallowmere_industrial_park_rent_roll.csv", text)
        self.assertIn("fallowmere_industrial_park_t12.xlsx", text)
        self.assertIn("Draft narrative: none yet", text)

    def test_deal_without_a_t12_only_offers_the_rent_roll(self):
        self.open_deal("brindlewick")
        self.assertEqual(set(self.downloads()), {"download_rent_roll_csv", "download_rent_roll_xlsx", "review_download"})
        self.assertIn("T-12: nothing saved for this deal yet.", self.page_text())

    def test_deal_with_no_numbers_offers_no_downloads(self):
        self.open_deal("quillhaven")
        self.assertFalse(self.app.exception)
        self.assertEqual(self.downloads(), {})

    def test_draft_download_appears_when_a_draft_exists(self):
        conn = db.get_connection(self.db_path)
        with conn:
            draft_id = conn.execute(
                "INSERT INTO drafts (deal_id, text) VALUES (?, 'Made-up draft text.')",
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


def all_deals_client(calls, answer, found=True, deals=(), sources=()):
    """A stand-in Gemini client for all-deals questions."""
    def generate_content(**kwargs):
        calls.append(kwargs["contents"])
        if isinstance(answer, Exception):
            raise answer
        text = json.dumps({"answer": answer, "found_in_deals": found,
                           "deals_used": list(deals), "sources": list(sources)})
        return type("Reply", (), {"text": text})()
    return type("Client", (), {"models": type("Models", (), {"generate_content": staticmethod(generate_content)})()})()


FALLOWMERE = "Fallowmere Industrial Park (SAMPLE - fictional)"


class TestFloatingAssistant(AppTestCase):
    def setUp(self):
        super().setUp()
        self.calls = []
        no_wait = mock.patch.object(gemini, "RETRY_WAIT_SECONDS", 0)
        no_wait.start()
        self.addCleanup(no_wait.stop)
        self.sign_in()

    def use_client(self, client):
        patcher = mock.patch.object(gemini, "get_client", lambda: client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def open_assistant(self):
        self.app.button(key="open_assistant").click().run()

    def test_button_is_on_the_dashboard_and_the_deal_page_but_not_the_login(self):
        self.assertEqual(self.app.button(key="open_assistant").label, "Ask the AI Teammate")
        self.open_deal("fallowmere")
        self.assertEqual(self.app.button(key="open_assistant").label, "Ask the AI Teammate")
        self.app.button(key="sign_out").click().run()
        self.assertNotIn("open_assistant", [button.key for button in self.app.button])

    def test_clicking_the_button_then_picking_all_deals_and_one_deal_never_errors(self):
        """The path that crashed in the browser: open the dialog, use the picker both ways."""
        self.use_client(all_deals_client(self.calls, AssertionError("Gemini must not be called just by looking")))
        self.open_assistant()
        self.assertFalse(self.app.exception)
        picker = self.app.selectbox(key="assistant_scope")
        self.assertEqual(picker.value, "All deals")
        self.assertIn("assistant_chat_input_all", [c.key for c in self.app.chat_input])
        for name, deal_id in self.deals.items():
            with self.subTest(name):
                self.app.selectbox(key="assistant_scope").set_value(deal_id).run()
                self.assertFalse(self.app.exception)
                self.assertIn(f"assistant_chat_input_{deal_id}", [c.key for c in self.app.chat_input])
        self.app.selectbox(key="assistant_scope").set_value("All deals").run()
        self.assertFalse(self.app.exception)
        self.assertIn("assistant_chat_input_all", [c.key for c in self.app.chat_input])
        self.assertEqual(self.calls, [])

    def test_the_dialog_uses_functions_that_really_exist(self):
        """Guards against a screen calling a helper another module does not have."""
        from app.views import ask_ai, assistant
        self.assertTrue(callable(ask_ai.render_chat))
        self.assertTrue(callable(ask_ai.get_answer))
        self.assertTrue(callable(assistant.render))

    def test_nothing_opens_and_gemini_is_not_called_until_the_button_is_clicked(self):
        self.use_client(all_deals_client(self.calls, AssertionError("must not be called")))
        self.assertEqual(len(self.app.selectbox), 0)
        self.open_assistant()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.calls, [])

    def test_picker_lists_all_deals_then_every_deal(self):
        self.open_assistant()
        picker = self.app.selectbox(key="assistant_scope")
        self.assertEqual(picker.value, "All deals")
        self.assertEqual(len(picker.options), 4)
        self.assertEqual(picker.options[0], "All deals")
        self.assertIn(FALLOWMERE, picker.options)

    def test_opened_from_a_deal_page_it_starts_on_that_deal(self):
        self.open_deal("brindlewick")
        self.open_assistant()
        self.assertEqual(self.app.selectbox(key="assistant_scope").value, self.deals["brindlewick"])
        self.assertIn(f"assistant_chat_input_{self.deals['brindlewick']}", [c.key for c in self.app.chat_input])

    def test_web_search_is_disabled(self):
        self.open_assistant()
        self.assertTrue(self.app.toggle(key="assistant_web_search_all").disabled)
        self.assertIn("Web search: coming in a later step.", self.page_text())

    def test_all_deals_answer_names_the_deals_it_used(self):
        self.use_client(all_deals_client(self.calls, "Only Fallowmere has an anomaly: unit 110 is flagged.",
                                         deals=[FALLOWMERE], sources=["Validation flags"]))
        self.open_assistant()
        self.app.chat_input(key="assistant_chat_input_all").set_value("Which deals have anomalies?").run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.calls), 1)
        reply = self.app.session_state["chat_all"][1]
        self.assertEqual(reply["label"], qa.LABEL_FROM_DEALS)
        self.assertEqual(reply["deals"], [FALLOWMERE])
        text = self.page_text()
        self.assertIn(">From these deals</span>", text)
        self.assertIn(f"Deals used: {FALLOWMERE}", text)
        for name in ("Fallowmere", "Quillhaven", "Brindlewick"):
            self.assertIn(name, self.calls[0])

    def test_all_deals_question_that_cannot_be_answered(self):
        self.use_client(all_deals_client(self.calls, "Probably around 6%.", found=False))
        self.open_assistant()
        self.app.chat_input(key="assistant_chat_input_all").set_value("What cap rate is typical?").run()
        reply = self.app.session_state["chat_all"][1]
        self.assertEqual(reply["label"], qa.LABEL_NOT_VERIFIED)
        self.assertEqual(reply["text"], "I don't have that in any of the deals.")

    def test_picking_one_deal_uses_the_deal_only_logic(self):
        self.use_client(reply_client(self.calls, "There are 5 units.", sources=("brindlewick_rent_roll.xlsx",)))
        self.open_assistant()
        self.app.selectbox(key="assistant_scope").set_value(self.deals["brindlewick"]).run()
        key = f"assistant_chat_input_{self.deals['brindlewick']}"
        self.app.chat_input(key=key).set_value("How many units?").run()
        reply = self.app.session_state[f"chat_{self.deals['brindlewick']}"][1]
        self.assertEqual(reply["label"], qa.LABEL_FROM_DEAL)
        self.assertIn("Pemberly Sock Emporium", self.calls[0])
        self.assertNotIn("Vantor Robotics Lab", self.calls[0])

    def test_assistant_and_the_ask_ai_tab_share_one_chat_per_deal(self):
        self.use_client(reply_client(self.calls, "There are 12 units."))
        self.open_deal("fallowmere")
        self.app.chat_input(key=f"chat_input_{self.deals['fallowmere']}").set_value("How many units?").run()
        self.open_assistant()
        self.assertEqual(len(self.app.session_state[f"chat_{self.deals['fallowmere']}"]), 2)
        self.assertEqual(self.page_text().count("There are 12 units."), 2)

    def test_quota_used_up_shows_a_friendly_message(self):
        self.use_client(all_deals_client(self.calls, daily_quota_error()))
        self.open_assistant()
        self.app.chat_input(key="assistant_chat_input_all").set_value("Which deals have anomalies?").run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.calls), 1)
        reply = self.app.session_state["chat_all"][1]
        self.assertEqual(reply["label"], "No answer")
        self.assertIn("daily quota is used up", reply["text"])


class NewDealAppTestCase(unittest.TestCase):
    """New-deal tests write to the database, so each one gets its own freshly seeded copy."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "app.db"
        self.uploads = Path(self.tmp.name) / "uploads"
        self.deals = seed.seed(self.db_path)
        self.calls = []
        from services import deals as deal_writes
        for target, name, value in ((db, "DB_PATH", self.db_path), (deal_writes, "UPLOAD_DIR", self.uploads),
                                    (gemini, "RETRY_WAIT_SECONDS", 0)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = AppTest.from_file(APP, default_timeout=20).run()
        self.app.button(key="sign_in_google").click().run()

    def use_gemini(self, reply):
        def generate_content(**kwargs):
            self.calls.append(kwargs["contents"])
            if isinstance(reply, Exception):
                raise reply
            return type("Reply", (), {"text": json.dumps(reply)})()
        client = type("Client", (), {"models": type("Models", (), {"generate_content": staticmethod(generate_content)})()})()
        patcher = mock.patch.object(gemini, "get_client", lambda: client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def rows(self, sql):
        conn = db.get_connection(self.db_path)
        result = [dict(row) for row in conn.execute(sql)]
        conn.close()
        return result

    def open_dialog(self, mode=None):
        self.app.button(key="new_deal").click().run()
        if mode:
            self.app.button_group(key="nd_mode").set_value(mode).run()
        self.assertFalse(self.app.exception)

    def deal_names(self):
        return [button.label for button in self.app.button if button.key.startswith("open_deal_")]

    def messages(self):
        return [m.value for kind in ("success", "warning", "error") for m in getattr(self.app, kind)]


class TestNewDealUpload(NewDealAppTestCase):
    def fill(self, name="Made-up Depot (test)", files=("rent_roll.xlsx",)):
        self.app.text_input(key="nd_name").set_value(name)
        self.app.selectbox(key="nd_type").set_value("Industrial")
        self.app.text_input(key="nd_location").set_value("Testville")
        sample = Path(APP).parent / "sample_data"
        if files:
            self.app.file_uploader(key="nd_files").set_value(
                [(name_, (sample / name_).read_bytes(), "application/octet-stream") for name_ in files])
        self.app.run()

    def test_button_opens_the_dialog_on_upload_and_calls_nothing(self):
        self.use_gemini(AssertionError("Gemini must not be called by opening the dialog"))
        self.open_dialog()
        self.assertEqual(self.app.button_group(key="nd_mode").value, "Upload files")
        self.assertEqual(self.app.file_uploader(key="nd_files").allowed_type, [".xlsx", ".csv"])
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.rows("SELECT id FROM deals")), 3)

    def test_uploading_a_rent_roll_creates_the_deal_and_reads_it(self):
        from tests.test_extraction import read_source_units
        self.use_gemini({"units": read_source_units()})
        self.open_dialog()
        self.fill(files=("rent_roll.xlsx", "t12.xlsx"))
        self.app.button(key="nd_create_upload").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.calls), 1)
        deal = self.rows("SELECT * FROM deals ORDER BY id DESC LIMIT 1")[0]
        self.assertEqual((deal["name"], deal["property_type"], deal["submarket"], deal["status"]),
                         ("Made-up Depot (test)", "Industrial", "Testville", "Needs Review"))
        self.assertEqual(self.rows(f"SELECT filename, source, status FROM documents WHERE deal_id = {deal['id']} ORDER BY id"),
                         [{"filename": "rent_roll.xlsx", "source": "Upload", "status": "Read"},
                          {"filename": "t12.xlsx", "source": "Upload", "status": "Received"}])
        self.assertIn("Made-up Depot (test)", self.deal_names())
        message = self.messages()[0]
        self.assertIn("rent_roll.xlsx: Read: 12 units, 1 flag.", message)
        self.assertIn("t12.xlsx: Saved, not read", message)
        self.assertEqual(len(self.app.file_uploader), 0)  # the dialog has closed

    def test_quota_used_up_still_creates_the_deal_and_says_so_kindly(self):
        self.use_gemini(daily_quota_error())
        self.open_dialog()
        self.fill()
        self.app.button(key="nd_create_upload").click().run()
        self.assertFalse(self.app.exception)
        deal = self.rows("SELECT * FROM deals ORDER BY id DESC LIMIT 1")[0]
        self.assertEqual((deal["name"], deal["status"]), ("Made-up Depot (test)", "Extracting"))
        self.assertEqual(self.rows(f"SELECT status FROM documents WHERE deal_id = {deal['id']}"), [{"status": "Received"}])
        self.assertIn("Made-up Depot (test)", self.deal_names())
        self.assertIn("daily quota is used up", self.app.warning[0].value)

    def test_name_and_a_file_are_required(self):
        self.use_gemini(AssertionError("must not be called"))
        self.open_dialog()
        self.fill(name="")
        self.app.button(key="nd_create_upload").click().run()
        self.assertIn("Give the deal a name.", self.messages())
        self.fill(name="Made-up Depot (test)", files=())
        self.app.file_uploader(key="nd_files").clear().run()
        self.app.button(key="nd_create_upload").click().run()
        self.assertIn("Add at least one file", self.messages()[0])
        self.assertEqual(len(self.rows("SELECT id FROM deals")), 3)
        self.assertEqual(self.calls, [])


DESCRIPTION = "Oakmere Depot is a 40,000 sf warehouse in Fort Worth with three tenants."


class TestNewDealDescribe(NewDealAppTestCase):
    REPLY = {"name": "Oakmere Depot", "property_type": "Industrial", "location": "Fort Worth",
             "facts": ["40,000 sf warehouse.", "Three tenants.", "Rent is about $9 per SF."]}

    def describe(self, text=DESCRIPTION):
        self.open_dialog("Describe it to the AI")
        self.app.text_area(key="nd_description").set_value(text).run()
        self.app.button(key="nd_draft_button").click().run()
        self.assertFalse(self.app.exception)

    def test_nothing_is_sent_until_draft_is_pressed(self):
        self.use_gemini(AssertionError("must not be called"))
        self.open_dialog("Describe it to the AI")
        self.app.text_area(key="nd_description").set_value(DESCRIPTION).run()
        self.assertEqual(self.calls, [])

    def test_draft_is_shown_as_an_editable_form_and_nothing_is_saved_yet(self):
        self.use_gemini(self.REPLY)
        self.describe()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.app.text_input(key="ndf_name_1").value, "Oakmere Depot")
        self.assertEqual(self.app.selectbox(key="ndf_type_1").value, "Industrial")
        self.assertEqual(self.app.text_input(key="ndf_location_1").value, "Fort Worth")
        self.assertEqual(self.app.text_area(key="ndf_notes_1").value, "40,000 sf warehouse.\nThree tenants.")
        self.assertIn("The AI left out", self.app.warning[0].value)
        self.assertIn("$9", self.app.warning[0].value)
        self.assertEqual(len(self.rows("SELECT id FROM deals")), 3)
        self.assertEqual(self.rows("SELECT id FROM deal_notes"), [])

    def test_the_person_can_edit_the_draft_before_creating(self):
        self.use_gemini(self.REPLY)
        self.describe()
        self.app.text_input(key="ndf_name_1").set_value("Oakmere Depot (edited)")
        self.app.text_area(key="ndf_notes_1").set_value("Three tenants, one leaving.")
        submit = [b for b in self.app.button if b.label == "Create deal"][0]
        submit.click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.calls), 1)
        deal = self.rows("SELECT * FROM deals ORDER BY id DESC LIMIT 1")[0]
        self.assertEqual((deal["name"], deal["property_type"], deal["submarket"], deal["status"]),
                         ("Oakmere Depot (edited)", "Industrial", "Fort Worth", "New"))
        self.assertEqual(self.rows("SELECT deal_id, text, source FROM deal_notes"),
                         [{"deal_id": deal["id"], "text": "Three tenants, one leaving.", "source": "Typed"}])
        self.assertIn("Oakmere Depot (edited)", self.deal_names())
        self.assertIn("Created 'Oakmere Depot (edited)'", self.app.success[0].value)

    def test_unknowns_are_left_blank_and_a_name_is_required(self):
        self.use_gemini({"name": None, "property_type": None, "location": None, "facts": []})
        self.describe("Something on the east side, more later.")
        self.assertEqual(self.app.text_input(key="ndf_name_1").value, "")
        self.assertIsNone(self.app.selectbox(key="ndf_type_1").value)
        self.assertEqual(self.app.text_input(key="ndf_location_1").value, "")
        [b for b in self.app.button if b.label == "Create deal"][0].click().run()
        self.assertIn("Give the deal a name.", self.messages())
        self.assertEqual(len(self.rows("SELECT id FROM deals")), 3)

    def test_quota_used_up_shows_a_friendly_message_and_an_empty_form(self):
        self.use_gemini(daily_quota_error())
        self.describe()
        self.assertEqual(len(self.calls), 1)
        self.assertIn("daily quota is used up", self.app.warning[0].value)
        self.assertEqual(self.app.text_input(key="ndf_name_1").value, "")
        self.assertEqual(len(self.rows("SELECT id FROM deals")), 3)

    def test_empty_description_is_not_sent(self):
        self.use_gemini(AssertionError("must not be called"))
        self.describe("   ")
        self.assertEqual(self.calls, [])
        self.assertIn("Describe the deal first.", self.messages())


GOOD_DRAFT = "The 12 units total 154,600 SF at an average rent of $8.84 per SF."


class TestDraftNarrative(NewDealAppTestCase):
    def use_text(self, reply):
        def generate_content(**kwargs):
            self.calls.append(kwargs["contents"])
            if isinstance(reply, Exception):
                raise reply
            return type("Reply", (), {"text": reply})()
        client = type("Client", (), {"models": type("Models", (), {"generate_content": staticmethod(generate_content)})()})()
        patcher = mock.patch.object(gemini, "get_client", lambda: client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def open_fallowmere(self):
        self.app.button(key=f"open_deal_{self.deals['fallowmere']}").click().run()

    def generate(self, reply):
        self.use_text(reply)
        self.open_fallowmere()
        self.app.button(key="draft_generate").click().run()
        self.assertFalse(self.app.exception)
        drafts = self.rows("SELECT * FROM drafts ORDER BY id DESC")
        return drafts[0] if drafts else None

    def box(self, draft):
        return self.app.text_area(key=f"draft_text_{draft['id']}")

    def page(self):
        parts = [e.value for kind in ("markdown", "caption", "error", "warning") for e in getattr(self.app, kind)]
        return "\n".join(part for part in parts if "<style>" not in part)

    def test_opening_the_review_tab_never_calls_gemini(self):
        self.use_text(AssertionError("must not be called"))
        self.open_fallowmere()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.rows("SELECT id FROM drafts"), [])

    def test_generate_uses_one_request_and_shows_a_labelled_unsent_draft(self):
        draft = self.generate(GOOD_DRAFT)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual((draft["status"], draft["edited"]), ("Generated, not sent", 0))
        self.assertIn("Flagged units (110) need confirmation", draft["text"])
        page = self.page()
        self.assertIn("AI-drafted - edit anything before it goes out", page)
        self.assertIn("Generated, not sent", page)
        self.assertIn("Checked: every number in this draft appears in the deal data", page)
        self.assertEqual(self.box(draft).value, draft["text"])
        self.assertTrue(self.box(draft).disabled)
        self.assertFalse(self.app.button(key="draft_approve").disabled)

    def test_a_draft_with_an_invented_figure_warns_and_cannot_be_approved(self):
        draft = self.generate("The property is worth about $19,000,000 at a 6.5% cap rate.")
        self.assertIn("figures that are not in the deal data: 6.5, 19,000,000.", self.app.error[0].value)
        self.assertTrue(self.app.button(key="draft_approve").disabled)
        self.assertEqual(draft["status"], "Generated, not sent")

    def test_editing_out_the_figure_unlocks_approve_and_a_person_approves(self):
        draft = self.generate("The property is worth about $19,000,000.")
        self.app.button(key="draft_edit").click().run()
        self.assertFalse(self.box(draft).disabled)
        self.assertEqual(self.app.button(key="draft_edit").label, "Save edits")
        self.assertTrue(self.app.button(key="draft_approve").disabled)  # not while editing
        self.box(draft).set_value("The 12 units total 154,600 SF. Unit 110 needs confirmation.").run()
        self.app.button(key="draft_edit").click().run()
        saved = self.rows("SELECT * FROM drafts")[0]
        self.assertEqual((saved["text"], saved["edited"]), ("The 12 units total 154,600 SF. Unit 110 needs confirmation.", 1))
        self.assertIn("AI-drafted, then edited by a person", self.page())
        self.assertEqual(len(self.app.error), 0)
        self.app.button(key="draft_approve").click().run()
        self.assertEqual(self.rows("SELECT status FROM drafts"), [{"status": "Approved"}])
        self.assertTrue(self.app.button(key="draft_approve").disabled)
        self.assertEqual(len(self.calls), 1)  # editing and approving never call the AI

    def test_flag_for_producer(self):
        self.generate(GOOD_DRAFT)
        self.app.button(key="draft_flag").click().run()
        self.assertEqual(self.rows("SELECT status FROM drafts"), [{"status": "Flagged for producer"}])
        self.assertIn("Flagged for producer", self.page())

    def test_download_becomes_the_draft_with_its_status(self):
        self.generate(GOOD_DRAFT)
        download = [d for d in self.app.get("download_button") if d.key == "review_download"][0]
        self.assertEqual(download.label, "Download")
        self.assertIn("fallowmere_industrial_park_draft_narrative.txt", download.help)

    def test_quota_used_up_shows_a_friendly_message_and_saves_nothing(self):
        draft = self.generate(daily_quota_error())
        self.assertIsNone(draft)
        self.assertIn("daily quota is used up", self.app.warning[0].value)
        self.assertIn("Nothing was saved", self.app.warning[0].value)

    def test_generating_again_adds_a_new_draft_and_keeps_the_old_one(self):
        self.generate(GOOD_DRAFT)
        self.assertEqual(self.app.button(key="draft_generate").label, "Generate a new draft")
        self.app.button(key="draft_generate").click().run()
        self.assertEqual(len(self.rows("SELECT id FROM drafts")), 2)
        self.assertEqual(len(self.calls), 2)


class TestMarketResearch(NewDealAppTestCase):
    """Run research on the deal page, with every source simulated (tests/connection_fakes.py)."""

    def setUp(self):
        super().setUp()
        self.queries, self.fetches = [], []
        from tests.test_connections import with_keys
        with_keys(self)

    def use(self, results=None, reply=None, fetch=None, grounded=None):
        from services import connections
        from tests import connection_fakes, research_fakes
        adapters = connection_fakes.adapters(
            fetch=fetch or connection_fakes.fake_fetch(self.fetches),
            search=research_fakes.fake_search(results, self.queries),
            research_client=research_fakes.fake_gemini(reply, self.calls),
            grounded_client=connection_fakes.fake_grounded_client(self.calls, grounded))
        patcher = mock.patch.object(connections, "all_adapters", lambda: adapters)
        patcher.start()
        self.addCleanup(patcher.stop)

    def open_fallowmere(self):
        self.app.button(key=f"open_deal_{self.deals['fallowmere']}").click().run()

    def run_research(self, force=False):
        self.open_fallowmere()
        if force:
            self.app.checkbox(key="research_force").check().run()
        self.app.button(key="research_run").click().run()
        self.assertFalse(self.app.exception)

    def page(self):
        parts = [e.value for kind in ("markdown", "caption", "warning") for e in getattr(self.app, kind)]
        return "\n".join(part for part in parts if "<style>" not in part)

    def finding_id(self, connection_id, topic):
        return self.rows(f"SELECT id FROM research_findings WHERE topic = '{topic}' AND connection_id = '{connection_id}'")[0]["id"]

    def test_opening_the_review_tab_calls_nothing(self):
        self.use(results=AssertionError("must not search"), reply=AssertionError("must not be called"))
        self.open_fallowmere()
        self.assertEqual((self.queries, self.calls, self.fetches), ([], [], []))
        page = self.page()
        self.assertIn("Not run yet", page)
        self.assertIn("About the Industrial market in Alliance, Fort Worth, TX, not about this property", page)

    def test_run_research_calls_each_switched_on_source_once_and_reports_each(self):
        self.use()
        self.run_research()
        self.assertEqual(len(self.queries), 4)                       # Tavily
        self.assertEqual(len(self.calls), 2)                         # 1 grounded search + 1 Tavily summary
        self.assertEqual(len(self.fetches), 4)                       # FRED 2, BLS 1, Census 1
        page = self.page()
        for line in ("Web search (Gemini + Google Search): 2 finding(s)", "Web search (Tavily): 4 finding(s)",
                     "FRED (St. Louis Fed): 1 finding(s)", "BLS (Bureau of Labor Statistics): 1 finding(s)",
                     "U.S. Census Bureau: 2 finding(s)"):
            self.assertIn(line, page)
        for topic in ("Vacancy", "Asking rent trend", "New supply", "Employment and demand", "Population and income"):
            self.assertIn(f'<div class="finding-topic"><span>{topic}</span>', page)
        self.assertIn('<span class="chip">FRED (St. Louis Fed)</span>', page)
        self.assertIn("the page's own text was not available to check it", page)
        self.assertNotIn("SIMULATED", page)

    def test_sources_that_disagree_across_connections_are_tagged(self):
        self.use()
        self.run_research()
        page = self.page()
        self.assertIn('<span>Vacancy</span><span class="pill flag">Sources disagree</span>', page)
        for figure in ("6.2%", "7.5%", "7.0%"):
            self.assertIn(f'<span class="figure">{figure}</span>', page)

    def test_one_source_failing_shows_source_unavailable_and_the_rest_still_work(self):
        from services import connections
        self.use(fetch=connection_fakes_failing())
        self.run_research()
        page = self.page()
        self.assertIn("FRED (St. Louis Fed): Source unavailable: The service could not be reached.", page)
        self.assertIn("Web search (Tavily): 4 finding(s)", page)

    def test_a_second_run_reuses_recent_results_unless_refreshed(self):
        self.use()
        self.run_research()
        self.app.button(key="research_run").click().run()
        self.assertIn("FRED (St. Louis Fed): used results from the last 24 hours", self.page())
        self.assertEqual(len(self.fetches), 4)
        self.app.checkbox(key="research_force").check().run()
        self.app.button(key="research_run").click().run()
        self.assertEqual(len(self.fetches), 8)

    def test_accept_and_dismiss_and_only_accepted_findings_reach_the_narrative(self):
        from services import drafting
        self.use()
        self.run_research()
        deal_id = self.deals["fallowmere"]
        self.assertIn("None accepted", drafting.deal_facts(deal_id, self.db_path)[0])
        self.app.button(key=f"accept_finding_{self.finding_id('fred', 'Employment and demand')}").click().run()
        facts = drafting.deal_facts(deal_id, self.db_path)[0]
        self.assertIn("FRED, St. Louis Fed (Tier 1, 2026-08-01): 4.4%", facts)
        dismiss = self.finding_id("web_search_tavily", "Vacancy")
        self.app.button(key=f"dismiss_finding_{dismiss}").click().run()
        self.assertEqual(self.rows(f"SELECT status FROM research_findings WHERE id = {dismiss}"), [{"status": "dismissed"}])

    def test_simulated_findings_show_a_chip_and_cannot_be_accepted(self):
        from services import connections
        connections.set_enabled("demo_costar", True, self.db_path)
        self.use()
        self.run_research()
        page = self.page()
        self.assertIn('<span class="chip simulated">SIMULATED</span>', page)
        demo_id = self.finding_id("demo_costar", "Vacancy")
        self.assertTrue(self.app.button(key=f"accept_finding_{demo_id}").disabled)
        self.assertIn("SIMULATED SAMPLE, NOT REAL DATA", page)

    def test_nothing_found_says_so(self):
        from services import connections
        connections.set_enabled("web_search_gemini", False, self.db_path)
        for source in ("fred", "bls", "census"):
            connections.set_enabled(source, False, self.db_path)
        self.use(results={}, reply=AssertionError("must not be called"))
        self.run_research()
        self.assertEqual(self.page().count("No reliable public sources found."), 4)

    def test_import_a_market_report(self):
        from tests import research_fakes
        self.use()
        reply = {"findings": [{"topic": "Vacancy", "summary": "Vacancy was 6.4% in Q3 2026.", "figure": "6.4%",
                               "metric": "vacancy rate", "period": "Q3 2026"}]}
        patcher = mock.patch.object(gemini, "get_client", lambda: research_fakes.fake_gemini(reply, self.calls))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.open_fallowmere()
        deal_id = self.deals["fallowmere"]
        self.app.file_uploader(key=f"import_file_{deal_id}").set_value(
            ("dfw.csv", b"Metric,Value\nVacancy rate,6.4%\nAs of,Q3 2026\n", "text/csv")).run()
        self.app.text_input(key=f"import_publisher_{deal_id}").set_value("Made-up Brokerage")
        self.app.selectbox(key=f"import_tier_{deal_id}").set_value(2).run()
        self.app.button(key=f"import_go_{deal_id}").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.calls), 1)
        self.assertIn("Imported dfw.csv: 1 finding(s).", self.page())
        self.assertIn("dfw.csv (imported, Made-up Brokerage)", self.page())

    def test_web_search_in_chat_stays_disabled(self):
        self.open_fallowmere()
        self.assertTrue(self.app.toggle(key=f"web_search_{self.deals['fallowmere']}").disabled)


def connection_fakes_failing():
    from services import connections
    from tests import connection_fakes
    fetch = connection_fakes.fake_fetch()

    def failing(url, params=None, body=None, **kwargs):
        if "stlouisfed" in url:
            raise connections.SourceError("The service could not be reached.")
        return fetch(url, params, body)
    return failing


class TestRecommendationsTab(NewDealAppTestCase):
    def setUp(self):
        super().setUp()
        from services import connections
        from tests import connection_fakes
        from tests.test_connections import with_keys
        with_keys(self)
        connections.set_enabled("demo_costar", True, self.db_path)
        connections.run_research({"id": self.deals["fallowmere"], "property_type": "Industrial",
                                  "submarket": "Alliance, Fort Worth, TX"}, self.db_path, adapters=connection_fakes.adapters())
        self.findings = {(r["connection_id"], r["topic"]): r["id"] for r in self.rows(
            "SELECT id, connection_id, topic FROM research_findings WHERE simulated = 0")}

    def use_ai(self, items):
        self.use_gemini({"recommendations": items})

    def open_fallowmere(self):
        self.app.button(key=f"open_deal_{self.deals['fallowmere']}").click().run()

    def page(self):
        return "\n".join(e.value for kind in ("markdown", "caption", "info") for e in getattr(self.app, kind)
                         if "<style>" not in e.value)

    def test_opening_calls_nothing_and_shows_the_banner_and_rule_cards(self):
        self.use_gemini(AssertionError("must not be called"))
        self.open_fallowmere()
        self.assertEqual(self.calls, [])
        page = self.page()
        self.assertIn("AI suggestions. A person decides.", page)
        self.assertIn("Confirm unit 110 with the property manager before pricing", page)
        self.assertIn('<span class="pill flag">High priority</span>', page)
        self.assertIn("4 leases (44,700 SF, 28.9% of total SF) end in the next 12 months", page)
        self.assertIn("Rule: Validation rule rent_per_sf_above_2x_average", page)
        self.assertIn('<span class="evidence">rent_roll.xlsx', page)
        self.assertIn("From the deal&#x27;s data", page)

    def test_simulated_findings_are_listed_as_not_used(self):
        self.open_fallowmere()
        page = self.page()
        self.assertIn("Not used: simulated findings", page)
        self.assertIn('<span class="chip simulated">SIMULATED</span> CoStar', page)

    def test_generate_adds_checked_ai_cards_and_says_how_many_were_removed(self):
        fred = self.findings[("fred", "Employment and demand")]
        tavily = self.findings[("web_search_tavily", "Vacancy")]
        self.use_ai([
            {"title": "Check labour supply", "why": "Unemployment was 4.4%.", "next_step": "Ask leasing teams about hiring.", "finding_ids": [fred]},
            {"title": "Price against both vacancy reports", "why": "Reports give 6.2% and 7.5%.", "next_step": "Show both figures.", "finding_ids": [tavily]},
            {"title": "Made-up", "why": "Rents will rise 9%.", "next_step": "Raise rents.", "finding_ids": [fred]},
            {"title": "Cites nothing real", "why": "Something.", "next_step": "Something.", "finding_ids": [99999]},
        ])
        self.open_fallowmere()
        self.app.button(key="rec_generate").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.calls), 1)
        page = self.page()
        self.assertIn("2 suggestions added. 2 suggestions removed: could not be verified.", page)
        self.assertIn("Check labour supply", page)
        self.assertNotIn("Rents will rise 9%", page)
        self.assertIn("From market research", page)
        self.assertIn('<span class="evidence tier1"><b>4.4%</b> · FRED, St. Louis Fed · Tier 1 · 2026-08-01 · FRED (St. Louis Fed)</span>', page)
        self.assertIn('<span class="pill flag">Sources disagree</span>', page)
        self.assertIn("Priority from the strongest source cited", page)

    def test_accept_dismiss_and_add_to_notes(self):
        self.open_fallowmere()
        self.app.button(key="rec_accept_flag_110_rent_per_sf_above_2x_average").click().run()
        self.app.button(key="rec_dismiss_expiring_12_24").click().run()
        self.app.button(key="rec_note_expiring_0_12").click().run()
        self.assertFalse(self.app.exception)
        rows = {r["rule_key"]: r["status"] for r in self.rows("SELECT rule_key, status FROM recommendations")}
        self.assertEqual(rows, {"flag:110:rent_per_sf_above_2x_average": "accepted", "expiring:12-24": "dismissed"})
        note = self.rows("SELECT text, source FROM deal_notes")[0]
        self.assertTrue(note["text"].startswith("Recommendation: Check renewals for 4 leases ending in the next 12 months"))
        self.assertEqual(note["source"], "Typed")
        self.assertIn("Added to the deal's notes", self.page())
        self.assertEqual(self.calls, [])

    def test_accepted_ones_show_on_the_review_tab(self):
        self.open_fallowmere()
        self.app.button(key="rec_accept_flag_110_rent_per_sf_above_2x_average").click().run()
        self.assertIn("Accepted recommendations", self.page())
        self.assertIn("<li>Confirm unit 110 with the property manager before pricing", self.page())

    def test_without_real_findings_generate_explains_and_calls_nothing(self):
        conn = db.get_connection(self.db_path)
        with conn:
            conn.execute("DELETE FROM research_findings WHERE simulated = 0")
        conn.close()
        self.use_gemini(AssertionError("must not be called"))
        self.open_fallowmere()
        self.app.button(key="rec_generate").click().run()
        self.assertIn("Run market research first", self.page())
        self.assertEqual(self.calls, [])

    def test_quota_used_up_is_friendly(self):
        self.use_gemini(daily_quota_error())
        self.open_fallowmere()
        self.app.button(key="rec_generate").click().run()
        self.assertFalse(self.app.exception)
        self.assertIn("daily quota is used up", self.page())


class TestConnectionsPage(NewDealAppTestCase):
    def setUp(self):
        super().setUp()
        from tests.test_connections import with_keys
        with_keys(self, {"GEMINI_API_KEY": "test-gemini", "FRED_API_KEY": "test-fred"})

    def open_page(self):
        self.app.button(key="nav_connections").click().run()
        self.assertFalse(self.app.exception)

    def page(self):
        return "\n".join(e.value for kind in ("markdown", "caption", "info") for e in getattr(self.app, kind)
                         if "<style>" not in e.value)

    def test_every_source_has_a_card_with_status_and_what_it_provides(self):
        self.open_page()
        self.assertEqual([h.value for h in self.app.header], ["Connections"])
        page = self.page()
        for name in ("Web search (Gemini + Google Search)", "Web search (Tavily)", "FRED (St. Louis Fed)",
                     "BLS (Bureau of Labor Statistics)", "U.S. Census Bureau", "Import a market report",
                     "LinkedIn", "CoStar", "LoopNet / Crexi", "Zillow", "Redfin"):
            self.assertIn(name, page)
        self.assertIn('<span class="pill approved">Connected</span>', page)
        self.assertIn('<span class="pill needs-review">Not set up</span>', page)
        self.assertIn('<span class="pill other">Needs licensed access</span>', page)
        self.assertIn("Free key: data.bls.gov/registrationEngine, then add BLS_API_KEY=... to .env.", page)
        self.assertIn("Needs licensed access - in production, CBRE's own license would connect here.", page)
        self.assertIn("Last used: never", page)

    def test_keys_are_never_shown(self):
        self.open_page()
        everything = self.page() + " ".join(str(w.value) for w in self.app.text_input)
        for key in ("test-gemini", "test-fred"):
            self.assertNotIn(key, everything)

    def test_how_sources_are_used_note(self):
        self.open_page()
        page = self.page()
        self.assertIn("How sources are used", page)
        self.assertIn("No website is ever scraped", page)
        self.assertIn("They can never be accepted, cited by the AI, or counted as research.", page)

    def test_the_broker_can_use_every_switch(self):
        self.open_page()
        switches = [t for t in self.app.toggle if t.key.startswith("switch_")]
        self.assertEqual(len(switches), 10)
        self.assertFalse(any(t.disabled for t in switches))
        self.assertNotIn("Administrator", self.page())

    def test_the_broker_switches_a_source_and_it_is_saved(self):
        self.open_page()
        self.assertFalse(self.app.toggle(key="switch_fred").disabled)
        self.app.toggle(key="switch_fred").set_value(False).run()
        self.app.toggle(key="switch_demo_costar").set_value(True).run()
        self.assertFalse(self.app.exception)
        rows = {r["id"]: r["enabled"] for r in self.rows("SELECT id, enabled FROM connections")}
        self.assertEqual((rows["fred"], rows["demo_costar"]), (0, 1))
        self.assertIn('<span class="pill simulated">Demo</span>', self.page())

    def test_connect_on_a_licensed_source_explains_instead_of_pretending(self):
        self.open_page()
        self.app.button(key="connect_demo_zillow").click().run()
        message = [i.value for i in self.app.info if "Zillow cannot be connected" in i.value]
        self.assertEqual(len(message), 1)
        self.assertIn("never scraped", message[0])
        self.assertEqual(self.rows("SELECT id FROM connections WHERE id = 'demo_zillow'"), [])

    def test_viewing_the_page_changes_nothing(self):
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        self.open_page()
        self.app.button(key="connect_demo_zillow").click().run()
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).hexdigest(), before)


AUDIO = b"RIFF" + b"\x00" * 4000  # made-up bytes standing in for a short recording


class TestVoice(NewDealAppTestCase):
    """The recorder, driven through its upload box (the test tool cannot press a microphone)."""

    def use_transcript(self, reply):
        """Simulate Gemini: audio requests get the transcript, text requests get a chat answer."""
        def generate_content(**kwargs):
            self.calls.append(kwargs["contents"])
            if isinstance(kwargs["contents"], list):
                if isinstance(reply, Exception):
                    raise reply
                return type("Reply", (), {"text": reply})()
            return type("Reply", (), {"text": json.dumps({"answer": "There are 12 units.", "found_in_deal": True,
                                                         "sources": ["rent_roll.xlsx"]})})()
        client = type("Client", (), {"models": type("Models", (), {"generate_content": staticmethod(generate_content)})()})()
        patcher = mock.patch.object(gemini, "get_client", lambda: client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def open_fallowmere(self):
        self.app.button(key=f"open_deal_{self.deals['fallowmere']}").click().run()
        return f"chat_{self.deals['fallowmere']}"

    def upload_and_transcribe(self, key, filename="memo.wav", data=AUDIO):
        self.app.file_uploader(key=f"{key}_audio_0").set_value((filename, data, "audio/wav")).run()
        self.app.button(key=f"{key}_transcribe").click().run()
        self.assertFalse(self.app.exception)

    def audio_calls(self):
        return [call for call in self.calls if isinstance(call, list)]

    def test_recorder_shows_the_privacy_notice_and_sends_nothing_by_itself(self):
        self.use_transcript(AssertionError("must not be called"))
        key = self.open_fallowmere()
        captions = [caption.value for caption in self.app.caption]
        self.assertIn("Audio is sent to Gemini for transcription and is not saved.", captions)
        self.assertTrue(self.app.button(key=f"{key}_transcribe").disabled)
        self.app.file_uploader(key=f"{key}_audio_0").set_value(("memo.wav", AUDIO, "audio/wav")).run()
        self.assertFalse(self.app.button(key=f"{key}_transcribe").disabled)
        self.assertEqual(self.calls, [])

    def test_audio_box_accepts_mp3_m4a_and_wav(self):
        key = self.open_fallowmere()
        self.assertEqual(self.app.file_uploader(key=f"{key}_audio_0").allowed_type, [".mp3", ".m4a", ".wav"])

    def test_transcript_is_shown_for_checking_before_anything_is_done_with_it(self):
        self.use_transcript("How many units are in the building")
        key = self.open_fallowmere()
        self.upload_and_transcribe(key)
        box = self.app.text_area(key=f"{key}_text_0")
        self.assertEqual(box.label, "AI transcript - please check it")
        self.assertEqual(box.value, "How many units are in the building")
        self.assertEqual(len(self.audio_calls()), 1)
        self.assertEqual(len(self.calls), 1)  # transcribed, but not yet asked
        self.assertEqual(self.app.session_state[key], [])
        self.assertEqual(self.rows("SELECT id FROM deal_notes"), [])

    def test_use_as_my_message_sends_the_edited_text_to_the_chat(self):
        self.use_transcript("How many units are in the building")
        key = self.open_fallowmere()
        self.upload_and_transcribe(key)
        self.app.text_area(key=f"{key}_text_0").set_value("How many units are in this building?")
        self.app.button(key=f"{key}_use").click().run()
        self.assertFalse(self.app.exception)
        messages = self.app.session_state[key]
        self.assertEqual(messages[0], {"role": "user", "text": "How many units are in this building?"})
        self.assertEqual(messages[1]["label"], qa.LABEL_FROM_DEAL)
        self.assertEqual(len(self.calls), 2)  # one transcription, one chat answer
        self.assertIn("How many units are in this building?", self.calls[1])

    def test_save_as_a_note_stores_the_edited_transcript_and_no_audio(self):
        self.use_transcript("Owner wants to sell by quarter two")
        key = self.open_fallowmere()
        self.upload_and_transcribe(key)
        self.app.text_area(key=f"{key}_text_0").set_value("Owner wants to sell by Q2.")
        self.app.button(key=f"{key}_save_note").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.rows("SELECT deal_id, text, source FROM deal_notes"),
                         [{"deal_id": self.deals["fallowmere"], "text": "Owner wants to sell by Q2.", "source": "Recording"}])
        self.assertEqual(len(self.calls), 1)  # saving a note does not ask the AI anything
        self.assertNotIn(AUDIO, self.db_path.read_bytes())
        self.assertFalse(self.uploads.exists())  # the audio file was not written to the uploads folder
        self.assertIn("Owner wants to sell by Q2.", "\n".join(m.value for m in self.app.markdown))

    def test_after_use_the_recorder_is_cleared_so_audio_cannot_be_sent_twice(self):
        self.use_transcript("How many units")
        key = self.open_fallowmere()
        self.upload_and_transcribe(key)
        self.app.button(key=f"{key}_use").click().run()
        self.assertTrue(self.app.button(key=f"{key}_transcribe").disabled)
        self.assertEqual(self.app.file_uploader(key=f"{key}_audio_1").value, None)

    def test_friendly_messages_for_each_problem(self):
        cases = {
            "empty recording": ("memo.wav", b"RIFF", "anything", "The recording is empty"),
            "no speech": ("memo.wav", AUDIO, "NO_SPEECH", "No speech was heard"),
            "quota used up": ("memo.wav", AUDIO, daily_quota_error(), "daily quota is used up"),
            "rate limited": ("memo.wav", AUDIO, gemini_error(429, "RESOURCE_EXHAUSTED"), "busy or rate-limited"),
            "unexpected failure": ("memo.wav", AUDIO, RuntimeError("network down"), "could not be transcribed"),
        }
        for name, (filename, data, reply, expected) in cases.items():
            with self.subTest(name):
                self.calls.clear()
                self.use_transcript(reply)
                self.app = AppTest.from_file(APP, default_timeout=20).run()
                self.app.button(key="sign_in_google").click().run()
                key = self.open_fallowmere()
                self.upload_and_transcribe(key, filename, data)
                self.assertIn(expected, self.app.warning[0].value)
                self.assertNotIn("network down", self.app.warning[0].value)
                self.assertNotIn(f"{key}_text_0", [area.key for area in self.app.text_area])

    def test_too_large_a_file_is_refused_without_calling_gemini(self):
        self.use_transcript(AssertionError("must not be called"))
        key = self.open_fallowmere()
        with mock.patch.object(transcribe, "MAX_AUDIO_BYTES", 3000):
            self.upload_and_transcribe(key)
        self.assertIn("too large", self.app.warning[0].value)
        self.assertEqual(self.calls, [])

    def test_assistant_dialog_has_the_recorder_and_no_note_button_on_all_deals(self):
        self.use_transcript("Which deals have anomalies")
        self.app.button(key="open_assistant").click().run()
        self.upload_and_transcribe("assistant_chat_all")
        keys = [button.key for button in self.app.button]
        self.assertIn("assistant_chat_all_use", keys)
        self.assertNotIn("assistant_chat_all_save_note", keys)

    def test_new_deal_describe_box_takes_the_transcript_as_the_description(self):
        self.use_transcript("Oakmere Depot is a warehouse in Fort Worth")
        self.app.button(key="new_deal").click().run()
        self.app.button_group(key="nd_mode").set_value("Describe it to the AI").run()
        self.upload_and_transcribe("nd")
        self.assertEqual(self.app.button(key="nd_use").label, "Use as my description")
        self.assertNotIn("nd_save_note", [button.key for button in self.app.button])
        self.app.button(key="nd_use").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.text_area(key="nd_description").value, "Oakmere Depot is a warehouse in Fort Worth")
        self.assertEqual(len(self.calls), 1)  # transcribed only; no draft was requested
        self.assertEqual(len(self.rows("SELECT id FROM deals")), 3)


class TestNotes(NewDealAppTestCase):
    def open_deal(self, name):
        self.app.button(key=f"open_deal_{self.deals[name]}").click().run()

    def test_typed_note_is_saved_and_shown_as_written(self):
        self.use_gemini(AssertionError("notes never call the AI"))
        self.open_deal("fallowmere")
        self.assertIn("Notes", [h.value for h in self.app.subheader])
        deal_id = self.deals["fallowmere"]
        self.app.text_area(key=f"new_note_{deal_id}").set_value("Seller prefers a quick close.\nCall back Friday.").run()
        self.app.button(key=f"save_note_{deal_id}").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.rows("SELECT deal_id, text, source FROM deal_notes"),
                         [{"deal_id": deal_id, "text": "Seller prefers a quick close.\nCall back Friday.", "source": "Typed"}])
        page = "\n".join(m.value for m in self.app.markdown)
        self.assertIn("Seller prefers a quick close.\nCall back Friday.", page)
        self.assertIn(">Typed</span>", page)
        self.assertEqual(self.app.text_area(key=f"new_note_{deal_id}").value, "")
        self.assertEqual(self.calls, [])

    def test_an_empty_note_is_not_saved(self):
        self.open_deal("fallowmere")
        self.app.button(key=f"save_note_{self.deals['fallowmere']}").click().run()
        self.assertEqual(self.rows("SELECT id FROM deal_notes"), [])

    def test_notes_show_on_a_deal_with_no_numbers_and_only_on_their_own_deal(self):
        from services import deals as deal_writes
        deal_writes.add_note(self.deals["quillhaven"], "Waiting on the rent roll <b>from</b> the owner.", "Recording", self.db_path)
        self.open_deal("quillhaven")
        page = "\n".join(m.value for m in self.app.markdown)
        self.assertIn("Waiting on the rent roll &lt;b&gt;from&lt;/b&gt; the owner.", page)  # shown as text, not as HTML
        self.assertIn(">Recording</span>", page)
        self.app.button(key="back_to_deals").click().run()
        self.open_deal("fallowmere")
        self.assertNotIn("Waiting on the rent roll", "\n".join(m.value for m in self.app.markdown))


class TestResolveFlags(NewDealAppTestCase):
    def open_fallowmere(self):
        self.app.button(key=f"open_deal_{self.deals['fallowmere']}").click().run()

    def flag(self):
        return self.rows("SELECT * FROM flags WHERE unit_number = '110' ORDER BY id")[0]

    def page(self):
        return "\n".join(e.value for kind in ("markdown", "caption", "success", "warning", "error")
                         for e in getattr(self.app, kind) if "<style>" not in e.value)

    def test_confirm_needs_a_reason_and_a_note_and_changes_no_data(self):
        self.use_gemini(AssertionError("confirming never calls the AI"))
        self.open_fallowmere()
        flag_id, before = self.flag()["id"], self.rows("SELECT * FROM rent_roll_units")
        self.app.button(key=f"confirm_btn_{flag_id}").click().run()
        key = f"confirm_{flag_id}"
        self.assertEqual(self.app.button_group(key=f"{key}_reason").options,
                         ["Special lease - verified", "Confirmed with property manager", "Source file is right", "Other"])
        self.assertTrue(self.app.button(key=f"{key}_go").disabled)
        self.app.button_group(key=f"{key}_reason").set_value("Special lease - verified").run()
        self.assertTrue(self.app.button(key=f"{key}_go").disabled)  # the note is still missing
        self.app.text_area(key=f"{key}_note").set_value("Lab fit-out premium in the signed lease.").run()
        self.app.button(key=f"{key}_go").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.flag()["status"], "confirmed")
        self.assertEqual(self.rows("SELECT * FROM rent_roll_units"), before)
        page = self.page()
        self.assertIn("Reviewed: confirmed by Avery Sample", page)
        self.assertIn("Special lease - verified: Lab fit-out premium in the signed lease.", page)
        self.assertIn("Every flag is resolved", page)
        self.assertEqual(self.calls, [])

    def test_fix_shows_a_before_and_after_with_recomputed_fields_then_clears_the_flag(self):
        self.use_gemini(AssertionError("a manual fix never calls the AI"))
        self.open_fallowmere()
        flag_id = self.flag()["id"]
        self.app.button(key=f"fix_btn_{flag_id}").click().run()
        key = f"fix_{flag_id}"
        self.assertEqual(self.app.text_input(key=f"{key}_monthly_rent").value, "5421.33")
        self.app.text_input(key=f"{key}_monthly_rent").set_value("2400").run()
        page = self.page()
        self.assertIn("<td>Monthly rent</td><td>5,421.33</td><td>2,400</td><td>Your change</td>", page)
        self.assertIn('<tr class="derived"><td>Annual rent</td><td>65,055.96</td><td>28,800</td><td>Recomputed: annual rent = monthly rent x 12</td>', page)
        self.assertIn("<td>Rent / SF</td><td>20.33</td><td>9</td><td>Recomputed: rent/SF = annual rent / SF</td>", page)
        self.assertTrue(self.app.button(key=f"{key}_save").disabled)  # no reason yet
        self.assertEqual(self.rows("SELECT id FROM edits"), [])  # previewing saves nothing
        self.app.text_area(key=f"{key}_reason").set_value("The lease abstract shows $2,400 a month.").run()
        self.app.button(key=f"{key}_save").click().run()
        self.assertFalse(self.app.exception)
        self.assertIn("Flag cleared: Unit 110 rent/SF is $20.33", self.app.success[0].value)
        self.assertEqual(self.flag()["status"], "corrected")
        self.assertIn("Reviewed: corrected by Avery Sample", self.page())
        self.assertEqual(len(self.rows("SELECT id FROM edits")), 3)
        self.assertEqual(self.calls, [])

    def test_the_dashboard_counts_only_open_flags(self):
        flag_id = self.flag()["id"]
        from services import corrections
        corrections.confirm_flag(flag_id, "Other", "Checked.", "Avery Sample", self.db_path)
        self.app.button(key="nav_all_deals").click().run()
        from app import queries
        self.assertEqual(queries.dashboard_stats()["anomalies"], 0)
        self.assertNotIn("1 anomaly", "\n".join(m.value for m in self.app.markdown))
        self.open_fallowmere()
        self.assertIn("Reviewed: confirmed by Avery Sample", self.page())  # still visible in the deal

    def test_timeline_and_undo(self):
        from services import corrections
        unit = self.rows("SELECT * FROM rent_roll_units WHERE unit_number = '110'")[0]
        changes, _ = corrections.plan(unit, {"monthly_rent": "2400"})
        result = corrections.apply(self.deals["fallowmere"], unit["id"], changes, "Lease abstract.", "Avery Sample", db_path=self.db_path)
        self.open_fallowmere()
        page = self.page()
        self.assertIn('<div class="event-title">Edited</div>', page)
        self.assertIn("Avery Sample · just now · Manual", page)
        self.assertIn("Unit 110 Monthly rent: 5,421.33 -&gt; 2,400", page)
        self.assertIn("Why: Lease abstract.", page)
        self.app.button(key=f"undo_{result['batch_id']}").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.rows("SELECT monthly_rent FROM rent_roll_units WHERE unit_number = '110'"), [{"monthly_rent": 5421.33}])
        self.assertIn('<div class="event-title">Undone</div>', self.page())
        self.assertIn("1 flag to resolve", self.page())

    def test_edited_cells_are_marked_with_their_original_value(self):
        from app.views import review
        from services import corrections
        unit = self.rows("SELECT * FROM rent_roll_units WHERE unit_number = '110'")[0]
        changes, _ = corrections.plan(unit, {"monthly_rent": "2400"})
        corrections.apply(self.deals["fallowmere"], unit["id"], changes, "Lease abstract.", "Avery Sample", db_path=self.db_path)
        edited = corrections.originals(self.deals["fallowmere"], self.db_path)
        units = self.rows(f"SELECT * FROM rent_roll_units WHERE deal_id = {self.deals['fallowmere']} ORDER BY id")
        table = review.units_table(units, self.rows("SELECT * FROM flags"), edited)
        self.assertEqual(table[table["Unit"] == "110"]["Edited"].iloc[0], "Monthly rent, Annual rent, Rent / SF")
        self.assertEqual(table[table["Unit"] == "110"]["Flag"].iloc[0], "Corrected")
        self.assertEqual(review._selected_cell({"selection": {"cells": [[9, "Monthly rent"]]}}), (9, "Monthly rent"))
        self.assertEqual(review._selected_cell({"selection": {"cells": [{"row": 2, "column": "SF"}]}}), (2, "SF"))
        self.assertIsNone(review._selected_cell({"selection": {"cells": []}}))

    def test_an_approved_deal_locks_the_buttons(self):
        conn = db.get_connection(self.db_path)
        with conn:
            conn.execute(f"UPDATE deals SET status = 'Approved' WHERE id = {self.deals['fallowmere']}")
        conn.close()
        self.open_fallowmere()
        flag_id = self.flag()["id"]
        self.assertTrue(self.app.button(key=f"fix_btn_{flag_id}").disabled)
        self.assertTrue(self.app.button(key=f"confirm_btn_{flag_id}").disabled)


class TestTellTheAi(NewDealAppTestCase):
    TEXT = "Unit 110's monthly rent should be $2,400. The rest was a one-off fit-out charge."

    def open_fix(self):
        self.app.button(key=f"open_deal_{self.deals['fallowmere']}").click().run()
        self.flag_id = self.rows("SELECT id FROM flags WHERE unit_number = '110'")[0]["id"]
        self.app.button(key=f"fix_btn_{self.flag_id}").click().run()

    def ask(self, text=None):
        self.app.text_area(key=f"corr_text_{self.flag_id}").set_value(text or self.TEXT).run()
        self.app.button(key=f"understand_{self.flag_id}").click().run()
        self.assertFalse(self.app.exception)

    def reply(self, changes=(), questions=()):
        self.use_gemini({"interpretation": "Unit 110's monthly rent should be 2,400.", "questions": list(questions),
                         "changes": [{"unit": u, "field": f, "new_value": v} for u, f, v in changes]})

    def page(self):
        return "\n".join(e.value for kind in ("markdown", "caption", "warning", "success")
                         for e in getattr(self.app, kind) if "<style>" not in e.value)

    def test_the_panel_has_a_text_box_the_recorder_and_calls_nothing_by_itself(self):
        self.use_gemini(AssertionError("must not be called"))
        self.open_fix()
        self.assertIn("unit 110's monthly rent should be $2,400", self.app.text_area(key=f"corr_text_{self.flag_id}").placeholder)
        self.assertIn(f"corr_{self.flag_id}_transcribe", [b.key for b in self.app.button])
        self.assertTrue(self.app.button(key=f"understand_{self.flag_id}").disabled)
        self.assertEqual(self.calls, [])

    def test_a_proposal_is_shown_and_nothing_is_saved_until_apply(self):
        self.reply([("110", "monthly_rent", "2400"), ("999", "monthly_rent", "2400")])
        self.open_fix()
        self.ask()
        self.assertEqual(len(self.calls), 1)
        page = self.page()
        self.assertIn("Here is what I understood:</b> Unit 110&#x27;s monthly rent should be 2,400.", page)
        self.assertIn("1 suggestion could not be applied: unit 999 is not in this deal.", page)
        self.assertIn("Proposed change to unit 110", page)
        self.assertIn("Recomputed: annual rent = monthly rent x 12", page)
        self.assertEqual(self.rows("SELECT id FROM edits"), [])
        self.app.button(key=f"ai_apply_{self.flag_id}_0").click().run()
        self.assertFalse(self.app.exception)
        edits = self.rows("SELECT source, reason FROM edits")
        self.assertEqual({e["source"] for e in edits}, {"AI-assisted"})
        self.assertEqual(edits[0]["reason"], self.TEXT)
        self.assertIn("Applied (AI-assisted).", self.app.success[0].value)
        self.assertIn("Flag cleared", self.app.success[0].value)
        self.assertEqual(self.rows("SELECT status FROM flags WHERE unit_number = '110'")[0]["status"], "corrected")
        self.assertEqual(len(self.calls), 1)

    def test_cancel_drops_the_proposal_and_saves_nothing(self):
        self.reply([("110", "monthly_rent", "2400")])
        self.open_fix()
        self.ask()
        self.app.button(key=f"ai_cancel_{self.flag_id}_0").click().run()
        self.assertNotIn("Proposed change to unit 110", self.page())
        self.assertEqual(self.rows("SELECT id FROM edits"), [])

    def test_edit_opens_the_form_filled_with_the_proposal(self):
        self.reply([("110", "monthly_rent", "2400")])
        self.open_fix()
        self.ask()
        self.app.button(key=f"ai_edit_{self.flag_id}_0").click().run()
        key = f"aiedit_{self.flag_id}"
        self.assertEqual(self.app.text_input(key=f"{key}_monthly_rent").value, "2400")
        self.assertEqual(self.app.text_area(key=f"{key}_reason").value, self.TEXT)
        self.app.text_input(key=f"{key}_monthly_rent").set_value("2450").run()
        self.app.button(key=f"{key}_save").click().run()
        self.assertEqual({e["source"] for e in self.rows("SELECT source FROM edits")}, {"AI-assisted"})
        self.assertEqual(self.rows("SELECT monthly_rent FROM rent_roll_units WHERE unit_number = '110'"), [{"monthly_rent": 2450.0}])

    def test_an_unsure_ai_asks_a_question_and_the_answer_is_sent_back(self):
        self.reply(questions=["Which unit's rent is wrong?"])
        self.open_fix()
        self.ask("The rent looks wrong.")
        self.assertIn("The AI needs to know: Which unit&#x27;s rent is wrong?", self.page())
        self.assertNotIn("Proposed change", self.page())
        self.reply([("110", "monthly_rent", "2400")])
        self.app.text_input(key=f"answer_{self.flag_id}_0").set_value("Unit 110, it should be 2400 a month").run()
        self.app.button(key=f"answer_go_{self.flag_id}_0").click().run()
        self.assertFalse(self.app.exception)
        self.assertIn("Proposed change to unit 110", self.page())
        self.assertIn("Answer: Unit 110, it should be 2400 a month", self.calls[-1])

    def test_quota_used_up_is_friendly_and_the_manual_form_stays(self):
        self.use_gemini(daily_quota_error())
        self.open_fix()
        self.ask()
        self.assertIn("daily quota is used up", self.page())
        self.assertIn(f"fix_{self.flag_id}_monthly_rent", [t.key for t in self.app.text_input])
        self.assertEqual(self.rows("SELECT id FROM edits"), [])


class TestApprovalPanel(NewDealAppTestCase):
    def open_fallowmere(self):
        self.app.button(key=f"open_deal_{self.deals['fallowmere']}").click().run()

    def page(self):
        return "\n".join(e.value for kind in ("markdown", "caption", "success", "warning")
                         for e in getattr(self.app, kind) if "<style>" not in e.value)

    def confirm_flag(self):
        from services import corrections
        flag_id = self.rows("SELECT id FROM flags WHERE unit_number = '110'")[0]["id"]
        corrections.confirm_flag(flag_id, "Special lease - verified", "Checked the lease.", "Avery Sample", self.db_path)

    def test_the_checklist_and_a_locked_button_while_a_flag_is_open(self):
        self.open_fallowmere()
        page = self.page()
        self.assertIn('<li class="todo">Flags resolved: 0 of 1</li>', page)
        self.assertIn('<li class="done">Edits made: 0</li>', page)
        self.assertIn('<li class="todo">Draft narrative: no draft yet</li>', page)
        self.assertTrue(self.app.button(key="approve_start").disabled)

    def test_review_approve_lock_and_reopen(self):
        self.use_gemini(AssertionError("approving never calls the AI"))
        self.confirm_flag()
        self.open_fallowmere()
        self.assertIn('<li class="done">Flags resolved: 1 of 1</li>', self.page())
        self.app.button(key="approve_start").click().run()
        page = self.page()
        self.assertIn("1 flag(s) confirmed", page)
        self.assertIn("Unit 110: rent/SF is more than 2x the average of the other units · Avery Sample · Special lease - verified: Checked the lease.", page)
        self.assertEqual(self.rows(f"SELECT status FROM deals WHERE id = {self.deals['fallowmere']}"), [{"status": "Needs Review"}])
        self.app.button(key="approve_confirm").click().run()
        self.assertFalse(self.app.exception)
        deal = self.rows(f"SELECT status, approved_by FROM deals WHERE id = {self.deals['fallowmere']}")[0]
        self.assertEqual(deal, {"status": "Approved", "approved_by": "Avery Sample"})
        page = self.page()
        self.assertIn("Approved by Avery Sample on", page)
        self.assertIn('<div class="event-title">Deal approved</div>', page)
        self.assertIn("review_download", [d.key for d in self.app.get("download_button")])
        self.assertFalse([d for d in self.app.get("download_button") if d.key == "review_download"][0].disabled)
        unit_edit_keys = [b for b in self.app.button if b.key.startswith(("fix_btn_", "confirm_btn_", "undo_"))]
        self.assertTrue(all(b.disabled for b in unit_edit_keys))
        self.app.button(key="reopen_start").click().run()
        self.assertTrue(self.app.button(key="reopen_confirm").disabled)
        self.app.text_area(key="reopen_reason").set_value("Owner sent a corrected rent roll.").run()
        self.app.button(key="reopen_confirm").click().run()
        self.assertEqual(self.rows(f"SELECT status FROM deals WHERE id = {self.deals['fallowmere']}"), [{"status": "Needs Review"}])
        self.assertIn('<div class="event-title">Reopened for changes</div>', self.page())
        self.assertIn("Why: Owner sent a corrected rent roll.", self.page())
        self.assertEqual(self.calls, [])

    def test_flag_for_producer_still_works_separately(self):
        conn = db.get_connection(self.db_path)
        with conn:
            conn.execute(f"INSERT INTO drafts (deal_id, text) VALUES ({self.deals['fallowmere']}, 'The 12 units total 154,600 SF.')")
        conn.close()
        self.open_fallowmere()
        self.app.button(key="draft_flag").click().run()
        self.assertEqual(self.rows("SELECT status FROM drafts"), [{"status": "Flagged for producer"}])
        self.assertEqual(self.rows(f"SELECT status FROM deals WHERE id = {self.deals['fallowmere']}"), [{"status": "Needs Review"}])
        self.assertIn('<li class="done">Draft narrative: Flagged for producer</li>', self.page())


class TestAppNeverChangesData(AppTestCase):
    def test_opening_the_fix_and_confirm_panels_changes_nothing(self):
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        self.sign_in()
        self.open_deal("fallowmere")
        conn = db.get_connection(self.db_path)
        flag_id = conn.execute("SELECT id FROM flags WHERE unit_number = '110'").fetchone()["id"]
        conn.close()
        self.app.button(key=f"fix_btn_{flag_id}").click().run()
        self.app.text_input(key=f"fix_{flag_id}_monthly_rent").set_value("2400").run()
        self.app.button(key=f"confirm_btn_{flag_id}").click().run()
        self.app.button(key="back_to_deals").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).hexdigest(), before)

    def test_opening_and_closing_the_new_deal_dialog_changes_nothing(self):
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        self.sign_in()
        self.app.button(key="new_deal").click().run()
        self.app.button_group(key="nd_mode").set_value("Describe it to the AI").run()
        self.app.button(key="nav_all_deals").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).hexdigest(), before)

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
