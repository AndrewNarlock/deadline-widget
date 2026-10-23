"""models.py - the records every step passes along (Item for deadlines, Email for the inbox),
plus small date helpers.

A `due` value is a datetime when it has a time of day (most Canvas deadlines) and a plain
date when it doesn't (all-day events, and dates Claude reads from text).
"""

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta

CALENDAR = "calendar"  # straight from the Canvas feed
AI = "ai"  # extracted by Claude, and passed the validator in extract.py

# The Calendar page's sections. ai/plan.py asks Claude to sort every item into one of these.
ASSIGNMENT, READING, EXAM = "assignment", "reading", "exam"
CATEGORIES = (ASSIGNMENT, READING, EXAM)

COURSE_TAG = re.compile(r"\s*\[([A-Z]+ ?\d+)[^\]]*\]\s*$")  # Canvas titles end like "[TCSS 490 A]"


@dataclass(frozen=True)
class Item:
    title: str
    due: date | datetime
    kind: str  # CALENDAR or AI
    source: str  # "Canvas", or the event/page title Claude read it from
    url: str = ""
    est_minutes: int | None = None  # Claude's estimate; AI items only
    category: str = ""  # one of CATEGORIES, set by plan.py

    @property
    def course(self) -> str:
        """Like "TCSS 490", from a title (or, for AI items, the source event) ending in "[TCSS 490 A]"."""
        match = COURSE_TAG.search(self.title) or COURSE_TAG.search(self.source)
        return match.group(1) if match else ""

    @property
    def short_title(self) -> str:
        """The title without its course tag."""
        return COURSE_TAG.sub("", self.title) or self.title

    @property
    def day(self) -> date:
        return day_of(self.due)

    @property
    def day_label(self) -> str:
        """Like "Fri Oct 23"."""
        return f"{self.due:%a %b} {self.due.day}"

    @property
    def time_label(self) -> str:
        """Like "11:59 PM", or "" for all-day items."""
        return f"{self.due:%I:%M %p}".lstrip("0") if isinstance(self.due, datetime) else ""

    def to_dict(self) -> dict:
        return {**asdict(self), "due": self.due.isoformat()}

    @classmethod
    def from_dict(cls, data: dict) -> "Item":
        due = data["due"]
        parsed = datetime.fromisoformat(due) if "T" in due else date.fromisoformat(due)
        return cls(**{**data, "due": parsed})


@dataclass(frozen=True)
class Email:
    """One inbox email, as sources/gmail.py reads it. Only these fields are ever read."""

    id: str
    sender: str  # the display name, or the address if there is none
    subject: str
    snippet: str  # Gmail's short preview of the body
    received: datetime
    unread: bool
    important: bool  # Gmail's own "important" label
    url: str  # opens the email in Gmail

    def to_dict(self) -> dict:
        return {**asdict(self), "received": self.received.isoformat()}

    @classmethod
    def from_dict(cls, data: dict) -> "Email":
        return cls(**{**data, "received": datetime.fromisoformat(data["received"])})


def day_of(due: date | datetime) -> date:
    return due.date() if isinstance(due, datetime) else due


def moment(due: date | datetime) -> datetime:
    """An aware local datetime for sorting and comparing. All-day dates count from midnight.

    astimezone() with no argument applies the UTC offset in effect on that date, so this
    stays correct across daylight saving changes.
    """
    return due if isinstance(due, datetime) else datetime.combine(due, time.min).astimezone()


def upcoming(things: list, days: int) -> list:
    """Anything with a `.due` from the start of today up to `days` days ahead, soonest first."""
    today = date.today()
    start, end = moment(today), moment(today + timedelta(days=days))
    return sorted((t for t in things if start <= moment(t.due) < end), key=lambda t: moment(t.due))


def parents(items: list[Item]) -> dict[int, int]:
    """{index of an AI item: index of the Canvas event it was read from}, for AI items due the
    same day as that event. Those items are details of the event ("submit a single PDF"),
    so the widget shows them under it and the planner doesn't plan them twice."""
    events = {(item.title, item.day): n for n, item in enumerate(items) if item.kind == CALENDAR}
    return {
        n: events[item.source, item.day]
        for n, item in enumerate(items)
        if item.kind == AI and (item.source, item.day) in events
    }
