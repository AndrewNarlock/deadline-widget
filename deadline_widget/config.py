"""config.py - settings and file paths in one place. Settings can be overridden in .env."""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"  # gitignored
CACHE_FILE = DATA_DIR / "cache.json"  # everything the widget shows, written by pipeline.py
EXTRACTIONS_FILE = DATA_DIR / "extractions.json"  # Claude's answers, keyed by a hash of the text
PLANS_FILE = DATA_DIR / "plans.json"  # Claude's plan for today, keyed by a hash of the day and the items
MAIL_FILE = DATA_DIR / "mail.json"  # the emails the widget shows, written by pipeline.refresh_mail
MAIL_RULE_FILE = DATA_DIR / "mail_rule.json"  # the rule typed on the Email page
MAIL_ANSWERS_FILE = DATA_DIR / "mail_answers.json"  # Claude's email picks, keyed by a hash of the rule and the emails
GMAIL_CREDENTIALS_FILE = DATA_DIR / "gmail_credentials.json"  # the OAuth client downloaded from Google Cloud
GMAIL_TOKEN_FILE = DATA_DIR / "gmail_token.json"  # a secret: the login, saved after the first sign-in

load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


FEED_URL = _env("CANVAS_FEED_URL")  # a secret: never print it or put it in an error message
COURSE_PAGES = [url.strip() for url in _env("COURSE_PAGES").split(",") if url.strip()]

# Dates Claude reads from text must fall inside the term, or the validator rejects them.
TERM_START = date.fromisoformat(_env("TERM_START", "2026-09-30"))
TERM_END = date.fromisoformat(_env("TERM_END", "2026-12-18"))

CLAUDE_MODEL = _env("CLAUDE_MODEL", "haiku")
DAYS_AHEAD = int(_env("DAYS_AHEAD", "30"))
DAILY_MINUTES = int(_env("DAILY_MINUTES", "180"))  # study time per day that today's plan may fill
REFRESH_MINUTES = 30
