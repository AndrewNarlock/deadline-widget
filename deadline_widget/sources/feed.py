"""feed.py - plain code (no model). Download the Canvas calendar feed and parse its events."""

from dataclasses import dataclass
from datetime import date, datetime

import requests
from icalendar import Calendar

from .. import config
from ..models import CALENDAR, Item


class FeedError(RuntimeError):
    """The feed could not be loaded. Messages never include the feed URL, which is a secret."""


@dataclass(frozen=True)
class Event:
    uid: str
    title: str
    due: date | datetime
    description: str  # untrusted text; pipeline.py may hand it to Claude
    url: str

    def to_item(self) -> Item:
        return Item(title=self.title, due=self.due, kind=CALENDAR, source="Canvas", url=self.url)


def load_events(ics_file: str | None = None) -> list[Event]:
    """Events from a local .ics file if given, otherwise from CANVAS_FEED_URL in .env."""
    if ics_file:
        with open(ics_file, encoding="utf-8") as f:
            ics_text = f.read()
    elif config.FEED_URL:
        ics_text = fetch_ics(config.FEED_URL)
    else:
        raise FeedError("CANVAS_FEED_URL is not set. Copy .env.example to .env and paste your feed URL.")
    try:
        return parse_events(ics_text)
    except ValueError:
        raise FeedError("The calendar feed is not valid iCal data. Check the URL in .env.") from None


def fetch_ics(url: str) -> str:
    # `from None` drops the original exception, whose message would contain the secret URL.
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except requests.HTTPError as error:
        raise FeedError(f"The calendar feed returned HTTP {error.response.status_code}.") from None
    except requests.RequestException as error:
        raise FeedError(f"Could not reach the calendar feed ({type(error).__name__}).") from None
    return response.text


def parse_events(ics_text: str) -> list[Event]:
    """Turn raw .ics text into events. Recurring events (RRULE) are not expanded; Canvas doesn't use them."""
    events = []
    for component in Calendar.from_ical(ics_text).walk("VEVENT"):
        start = component.get("DTSTART")
        if start is None or not isinstance(start.dt, date):
            continue
        events.append(
            Event(
                uid=str(component.get("UID", "")),
                title=str(component.get("SUMMARY", "(untitled)")),
                due=_local(start.dt),
                description=str(component.get("DESCRIPTION", "")).strip(),
                url=str(component.get("URL", "")),
            )
        )
    return events


def _local(value: date | datetime) -> date | datetime:
    """Datetimes become local time with the UTC offset in effect on *that* date, so deadlines after
    a daylight saving change keep the right hour. Naive (floating) times count as local already.
    All-day dates stay dates."""
    return value.astimezone() if isinstance(value, datetime) else value
