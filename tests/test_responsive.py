"""Responsive layout: breakpoints set once, phone navigation, and the CSS rules phones and tablets rely on.

The real look at 390, 820 and 1440 px is checked in the browser by tools/screenshots.py (mobile, tablet, chrome).
"""

import re
import unittest
from pathlib import Path

from app import style
from tests.test_app import AppTestCase

ROOT = Path(__file__).resolve().parent.parent


class TestBreakpoints(unittest.TestCase):
    def test_breakpoints_are_set_once(self):
        self.assertEqual((style.PHONE_MAX, style.TABLET_MAX), (640, 1024))
        queries = re.findall(r"@media \(max-width: (\d+)px\)", style.CSS)
        self.assertEqual(set(queries), {"640", "1024"})
        self.assertNotIn("__PHONE__", style.CSS)
        for path in (ROOT / "app").rglob("*.py"):
            text = path.read_text()
            with self.subTest(path.name):
                self.assertNotIn("760px", text)  # the old single breakpoint is gone everywhere

    def test_phone_rules_cover_taps_text_dialogs_and_tables(self):
        phone = style.CSS.split("@media (max-width: 640px)")[1]
        for rule in ("--control-h: 44px", "min-height: 44px", "font-size: 1rem", 'section[role="dialog"]',
                     "inset: 0 !important", "env(safe-area-inset-bottom)", "overflow-x: auto", ".st-key-bottom_nav",
                     "bottom: calc(var(--bottomnav-h) + 16px"):
            self.assertIn(rule, phone)

    def test_hover_only_extras_are_hidden_on_touch_screens(self):
        tablet = style.CSS.split("@media (max-width: 1024px)")[1].split("@media")[0]
        self.assertIn('[data-testid="stHeaderActionElements"]', tablet)
        self.assertIn(".st-key-fab::before { display: none; }", tablet)

    def test_menu_and_bottom_bar_are_hidden_on_desktop(self):
        desktop = style.CSS.split("@media (max-width: 1024px)")[0]
        self.assertIn(".st-key-nav_menu, .st-key-bottom_nav { display: none !important; }", desktop)


class TestPhoneNavigation(AppTestCase):
    def setUp(self):
        super().setUp()
        self.sign_in()

    def test_bottom_bar_has_the_add_button_in_the_centre_and_marks_the_page(self):
        labels = {b.key: b.label for b in self.app.button if b.key and b.key.startswith("bnav_")}
        self.assertEqual(list(labels.values()), ["Home", "Deals", "New", "Connections", "Settings"])  # "+" in the centre
        self.assertEqual(self.app.button(key="bnav_home").proto.type, "primary")
        self.app.button(key="bnav_deals").click().run()
        self.assertEqual(self.app.session_state["page"], "dashboard")
        self.assertEqual(self.app.button(key="bnav_deals").proto.type, "primary")
        self.assertEqual(self.app.button(key="bnav_home").proto.type, "tertiary")

    def test_the_menu_has_settings_and_sign_out(self):
        self.app.button(key="menu_settings").click().run()
        self.assertEqual(self.app.session_state["page"], "settings")
        self.app.button(key="menu_sign_out").click().run()
        self.assertNotIn("user", self.app.session_state)
