"""The AI Teammate chat card: the Ask AI tab and the floating dialog use the same component and draw the same
bubbles (broker on the right, AI on the left, limits and errors as a soft amber notice). Gemini is simulated.
"""

from unittest import mock

from app.views import ask_ai
from services import gemini, qa
from tests.test_app import AppTestCase, all_deals_client, daily_quota_error, reply_client


class ChatCase(AppTestCase):
    def setUp(self):
        super().setUp()
        self.calls, self.shown, self.cards = [], [], []
        for patcher in (mock.patch.object(gemini, "RETRY_WAIT_SECONDS", 0),
                        mock.patch.object(ask_ai, "render_chat", side_effect=self.spy_card(ask_ai.render_chat)),
                        mock.patch.object(ask_ai, "_show", side_effect=self.spy_show(ask_ai._show))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sign_in()

    def spy_card(self, real):
        def card(deal_id, prefix="", header=True):
            self.cards.append((prefix, header))
            return real(deal_id, prefix=prefix, header=header)
        return card

    def spy_show(self, real):
        def show(message, key):
            self.shown.append((key, ask_ai.bubble_kind(message)))
            return real(message, key)
        return show

    def kinds(self, prefix):
        return {kind for key, kind in self.shown if key.startswith(f"{prefix}chatmsg_")}


class TestOneComponent(ChatCase):
    def test_the_tab_and_the_dialog_draw_the_same_chat_card(self):
        self.open_deal("fallowmere")
        self.app.button(key="open_assistant").click().run()
        self.assertFalse(self.app.exception)
        self.assertIn(("", True), self.cards)                     # the Ask AI tab, with its own forest header
        self.assertIn(("assistant_", False), self.cards)          # the dialog, whose title bar is the header
        self.assertEqual(len({c for c in self.cards}), 2)

    def test_both_bubble_types_in_the_tab(self):
        with mock.patch.object(gemini, "get_client", lambda: reply_client(self.calls, "Unit 110 pays 20.33 per SF.")):
            self.open_deal("fallowmere")
            self.app.chat_input(key=f"chat_input_{self.deals['fallowmere']}").set_value("What does unit 110 pay per SF?").run()
        self.assertEqual(len(self.calls), 1)
        self.assertLessEqual({"user", "ai"}, self.kinds(""))
        self.assertIn(">From this deal</span>", "\n".join(m.value for m in self.app.markdown))  # still labelled

    def test_both_bubble_types_and_the_notice_in_the_dialog(self):
        client = all_deals_client(self.calls, daily_quota_error())
        with mock.patch.object(gemini, "get_client", lambda: client):
            self.app.button(key="open_assistant").click().run()
            self.app.chat_input(key="assistant_chat_input_all").set_value("Which deals have anomalies?").run()
        self.assertLessEqual({"user", "notice"}, self.kinds("assistant_"))
        self.assertIn("ai", self.kinds("assistant_"))  # the greeting before the first question

    def test_a_suggestion_chip_sends_its_question_with_one_request(self):
        with mock.patch.object(gemini, "get_client", lambda: reply_client(self.calls, "Unit 110 is the flagged unit.")):
            self.open_deal("fallowmere")
            self.assertEqual(self.calls, [])  # nothing is sent just by looking
            self.app.button(key=f"chatchip_{self.deals['fallowmere']}_1").click().run()
        self.assertEqual(len(self.calls), 1)
        messages = self.app.session_state[f"chat_{self.deals['fallowmere']}"]
        self.assertEqual(messages[0], {"role": "user", "text": ask_ai.SUGGESTIONS["deal"][1]})
        self.assertEqual(messages[1]["label"], qa.LABEL_FROM_DEAL)


class TestBubbleKinds(ChatCase):
    def test_kinds(self):
        self.assertEqual(ask_ai.bubble_kind({"role": "user", "text": "q"}), "user")
        self.assertEqual(ask_ai.bubble_kind({"role": "assistant", "label": qa.LABEL_FROM_DEAL}), "ai")
        self.assertEqual(ask_ai.bubble_kind({"role": "assistant", "label": ask_ai.LABEL_NO_ANSWER}), "notice")
