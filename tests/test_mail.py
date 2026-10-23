"""Tests for the email step: reading Gmail's message format, the validator and the cache.
Gmail and Claude are faked."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from deadline_widget.ai.claude import ClaudeError
from deadline_widget.ai.mail_filter import MAX_WHY_CHARS, clean_rule, filter_emails, filter_request, validate_matches
from deadline_widget.cache import AnswerCache
from deadline_widget.models import Email
from deadline_widget.sources.gmail import parse_message


def email(n: int, subject: str, important: bool = False) -> Email:
    return Email(
        id=f"m{n}", sender=f"Sender {n}", subject=subject, snippet="preview", received=datetime(2026, 10, 23 - n),
        unread=True, important=important, url=f"https://mail.google.com/mail/#all/m{n}",
    )


EMAILS = [email(1, "Software intern posting"), email(2, "Weekly newsletter"), email(3, "New grad role", True)]


class ParseMessageTests(unittest.TestCase):
    def test_reads_headers_labels_and_link(self):
        message = {
            "id": "18abc",
            "labelIds": ["INBOX", "UNREAD", "IMPORTANT"],
            "snippet": "We&#39;re hiring   interns",
            "internalDate": "1792000000000",
            "payload": {"headers": [{"name": "From", "value": "Handshake <no-reply@handshake.com>"},
                                    {"name": "Subject", "value": "New  job\n posting"}]},
        }
        parsed = parse_message(message, "me@gmail.com")
        self.assertEqual(parsed.sender, "Handshake")
        self.assertEqual(parsed.subject, "New job posting")
        self.assertEqual(parsed.snippet, "We're hiring interns")
        self.assertTrue(parsed.unread and parsed.important)
        self.assertEqual(parsed.url, "https://mail.google.com/mail/?authuser=me%40gmail.com#all/18abc")

    def test_missing_headers_get_placeholders(self):
        parsed = parse_message({"id": "1", "payload": {}}, "me@gmail.com")
        self.assertEqual((parsed.sender, parsed.subject), ("(unknown sender)", "(no subject)"))
        self.assertFalse(parsed.unread)

    def test_round_trip(self):
        self.assertEqual(Email.from_dict(EMAILS[0].to_dict()), EMAILS[0])


class ValidateMatchesTests(unittest.TestCase):
    def test_keeps_good_matches_in_email_order(self):
        answer = {"matches": [{"id": "e3", "why": "New grad job."}, {"id": "e1", "why": "Internship posting."}]}
        matches, rejections = validate_matches(answer, EMAILS)
        self.assertEqual(matches, [(0, "Internship posting."), (2, "New grad job.")])
        self.assertEqual(rejections, [])

    def test_rejects_unknown_ids_and_repeats(self):
        answer = {"matches": [{"id": "e9", "why": "x"}, {"id": "m1", "why": "x"}, {"id": "e1", "why": "Job."},
                              {"id": "e1", "why": "Job again."}]}
        matches, rejections = validate_matches(answer, EMAILS)
        self.assertEqual(matches, [(0, "Job.")])
        self.assertEqual(len(rejections), 3)
        self.assertIn("picked twice", rejections[-1])

    def test_rejects_bad_why(self):
        answer = {"matches": [{"id": "e1", "why": ""}, {"id": "e2", "why": "x" * (MAX_WHY_CHARS + 1)},
                              {"id": "e3", "why": "Apply at https://evil.example"}]}
        matches, rejections = validate_matches(answer, EMAILS)
        self.assertEqual(matches, [])
        self.assertEqual([r.split(": ")[1].split(" (")[0] for r in rejections],
                         ["missing why", "why is too long", "why contains a link"])

    def test_junk_answer_shows_nothing(self):
        for junk in (None, "matches", {"matches": "e1"}, {"matches": [None, 5]}):
            self.assertEqual(validate_matches(junk, EMAILS)[0], [])


class FilterEmailsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "answers.json"

    def test_rule_goes_in_the_instruction_and_emails_on_stdin(self):
        seen = []

        def ask(rule, document):
            seen.append((rule, document))
            return {"matches": [{"id": "e1", "why": "Internship."}]}

        report = filter_emails(EMAILS, "  only\njob postings ", AnswerCache(self.path), ask=ask)
        self.assertEqual(seen[0][0], "only job postings")
        self.assertEqual(seen[0][1], filter_request(EMAILS))
        self.assertNotIn("only job postings", str(seen[0][1]))
        self.assertEqual((report.matches, report.calls), ([(0, "Internship.")], 1))

    def test_same_rule_and_emails_use_the_cache(self):
        ask = lambda rule, document: {"matches": [{"id": "e1", "why": "Internship."}]}
        filter_emails(EMAILS, "jobs", AnswerCache(self.path), ask=ask)

        def fail(rule, document):
            raise AssertionError("Claude should not be asked again")

        report = filter_emails(EMAILS, "jobs", AnswerCache(self.path), ask=fail)
        self.assertTrue(report.cached)
        self.assertEqual(report.matches, [(0, "Internship.")])

    def test_claude_error_is_reported(self):
        def broken(rule, document):
            raise ClaudeError("timed out")

        report = filter_emails(EMAILS, "jobs", AnswerCache(self.path), ask=broken)
        self.assertEqual((report.matches, report.error), ([], "timed out"))

    def test_no_rule_asks_nothing(self):
        report = filter_emails(EMAILS, "   ", AnswerCache(self.path), ask=lambda *_: self.fail("asked Claude"))
        self.assertEqual(report.calls, 0)

    def test_clean_rule(self):
        self.assertEqual(clean_rule(" a\n b " + "c" * 300)[:5], "a b c")
        self.assertEqual(len(clean_rule("c" * 300)), 200)


if __name__ == "__main__":
    unittest.main()
