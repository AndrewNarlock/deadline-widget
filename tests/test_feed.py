"""Tests for feed parsing, time zones and the Item helpers."""

import unittest
from datetime import date, datetime, timedelta, timezone

from deadline_widget.models import AI, CALENDAR, Item, upcoming
from deadline_widget.sources.feed import parse_events

ICS = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:before-dst-ends
DTSTART:20261024T065900Z
SUMMARY:Reflection 4
DESCRIPTION:Read Chapter 3 first.
URL:https://canvas.example.edu/assignments/4
END:VEVENT
BEGIN:VEVENT
UID:after-dst-ends
DTSTART:20261109T075900Z
SUMMARY:Reflection 5
END:VEVENT
BEGIN:VEVENT
UID:all-day
DTSTART;VALUE=DATE:20261111
SUMMARY:No class
END:VEVENT
BEGIN:VEVENT
UID:no-start
SUMMARY:Broken event
END:VEVENT
END:VCALENDAR
"""


def local_offset(year: int, month: int, day: int) -> timedelta:
    """This machine's UTC offset on a given date (differs across a DST change)."""
    return datetime(year, month, day, 12).astimezone().utcoffset()


class ParseEventsTest(unittest.TestCase):
    def setUp(self):
        self.events = {event.uid: event for event in parse_events(ICS)}

    def test_skips_events_without_a_start(self):
        self.assertEqual(set(self.events), {"before-dst-ends", "after-dst-ends", "all-day"})

    def test_reads_fields(self):
        event = self.events["before-dst-ends"]
        self.assertEqual((event.title, event.description), ("Reflection 4", "Read Chapter 3 first."))
        self.assertEqual(event.url, "https://canvas.example.edu/assignments/4")

    def test_each_date_gets_its_own_utc_offset(self):
        # The old code used today's offset for every date, so on Pacific time anything after
        # Nov 1 showed an hour late (11:59 PM became 12:59 AM the next day).
        for uid, utc, day in [
            ("before-dst-ends", datetime(2026, 10, 24, 6, 59, tzinfo=timezone.utc), (2026, 10, 24)),
            ("after-dst-ends", datetime(2026, 11, 9, 7, 59, tzinfo=timezone.utc), (2026, 11, 9)),
        ]:
            with self.subTest(uid):
                due = self.events[uid].due
                self.assertEqual(due, utc)  # same instant
                self.assertEqual(due.utcoffset(), local_offset(*day))

    def test_all_day_events_stay_dates(self):
        self.assertIs(type(self.events["all-day"].due), date)


class ItemTest(unittest.TestCase):
    def test_round_trips_through_json_shape(self):
        timed = Item("Quiz", datetime(2026, 10, 23, 23, 59).astimezone(), CALENDAR, "Canvas", "https://x")
        all_day = Item("Read Chapter 3", date(2026, 10, 23), AI, "Week 4", est_minutes=45)
        for item in (timed, all_day):
            self.assertEqual(Item.from_dict(item.to_dict()), item)

    def test_labels(self):
        item = Item("Quiz", datetime(2026, 10, 23, 9, 5).astimezone(), CALENDAR, "Canvas")
        self.assertEqual((item.day_label, item.time_label), ("Fri Oct 23", "9:05 AM"))
        self.assertEqual(Item("Read", date(2026, 11, 2), AI, "x").time_label, "")

    def test_upcoming_keeps_today_through_the_window_soonest_first(self):
        today = date.today()
        items = [
            Item("later today", datetime.combine(today, datetime.max.time()).astimezone(), CALENDAR, "Canvas"),
            Item("today, all day", today, AI, "x"),
            Item("yesterday", today - timedelta(days=1), AI, "x"),
            Item("too far", today + timedelta(days=30), AI, "x"),
        ]
        self.assertEqual([i.title for i in upcoming(items, days=30)], ["today, all day", "later today"])


if __name__ == "__main__":
    unittest.main()
