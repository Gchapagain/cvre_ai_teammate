"""Tests for the Home feed: every item type from real rows, groups and times, read / snooze / dismiss,
adding an email to a deal, meetings, and the prep brief (simulated Gemini only)."""

import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import db
import seed
from services import briefs, feed, gemini, notifications
from tests.test_extraction import daily_quota_error

CHICAGO = ZoneInfo("America/Chicago")
AT_2PM = datetime(2026, 10, 28, 14, 0, tzinfo=CHICAGO)
LOCAL_2PM = AT_2PM.replace(tzinfo=None)


class FeedTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / "feed.db"
        self.deals = seed.seed(self.db_path)
        patcher = mock.patch.object(db, "DB_PATH", self.db_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def items(self, now=AT_2PM):
        from app import queries
        return feed.build(queries.feed_rows(), now)

    def item(self, key, now=AT_2PM):
        return next((i for i in self.items(now) if i.key == key), None)

    def sql(self, statement, params=()):
        conn = db.get_connection(self.db_path)
        try:
            with conn:
                return [dict(row) for row in conn.execute(statement, params)]
        finally:
            conn.close()


class TestItemsFromRealData(FeedTestCase):
    def test_every_kind_appears_from_the_sample_data(self):
        kinds = {i.kind for i in self.items()}
        self.assertEqual(kinds, {feed.FLAG, feed.WAITING_KIND, feed.MEETING, feed.EMAIL})

    def test_an_open_flag_is_red_priority_with_its_own_numbers(self):
        flag_id = self.sql("SELECT id FROM flags WHERE status = 'open'")[0]["id"]
        item = self.item(f"flag:{flag_id}")
        self.assertEqual(item.group, feed.NOW_GROUP)
        self.assertEqual(item.message, "Unit 110 rent/SF is 2.37x the average - Fallowmere Industrial Park")
        self.assertEqual(item.actions, (("Review flag", "review_flag"),))
        self.assertFalse(item.can_hide)

    def test_a_resolved_flag_leaves_the_feed_but_stays_on_the_deal(self):
        flag_id = self.sql("SELECT id FROM flags WHERE status = 'open'")[0]["id"]
        self.sql("UPDATE flags SET status = 'confirmed' WHERE id = ?", (flag_id,))
        self.assertIsNone(self.item(f"flag:{flag_id}"))
        self.assertEqual(len(self.sql("SELECT id FROM flags WHERE id = ?", (flag_id,))), 1)

    def test_waiting_items_come_from_each_waiting_thing(self):
        fallowmere, quillhaven = self.deals["fallowmere"], self.deals["quillhaven"]
        self.assertEqual(self.item(f"review:{fallowmere}").message, "Fallowmere Industrial Park is waiting for your review")
        doc_id = self.sql("SELECT id FROM documents WHERE deal_id = ? AND status = 'Received'", (quillhaven,))[0]["id"]
        self.assertIn("has arrived and has not been read yet", self.item(f"doc:{doc_id}:Received").message)
        self.sql("UPDATE documents SET status = 'Needs password' WHERE id = ?", (doc_id,))
        self.assertIn("needs a password", self.item(f"doc:{doc_id}:Needs password").message)

    def test_an_ai_draft_waiting_for_approval_is_an_ai_item(self):
        conn = db.get_connection(self.db_path)
        with conn:
            draft_id = conn.execute("INSERT INTO drafts (deal_id, text) VALUES (?, 'A draft.')", (self.deals["fallowmere"],)).lastrowid
        conn.close()
        item = self.item(f"draft:{draft_id}")
        self.assertTrue(item.ai)
        self.assertEqual(item.group, feed.WAITING)
        self.assertIn("AI-drafted narrative", item.message)

    def test_new_real_research_waits_but_simulated_research_never_does(self):
        fallowmere = self.deals["fallowmere"]
        conn = db.get_connection(self.db_path)
        with conn:
            conn.execute("INSERT INTO research_findings (deal_id, topic, summary) VALUES (?, 'Vacancy', 'Real.')", (fallowmere,))
            newest = conn.execute("INSERT INTO research_findings (deal_id, topic, summary) VALUES (?, 'Supply', 'Real.')",
                                  (fallowmere,)).lastrowid
            conn.execute("INSERT INTO research_findings (deal_id, topic, summary, simulated) VALUES (?, 'X', 'Fake.', 1)",
                         (fallowmere,))
        conn.close()
        item = self.item(f"research:{fallowmere}:{newest}")
        self.assertIn("2 research findings", item.message)

    def test_meeting_message_has_the_time_title_deal_and_countdown(self):
        item = self.item("meeting:1")
        self.assertEqual(item.message, "Today 3:00 PM - Client call - Fallowmere Industrial Park - in 1 hour")
        self.assertEqual(item.group, feed.NOW_GROUP)
        self.assertTrue(item.sample)
        self.assertEqual([a for _, a in item.actions], ["open_deal", "prep_brief"])

    def test_email_message_names_the_sender_deal_and_attachments(self):
        item = self.item("email:1")
        self.assertEqual(item.message, "New email from Dana Reyes about Fallowmere Industrial Park - "
                                       "1 attachment (fallowmere_rent_roll_v2.xlsx)")
        self.assertEqual([a for _, a in item.actions], ["add_email", "dismiss_email"])
        self.assertTrue(item.sample)

    def test_every_sample_item_is_marked_sample_and_nothing_else_is(self):
        for item in self.items():
            with self.subTest(item.key):
                self.assertEqual(item.sample, item.kind in (feed.MEETING, feed.EMAIL))


class TestGroupsAndTimes(FeedTestCase):
    def groups(self, hour):
        return {i.key: i.group for i in self.items(datetime(2026, 10, 28, hour, 0, tzinfo=CHICAGO))}

    def test_meetings_move_between_groups_through_the_day(self):
        self.assertEqual(self.groups(7)["meeting:1"], feed.NOW_GROUP)    # client call at 3 PM, in 8 hours
        self.assertEqual(self.groups(7)["meeting:3"], feed.COMING_UP)    # tomorrow 10 AM, 27 hours away
        self.assertEqual(self.groups(14)["meeting:3"], feed.NOW_GROUP)   # now within 24 hours
        self.assertEqual(self.groups(21)["meeting:1"], feed.EARLIER)     # ended
        self.assertEqual(self.groups(14)["meeting:5"], feed.EARLIER)     # yesterday's check-in

    def test_needs_you_counts_open_flags_and_meetings_in_the_next_24_hours(self):
        self.assertEqual(feed.needs_you(self.items()), 3)

    def test_sample_times_follow_today(self):
        anchor = date.fromisoformat(db.SAMPLE_ANCHOR_DAY)
        moved = feed.local(f"{anchor} 15:00:00", "Sample", date(2026, 10, 28))
        self.assertEqual(moved, datetime(2026, 10, 28, 15, 0))
        self.assertEqual(feed.local("2026-11-02 09:00:00", "Manual", date(2026, 10, 28)), datetime(2026, 11, 2, 9, 0))

    def test_utc_times_are_shown_in_the_persons_timezone(self):
        self.assertEqual(feed.from_utc("2026-10-28 19:00:00", AT_2PM), datetime(2026, 10, 28, 14, 0))

    def test_countdown_and_ago_wording(self):
        now = LOCAL_2PM
        self.assertEqual(feed.countdown(now + timedelta(minutes=25), None, now), "in 25 min")
        self.assertEqual(feed.countdown(now + timedelta(hours=2), None, now), "in 2 hours")
        self.assertEqual(feed.countdown(now - timedelta(minutes=10), now + timedelta(minutes=20), now), "happening now")
        self.assertEqual(feed.countdown(now - timedelta(hours=2), now - timedelta(hours=1), now), "ended")
        self.assertEqual(feed.ago(now - timedelta(minutes=5), now), "5 min ago")
        self.assertEqual(feed.ago(now - timedelta(hours=3), now), "3 hours ago")
        self.assertEqual(feed.ago(now - timedelta(days=1, hours=2), now), "Yesterday")

    def test_order_is_group_then_soonest_meeting(self):
        items = self.items()
        self.assertEqual([i.group for i in items], sorted((i.group for i in items), key=feed.GROUPS.index))
        now_group = [i.key for i in items if i.group == feed.NOW_GROUP]
        self.assertEqual(now_group[:2], ["meeting:1", "meeting:3"])

    def test_filters_and_counts(self):
        items = self.items()
        counts = feed.counts(items)
        self.assertEqual(counts["All"], len(items))
        self.assertEqual(counts["Flags"], 1)
        self.assertEqual(sum(len(g) for _, g in feed.grouped(items, feed.FLAG)), 1)

    def test_no_items_means_no_groups(self):
        empty = {"flags": [], "review_deals": [], "documents": [], "drafts": [], "research": [], "meetings": [],
                 "emails": [], "state": {}}
        items = feed.build(empty, AT_2PM)
        self.assertEqual((items, feed.grouped(items), feed.needs_you(items), feed.unread(items)), ([], [], 0, 0))


class TestItemState(FeedTestCase):
    def test_mark_read(self):
        self.assertFalse(self.item("email:1").read)
        notifications.mark_read(["email:1"], LOCAL_2PM, self.db_path)
        self.assertTrue(self.item("email:1").read)

    def test_mark_all_read_empties_the_unread_count(self):
        notifications.mark_read([i.key for i in self.items()], LOCAL_2PM, self.db_path)
        self.assertEqual(feed.unread(self.items()), 0)

    def test_snooze_hides_for_a_day_then_it_comes_back(self):
        notifications.snooze("email:1", LOCAL_2PM, self.db_path)
        self.assertIsNone(self.item("email:1"))
        self.assertIsNotNone(self.item("email:1", AT_2PM + timedelta(days=1, minutes=1)))

    def test_dismiss_hides_it(self):
        notifications.dismiss("meeting:3", LOCAL_2PM, self.db_path)
        self.assertIsNone(self.item("meeting:3"))

    def test_flags_cannot_be_snoozed_or_dismissed(self):
        key = next(i.key for i in self.items() if i.kind == feed.FLAG)
        for action in (notifications.snooze, notifications.dismiss):
            with self.subTest(action.__name__):
                with self.assertRaises(ValueError):
                    action(key, LOCAL_2PM, self.db_path)
        # Even if a dismissed state were stored for a flag, the flag still shows.
        self.sql("INSERT INTO notification_state (item_key, dismissed_at) VALUES (?, '2026-10-28 13:00:00')", (key,))
        self.assertIsNotNone(self.item(key))


class TestEmails(FeedTestCase):
    def test_add_to_deal_creates_received_documents_from_email(self):
        quillhaven = self.deals["quillhaven"]
        before = len(self.sql("SELECT id FROM documents WHERE deal_id = ?", (quillhaven,)))
        ids = notifications.add_email_to_deal(3, quillhaven, self.db_path)
        docs = self.sql(f"SELECT filename, source, status, file_path FROM documents WHERE id IN ({','.join('?' * len(ids))})", ids)
        self.assertEqual(docs, [
            {"filename": "quillhaven_t12.xlsx", "source": "Email", "status": "Received", "file_path": None},
            {"filename": "quillhaven_lease_abstract.pdf", "source": "Email", "status": "Received", "file_path": None}])
        self.assertEqual(len(self.sql("SELECT id FROM documents WHERE deal_id = ?", (quillhaven,))), before + 2)
        self.assertEqual(self.sql("SELECT status FROM emails WHERE id = 3")[0]["status"], "added")
        self.assertIsNone(self.item("email:3"))
        # The new documents now wait in the feed.
        self.assertIsNotNone(self.item(f"doc:{ids[0]}:Received"))

    def test_an_email_without_a_deal_goes_to_the_deal_the_person_picks(self):
        notifications.add_email_to_deal(2, self.deals["fallowmere"], self.db_path)
        self.assertEqual(self.sql("SELECT deal_id, status FROM emails WHERE id = 2")[0],
                         {"deal_id": self.deals["fallowmere"], "status": "added"})

    def test_an_email_cannot_be_added_twice_or_to_no_deal(self):
        notifications.add_email_to_deal(1, self.deals["fallowmere"], self.db_path)
        with self.assertRaises(ValueError):
            notifications.add_email_to_deal(1, self.deals["fallowmere"], self.db_path)
        with self.assertRaises(ValueError):
            notifications.add_email_to_deal(2, 9999, self.db_path)

    def test_dismissing_an_email_adds_nothing(self):
        before = len(self.sql("SELECT id FROM documents"))
        notifications.dismiss_email(1, self.db_path)
        self.assertEqual(self.sql("SELECT status FROM emails WHERE id = 1")[0]["status"], "dismissed")
        self.assertEqual(len(self.sql("SELECT id FROM documents")), before)
        self.assertIsNone(self.item("email:1"))


class TestMeetings(FeedTestCase):
    def test_a_typed_meeting_appears_in_the_feed(self):
        meeting_id = notifications.add_meeting("Lender call", LOCAL_2PM + timedelta(hours=2), LOCAL_2PM + timedelta(hours=3),
                                               self.deals["quillhaven"], "Sam Ito", db_path=self.db_path)
        item = self.item(f"meeting:{meeting_id}")
        self.assertEqual(item.message, "Today 4:00 PM - Lender call - Quillhaven Flex Center - in 2 hours")
        self.assertFalse(item.sample)

    def test_a_meeting_needs_a_title_and_must_end_after_it_starts(self):
        with self.assertRaises(ValueError):
            notifications.add_meeting(" ", LOCAL_2PM, db_path=self.db_path)
        with self.assertRaises(ValueError):
            notifications.add_meeting("Call", LOCAL_2PM, LOCAL_2PM - timedelta(minutes=5), db_path=self.db_path)

    def test_a_meeting_with_no_deal_has_no_prep_brief(self):
        self.assertEqual(self.item("meeting:2", datetime(2026, 10, 28, 7, 0, tzinfo=CHICAGO)).actions, ())


def brief_client(calls, reply):
    def generate_content(**kwargs):
        calls.append(kwargs["contents"])
        if isinstance(reply, Exception):
            raise reply
        return type("Reply", (), {"text": json.dumps({"brief": reply})})()
    return type("Client", (), {"models": type("Models", (), {"generate_content": staticmethod(generate_content)})()})()


class TestPrepBrief(FeedTestCase):
    def setUp(self):
        super().setUp()
        self.calls = []
        no_wait = mock.patch.object(gemini, "RETRY_WAIT_SECONDS", 0)
        no_wait.start()
        self.addCleanup(no_wait.stop)

    def saved(self, meeting_id=1):
        row = self.sql("SELECT brief, brief_at FROM meetings WHERE id = ?", (meeting_id,))[0]
        return json.loads(row["brief"]) if row["brief"] else None

    def test_one_request_from_the_deals_data_only_and_saved_on_the_meeting(self):
        text = "- 12 units, 154,600 SF.\n- Unit 110 is flagged: confirm it before pricing."
        brief = briefs.generate_brief(1, client=brief_client(self.calls, text), db_path=self.db_path, now=LOCAL_2PM)
        self.assertEqual(len(self.calls), 1)
        self.assertIn("MEETING PREP BRIEF", self.calls[0])
        self.assertIn("Fallowmere Industrial Park", self.calls[0])
        self.assertNotIn("Quillhaven", self.calls[0])  # only this meeting's deal
        self.assertEqual(brief, {"text": text, "unverified": []})
        self.assertEqual(self.saved(), brief)

    def test_a_number_not_in_the_deal_is_listed_as_not_verified(self):
        brief = briefs.generate_brief(1, client=brief_client(self.calls, "- Expect a 6.5% cap rate."), db_path=self.db_path)
        self.assertEqual(brief["unverified"], [6.5])

    def test_a_meeting_without_a_deal_is_refused_without_calling_gemini(self):
        with self.assertRaises(ValueError):
            briefs.generate_brief(2, client=brief_client(self.calls, AssertionError("must not be called")), db_path=self.db_path)
        self.assertEqual(self.calls, [])

    def test_quota_used_up_saves_nothing(self):
        with self.assertRaises(gemini.GeminiQuotaError):
            briefs.generate_brief(1, client=brief_client(self.calls, daily_quota_error()), db_path=self.db_path)
        self.assertIsNone(self.saved())

    def test_an_unreadable_reply_saves_nothing(self):
        bad = type("Client", (), {"models": type("Models", (), {"generate_content": staticmethod(
            lambda **kwargs: type("Reply", (), {"text": "not json"})())})()})()
        with self.assertRaises(gemini.GeminiError):
            briefs.generate_brief(1, client=bad, db_path=self.db_path)
        self.assertIsNone(self.saved())


class TestSchema(FeedTestCase):
    def test_feed_tables_exist_and_sample_rows_are_labelled(self):
        conn = sqlite3.connect(self.db_path)
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            sources = {r[0] for r in conn.execute("SELECT source FROM meetings UNION SELECT source FROM emails")}
        finally:
            conn.close()
        self.assertLessEqual({"meetings", "emails", "notification_state"}, tables)
        self.assertEqual(sources, {"Sample"})


if __name__ == "__main__":
    unittest.main()


class TestRail(FeedTestCase):
    def test_todays_agenda_is_every_meeting_today_in_time_order(self):
        from app import queries
        agenda = feed.todays_meetings(queries.feed_rows(), AT_2PM)
        self.assertEqual([(m["title"], feed.clock(m["start"]), m["status"]) for m in agenda],
                         [("Coffee with a prospective client", "8:30 AM", "ended"), ("Client call", "3:00 PM", "in 1 hour")])
        self.assertTrue(all(m["sample"] for m in agenda))

    def test_a_dismissed_meeting_card_stays_on_the_agenda(self):
        from app import queries
        notifications.dismiss("meeting:1", LOCAL_2PM, self.db_path)
        self.assertIsNone(self.item("meeting:1"))
        self.assertIn("Client call", [m["title"] for m in feed.todays_meetings(queries.feed_rows(), AT_2PM)])

    def test_waiting_summary_counts_each_kind_and_skips_empty_ones(self):
        summary = feed.waiting_summary(self.items())
        self.assertEqual(summary, [("Open flags", 1, "Flags"), ("Deals to review", 1, "Waiting"),
                                   ("Documents not read yet", 1, "Waiting"), ("New emails", 3, "Email")])
