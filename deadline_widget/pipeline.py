"""pipeline.py - plain code that runs every step in order and saves data/cache.json and data/mail.json.

    Canvas feed (sources/feed.py) ---+
                                     +--> Claude + validator (ai/extract.py) --> merge
    course pages (sources/pages.py) -+        --> Claude + validator (ai/plan.py) --> data/cache.json --> Calendar page

    Gmail inbox (sources/gmail.py) --> Claude + validator (ai/mail_filter.py) --> data/mail.json --> Email page

Run it by hand to see exactly what the widget will show:

    python -m deadline_widget.pipeline                 # fetch, extract, print and save
    python -m deadline_widget.pipeline --days 60       # look further ahead
    python -m deadline_widget.pipeline --file my.ics   # a local .ics file instead of the feed
    python -m deadline_widget.pipeline --fresh         # ignore cached answers; ask Claude again
"""

import argparse
import sys
from dataclasses import replace
from datetime import date, datetime

import requests

from . import config
from .ai.extract import Source, extract
from .ai.mail_filter import clean_rule, filter_emails
from .ai.plan import make_plan, steps_to_dicts
from .cache import AnswerCache, read_json, write_json
from .models import CALENDAR, Email, Item, day_of, upcoming
from .sources import feed, gmail, pages

MIN_TEXT_CHARS = 20  # event descriptions shorter than this rarely hold anything to extract
POOL_QUERY = "in:inbox newer_than:14d"  # the emails Claude chooses from when there is a rule
POOL_SIZE = 40
IMPORTANT_QUERY = "in:inbox is:important newer_than:14d"  # shown when there is no rule
MAX_EMAILS = 15  # shown on the Email page


def refresh(days: int = config.DAYS_AHEAD, ics_file: str | None = None, fresh: bool = False) -> dict:
    """Run every step and save the result to data/cache.json. Raises feed.FeedError if the feed fails."""
    events = upcoming(feed.load_events(ics_file), days)
    sources, warnings = gather_sources(events)
    report = extract(sources, AnswerCache(config.EXTRACTIONS_FILE), fresh=fresh)
    items = upcoming([event.to_item() for event in events] + report.items, days)
    planned = make_plan(items, AnswerCache(config.PLANS_FILE), fresh=fresh)
    items = [replace(item, category=category) for item, category in zip(items, planned.categories)]

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    previous = load_snapshot()
    snapshot = {
        "generated_at": now,
        "items": [item.to_dict() for item in items],  # plan steps point into this list by index
        "plan": {
            "date": date.today().isoformat(),
            "steps": steps_to_dicts(planned.steps),
            "last_ran": now if planned.calls else (previous.get("plan") or {}).get("last_ran"),
            "calls": planned.calls,
            "rejected": len(planned.rejections),
            "rejections": planned.rejections,
            "error": planned.error,
        },
        "claude": {
            "last_ran": now if report.calls else (previous.get("claude") or {}).get("last_ran"),
            "calls": report.calls,
            "sources": report.sources,
            "cached": report.cached,
            "extracted": len(report.items),
            "rejected": len(report.rejections),
            "rejections": report.rejections,
            "error": report.error,
        },
        "warnings": warnings,
    }
    write_json(config.CACHE_FILE, snapshot)
    return snapshot


def refresh_mail(fresh: bool = False) -> dict:
    """Read the inbox, let Claude pick the emails that fit the rule, and save data/mail.json.

    With no rule, it shows Gmail's own important emails and Claude isn't asked. If Claude fails,
    it falls back to the important ones. A Gmail error keeps the last emails and reports the error.
    """
    rule = load_rule()
    previous = load_mail()
    snapshot = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "rule": rule,
        "checked": 0,
        "emails": [],
        "claude": None,
        "error": None,
    }
    try:
        pool = gmail.fetch(POOL_QUERY if rule else IMPORTANT_QUERY, POOL_SIZE if rule else MAX_EMAILS)
    except gmail.GmailError as error:
        snapshot.update(emails=previous.get("emails", []), error=str(error))
        write_json(config.MAIL_FILE, snapshot)
        return snapshot

    shown: list[tuple[Email, str | None]] = [(email, None) for email in pool]
    if rule:
        report = filter_emails(pool, rule, AnswerCache(config.MAIL_ANSWERS_FILE), fresh=fresh)
        if report.error:
            shown = [(email, None) for email in pool if email.important]
        else:
            shown = [(pool[n], why) for n, why in report.matches]
        last_ran = snapshot["generated_at"] if report.calls else ((previous.get("claude") or {}).get("last_ran"))
        snapshot["claude"] = {
            "last_ran": last_ran,
            "calls": report.calls,
            "matched": len(report.matches),
            "rejected": len(report.rejections),
            "rejections": report.rejections,
            "error": report.error,
        }
    snapshot["checked"] = len(pool)
    snapshot["emails"] = [{**email.to_dict(), "why": why} for email, why in shown[:MAX_EMAILS]]
    write_json(config.MAIL_FILE, snapshot)
    return snapshot


def load_mail() -> dict:
    """The last saved email result, or {} before the first one."""
    data = read_json(config.MAIL_FILE, {})
    return data if isinstance(data, dict) else {}


def mail_items(snapshot: dict) -> list[tuple[Email, str | None]]:
    """The emails to show, each with Claude's "why" (None when Claude didn't pick it)."""
    try:
        return [(Email.from_dict({k: v for k, v in data.items() if k != "why"}), data.get("why"))
                for data in snapshot.get("emails", [])]
    except (KeyError, TypeError, ValueError):  # a file from an older version
        return []


