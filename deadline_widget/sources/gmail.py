"""gmail.py - plain code. Signs in to Gmail (read-only) and reads recent inbox emails.

Only the sender, subject, Gmail's short preview ("snippet") and labels are read, never the
whole email. The login is saved in data/gmail_token.json (gitignored) after the first sign-in.

    python -m deadline_widget.sources.gmail    # sign in (opens the browser the first time) and list recent emails

The Google libraries are imported inside the functions that use them, so the tests and the
widget's start-up don't wait for them.
"""

import html
import sys
from datetime import datetime
from email.utils import parseaddr
from urllib.parse import quote

from .. import config
from ..models import Email

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
LOGIN_COMMAND = "python -m deadline_widget.sources.gmail"


class GmailError(RuntimeError):
    """Gmail could not be reached, or the widget isn't signed in."""


def credentials(login: bool = False):
    """The saved login, refreshed if needed. With login=True, sign in through the browser if there is none."""
    from google.auth.exceptions import RefreshError, TransportError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = None
    if config.GMAIL_TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(config.GMAIL_TOKEN_FILE), SCOPES)
        except ValueError:  # an unreadable token file: sign in again
            creds = None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
            return creds
        except TransportError:
            raise GmailError("Could not reach Google to refresh the Gmail login") from None
        except RefreshError:  # revoked, or expired (logins in Google's testing mode last 7 days)
            creds = None
    if not login:
        raise GmailError(f"Gmail is not connected. Run: {LOGIN_COMMAND}")
    if not config.GMAIL_CREDENTIALS_FILE.exists():
        raise GmailError("data/gmail_credentials.json is missing (see README, Gmail setup)")
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(config.GMAIL_CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds)
    return creds


def fetch(query: str, limit: int) -> list[Email]:
    """Emails matching a Gmail search (like "in:inbox newer_than:14d"), newest first."""
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from httplib2 import HttpLib2Error

    service = build("gmail", "v1", credentials=credentials(), cache_discovery=False)
    messages = service.users().messages()
    try:
        account = service.users().getProfile(userId="me").execute()["emailAddress"]
        found = messages.list(userId="me", q=query, maxResults=limit).execute().get("messages", [])
        raw = [
            messages.get(userId="me", id=m["id"], format="metadata", metadataHeaders=["From", "Subject"]).execute()
            for m in found
        ]
    except HttpError as error:
        raise GmailError(f"Gmail returned an error ({error.resp.status})") from None
    except (OSError, HttpLib2Error) as error:  # no network, timeouts
        raise GmailError(f"Could not reach Gmail ({type(error).__name__})") from None
    return [parse_message(message, account) for message in raw]


def parse_message(message: dict, account: str) -> Email:
    """One message from the Gmail API (format="metadata") as an Email."""
    headers = {h.get("name", "").lower(): h.get("value", "") for h in message.get("payload", {}).get("headers", [])}
    name, address = parseaddr(headers.get("from", ""))
    labels = message.get("labelIds", [])
    received = datetime.fromtimestamp(int(message.get("internalDate", 0)) / 1000).astimezone()
    return Email(
        id=message["id"],
        sender=name or address or "(unknown sender)",
        subject=" ".join(headers.get("subject", "").split()) or "(no subject)",
        snippet=" ".join(html.unescape(message.get("snippet", "")).split()),
        received=received,
        unread="UNREAD" in labels,
        important="IMPORTANT" in labels,
        url=f"https://mail.google.com/mail/?authuser={quote(account)}#all/{message['id']}",
    )


def _save_token(creds) -> None:
    config.GMAIL_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.GMAIL_TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")


def main() -> None:
    try:
        credentials(login=True)
        emails = fetch("in:inbox newer_than:7d", 10)
    except GmailError as error:
        sys.exit(str(error))
    print("Gmail is connected. Newest inbox emails:")
    for email in emails:
        print(f"  {email.received:%b %d %I:%M %p}  {email.sender[:24]:<24}  {email.subject[:60]}")


if __name__ == "__main__":
    main()
