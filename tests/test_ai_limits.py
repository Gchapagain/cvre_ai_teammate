"""Tests for the app's AI rate limits. No Gemini calls."""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import db
from services import ai_limits, gemini

START = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
SETTINGS = {"AI_DAILY_LIMIT": "3", "AI_SESSION_HOURLY_LIMIT": "2"}


class LimitsTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / "app.db"
        env = mock.patch.dict("os.environ", SETTINGS)
        env.start()
        self.addCleanup(env.stop)

    def acquire(self, session, minutes=0, seconds=0):
        ai_limits.acquire(session, self.db_path, START + timedelta(minutes=minutes, seconds=seconds))

    def count(self):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute("SELECT COUNT(*) FROM ai_usage").fetchone()[0]
        finally:
            conn.close()


class TestAcquire(LimitsTestCase):
    def test_requests_under_every_limit_are_recorded(self):
        self.acquire("a")
        self.acquire("a", minutes=1)
        self.assertEqual(self.count(), 2)

    def test_hourly_limit_is_per_session(self):
        self.acquire("a")
        self.acquire("a", minutes=1)
        with self.assertRaises(gemini.RateLimited) as raised:
            self.acquire("a", minutes=2)
        self.assertIn("You have used your 2 AI requests for this hour.", str(raised.exception))
        self.assertIn("about 58 minutes", str(raised.exception))
        self.acquire("b", minutes=2)  # another session is not affected by a's hour

    def test_hourly_limit_frees_up_after_an_hour(self):
        self.acquire("a")
        self.acquire("a", minutes=1)
        self.acquire("a", minutes=61)
        self.assertEqual(self.count(), 3)

    def test_daily_limit_covers_everyone_together(self):
        self.acquire("a")
        self.acquire("b", minutes=1)
        self.acquire("c", minutes=2)
        with self.assertRaises(gemini.RateLimited) as raised:
            self.acquire("d", minutes=3)
        self.assertIn("The app's AI limit of 3 requests a day has been reached.", str(raised.exception))
        self.assertIn("Try again in about 24 hours.", str(raised.exception))
        self.acquire("d", minutes=24 * 60 + 1)  # the first request has dropped out of the last 24 hours

    def test_two_requests_in_a_row_are_allowed(self):
        # One click can need two requests (Run research), so there is no wait between them.
        self.acquire("a")
        self.acquire("a", seconds=1)
        self.assertEqual(self.count(), 2)

    def test_a_refused_request_is_not_counted(self):
        self.acquire("a")
        self.acquire("a", seconds=1)
        for _ in range(3):
            with self.assertRaises(gemini.RateLimited):
                self.acquire("a", seconds=2)
        self.assertEqual(self.count(), 2)

    def test_rate_limited_is_a_gemini_error_but_not_busy_or_quota(self):
        self.assertTrue(issubclass(gemini.RateLimited, gemini.GeminiError))
        self.assertFalse(issubclass(gemini.RateLimited, (gemini.GeminiBusyError, gemini.GeminiQuotaError)))

    def test_no_limit_or_record_outside_the_app(self):
        # Scripts and tests have no browser session.
        with mock.patch.dict("os.environ", {"AI_DAILY_LIMIT": "0"}):
            for _ in range(5):
                ai_limits.acquire(None, self.db_path, START)
        self.assertFalse(self.db_path.exists())

    def test_bad_settings_fall_back_to_the_defaults(self):
        with mock.patch.dict("os.environ", {"AI_DAILY_LIMIT": "lots", "AI_SESSION_HOURLY_LIMIT": "-4"}):
            current = ai_limits.limits()
        self.assertEqual(current.daily, ai_limits.DEFAULTS["AI_DAILY_LIMIT"])
        self.assertEqual(current.hourly, 0)

    def test_generate_response_checks_the_limit_before_contacting_gemini(self):
        class NoClient:
            def __getattr__(self, name):
                raise AssertionError("Gemini must not be contacted when a limit is reached")

        with mock.patch.object(db, "DB_PATH", self.db_path), \
                mock.patch.object(ai_limits, "current_session", lambda: "a"), \
                mock.patch.dict("os.environ", {"AI_DAILY_LIMIT": "0"}):
            with self.assertRaises(gemini.RateLimited):
                gemini.generate_response(NoClient(), "Hello", None)


class TestUsage(LimitsTestCase):
    def test_counts_and_what_is_left(self):
        self.acquire("a")
        self.acquire("b", minutes=1)
        used = ai_limits.usage("a", self.db_path, START + timedelta(minutes=2))
        self.assertEqual((used.used_today, used.used_this_hour), (2, 1))
        self.assertEqual((used.left_today, used.left_this_hour), (1, 1))

    def test_works_with_no_database_or_an_old_one(self):
        self.assertEqual(ai_limits.usage("a", self.db_path).used_today, 0)
        self.assertFalse(self.db_path.exists())  # reading never creates the file
        sqlite3.connect(self.db_path).close()  # a database from before the ai_usage table
        self.assertEqual(ai_limits.usage("a", self.db_path).left_today, 3)

    def test_summary_line(self):
        ai_limits.acquire("a", self.db_path)  # now, because the summary counts back from now
        self.assertEqual(ai_limits.summary("a", self.db_path),
                         "AI requests left: 1 this hour (you), 2 today (whole app).")

    def test_table_is_part_of_the_schema(self):
        db.init_db(self.db_path)
        conn = sqlite3.connect(self.db_path)
        try:
            self.assertIn("ai_usage", {r[0] for r in conn.execute("SELECT name FROM sqlite_master")})
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