def load_rule() -> str:
    data = read_json(config.MAIL_RULE_FILE, {})
    return clean_rule(data.get("rule", "")) if isinstance(data, dict) else ""


def save_rule(text: str) -> None:
    write_json(config.MAIL_RULE_FILE, {"rule": clean_rule(text)})


def mail_status_line(snapshot: dict) -> str:
    """A short summary of the email step, for the widget footer on the Email page."""
    if not snapshot:
        return "No emails yet."
    when = _clock(snapshot["generated_at"])
    claude = snapshot.get("claude")
    if snapshot.get("error"):
        line = snapshot["error"]
    elif claude:
        line = f"Checked {snapshot.get('checked', 0)} emails at {when}"
        if claude.get("last_ran"):
            line += f" | Claude read them {_clock(claude['last_ran'])}"
        line += f"\nClaude matched {claude.get('matched', 0)} | {claude.get('rejected', 0)} rejected by the validator"
        if claude.get("error"):
            line += f"\nClaude step failed, so these are Gmail's important emails: {claude['error']}"
    else:
        line = f"Gmail's important emails, checked at {when}"
    return line


def gather_sources(events: list[feed.Event]) -> tuple[list[Source], list[str]]:
    """The texts for Claude: upcoming event descriptions, then the course pages listed in .env."""
    sources = [
        Source(
            id=event.uid or f"{event.title}@{event.due}",
            label=event.title,
            text=event.description,
            url=event.url,
            event_date=day_of(event.due),
        )
        for event in events
        if len(event.description) >= MIN_TEXT_CHARS
    ]
    warnings = []
    for url in config.COURSE_PAGES:
        try:
            title, text = pages.fetch_page(url)
        except requests.RequestException as error:
            warnings.append(f"Could not read {url} ({type(error).__name__})")
            continue
        sources.append(Source(id=url, label=title, text=text, url=url))
    return sources, warnings


def load_snapshot() -> dict:
    """The last saved result, or {} before the first refresh."""
    data = read_json(config.CACHE_FILE, {})
    return data if isinstance(data, dict) else {}


def snapshot_items(snapshot: dict) -> list[Item]:
    try:
        return [Item.from_dict(data) for data in snapshot.get("items", [])]
    except (KeyError, TypeError, ValueError):  # a cache file from an older version
        return []


def todays_plan(snapshot: dict) -> list[tuple[Item, int, str]]:
    """Today's plan as (item, minutes, reason). Empty if the saved plan is from another day."""
    plan = snapshot.get("plan") or {}
    if plan.get("date") != date.today().isoformat():
        return []
    items = snapshot_items(snapshot)
    try:
        return [(items[step["item"]], step["minutes"], step["reason"]) for step in plan.get("steps", [])]
    except (IndexError, KeyError, TypeError):  # a cache file from an older version
        return []


def status_line(snapshot: dict) -> str:
    """A short summary of both Claude steps, for the widget footer and the command line."""
    claude = snapshot.get("claude")
    if not claude:
        return "No data yet."
    plan = snapshot.get("plan") or {}
    last_ran = claude.get("last_ran")
    if claude.get("calls"):
        line = f"Claude read {claude.get('sources', 0) - claude.get('cached', 0)} new texts at {_clock(last_ran)}"
    elif last_ran:
        line = f"No new text for Claude (last read {_clock(last_ran)})"
    else:
        line = "Claude has not read anything yet"
    if plan.get("last_ran"):
        line += f" | planned {_clock(plan['last_ran'])}"
    rejected = claude.get("rejected", 0) + plan.get("rejected", 0)
    line += f"\n{claude.get('extracted', 0)} AI items | {rejected} rejected by the validator"
    if claude.get("error"):
        line += f"\nClaude step failed: {claude['error']}"
    if plan.get("error"):
        line += f"\nPlanning failed: {plan['error']}"
    if snapshot.get("warnings"):
        line += f"\n{len(snapshot['warnings'])} course page(s) could not be read"
    return line


def _clock(iso: str) -> str:
    when = datetime.fromisoformat(iso)
    clock = f"{when:%I:%M %p}".lstrip("0")
    return clock if when.date() == date.today() else f"{when:%b} {when.day} {clock}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch deadlines, run both Claude steps and save data/cache.json.")
    parser.add_argument("--days", type=int, default=config.DAYS_AHEAD, help="how many days ahead to include")
    parser.add_argument("--file", help="read a local .ics file instead of the feed URL")
    parser.add_argument("--fresh", action="store_true", help="ignore cached answers and ask Claude about every text")
    args = parser.parse_args()

    try:
        snapshot = refresh(args.days, args.file, args.fresh)
    except feed.FeedError as error:
        sys.exit(str(error))

    items = snapshot_items(snapshot)
    if not items:
        print(f"Nothing due in the next {args.days} days.")
    for item in items:
        tag = "Canvas" if item.kind == CALENDAR else f"AI ~{item.est_minutes}m"
        print(f"{item.day_label:<11}{item.time_label:>8}  {tag:<9} {item.category:<11} {item.title}")
    print("\nToday's plan:")
    for number, (item, minutes, reason) in enumerate(todays_plan(snapshot), 1):
        print(f"  {number}. {item.short_title} ({minutes} min) - {reason}")
    print(f"\n{status_line(snapshot)}")
    for note in snapshot["claude"]["rejections"] + snapshot["plan"]["rejections"] + snapshot["warnings"]:
        print(f"  - {note}")


if __name__ == "__main__":
    main()
