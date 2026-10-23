"""Tests for the validator, response parsing, batching and the hash cache. Claude is faked."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from deadline_widget.ai.claude import ClaudeError, parse_response
from deadline_widget.ai.extract import Source, extract, validate_items
from deadline_widget.cache import AnswerCache
from deadline_widget.models import AI

WEEK4 = Source(
    id="week4",
    label="Week 4",
    text="Before Friday, read Chapter 3 (pp. 40–55) of the textbook.\nQuiz 2 opens Monday.",
    url="https://example.edu/week4",
)
WEEK5 = Source(id="week5", label="Week 5", text="Nothing is due this week. Enjoy the break.")
DATED = Source(
    id="dated",
    label="Reflection 5",
    text="Peer feedback replies are due Saturday. Replies due Tuesday, November 10. Read the Oct 22nd handout.",
)


def raw(**overrides) -> dict:
    return {"source_id": "s1", "task": "read Chapter 3", "due": "2026-10-23", "est_minutes": 45, **overrides}


class ValidateItemsTest(unittest.TestCase):
    def test_good_item_passes(self):
        valid, rejections = validate_items([raw()], WEEK4)
        self.assertEqual(rejections, [])
        [item] = valid
        self.assertEqual(item.title, "read Chapter 3")
        self.assertEqual(item.due, date(2026, 10, 23))
        self.assertEqual((item.kind, item.source, item.url, item.est_minutes), (AI, "Week 4", WEEK4.url, 45))

    def test_task_match_ignores_case_spacing_and_punctuation(self):
        valid, _ = validate_items([raw(task="Read  chapter 3 (pp. 40-55)")], WEEK4)
        self.assertEqual(len(valid), 1)

    def test_due_must_match_a_weekday_or_date_named_in_the_task(self):
        # The first case is a real mistake Claude made: "due Saturday" came back as a Monday.
        for task, right, wrong in [
            ("Peer feedback replies are due Saturday", "2026-10-24", "2026-10-26"),
            ("Replies due Tuesday, November 10", "2026-11-10", "2026-11-11"),
            ("Read the Oct 22nd handout", "2026-10-22", "2026-10-21"),
        ]:
            with self.subTest(task):
                self.assertEqual(len(validate_items([raw(task=task, due=right)], DATED)[0]), 1)
                self.assertEqual(len(validate_items([raw(task=task, due=wrong)], DATED)[1]), 1)

    def test_bad_items_are_rejected_with_a_reason(self):
        bad = {
            "invented reading": raw(task="read Chapter 9"),
            "partial word": raw(task="read Chapt"),
            "only punctuation": raw(task="!!!"),
            "outside the term": raw(due="2027-03-01"),
            "not a real date": raw(due="2026-02-30"),
            "wrong date format": raw(due="Oct 23"),
            "boolean minutes": raw(est_minutes=True),
            "zero minutes": raw(est_minutes=0),
            "minutes as text": raw(est_minutes="45"),
            "missing task": {"due": "2026-10-23", "est_minutes": 45},
            "not an object": "read Chapter 3",
        }
        for case, item in bad.items():
            with self.subTest(case):
                valid, rejections = validate_items([item], WEEK4)
                self.assertEqual(valid, [])
                self.assertEqual(len(rejections), 1)


class ParseResponseTest(unittest.TestCase):
    def test_reads_structured_output(self):
        stdout = json.dumps({"is_error": False, "result": "", "structured_output": {"items": [raw()]}})
        self.assertEqual(parse_response(stdout), {"items": [raw()]})

    def test_unusable_output_raises(self):
        for stdout in [
            "not json",
            json.dumps(["a list"]),
            json.dumps({"is_error": True, "result": "rate limited"}),
            json.dumps({"is_error": False, "result": "no structured output"}),
            json.dumps({"is_error": False, "structured_output": ["not an object"]}),
        ]:
            with self.subTest(stdout=stdout), self.assertRaises(ClaudeError):
                parse_response(stdout)


class ExtractTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.cache_path = Path(folder.name) / "extractions.json"
        self.calls: list[list[str]] = []

    def fake_claude(self, sources: dict[str, Source]) -> list:
        self.calls.append([source.id for source in sources.values()])
        answer = [raw(source_id=sid) for sid, source in sources.items() if "Chapter 3" in source.text]
        return answer + [raw(source_id="s99")]  # an item naming a source that was never sent

    def run_extract(self, sources, fresh=False):
        return extract(sources, AnswerCache(self.cache_path), fresh=fresh, ask=self.fake_claude)

    def test_all_new_text_goes_in_one_call_then_comes_from_the_cache(self):
        first = self.run_extract([WEEK4, WEEK5])
        self.assertEqual(self.calls, [["week4", "week5"]])
        self.assertEqual([item.title for item in first.items], ["read Chapter 3"])
        self.assertEqual(len(first.rejections), 1)  # the s99 item

        second = self.run_extract([WEEK4, WEEK5])
        self.assertEqual(len(self.calls), 1)  # nothing changed, so Claude wasn't asked
        self.assertEqual((second.calls, second.cached), (0, 2))
        self.assertEqual(second.items, first.items)

    def test_only_changed_text_is_sent_again(self):
        self.run_extract([WEEK4, WEEK5])
        changed = Source(id="week5", label="Week 5", text="Read Chapter 3 again before the quiz.")
        self.run_extract([WEEK4, changed])
        self.assertEqual(self.calls, [["week4", "week5"], ["week5"]])

    def test_fresh_ignores_the_cache(self):
        self.run_extract([WEEK4])
        self.run_extract([WEEK4], fresh=True)
        self.assertEqual(self.calls, [["week4"], ["week4"]])

    def test_same_task_from_two_texts_shows_once(self):
        copy = Source(id="copy", label="Copy", text=WEEK4.text)
        report = self.run_extract([WEEK4, copy])
        self.assertEqual(len(report.items), 1)

    def test_claude_failure_is_reported_not_raised(self):
        def broken(sources):
            raise ClaudeError("claude -p exited with code 1")

        report = extract([WEEK4], AnswerCache(self.cache_path), ask=broken)
        self.assertEqual((report.items, report.calls), ([], 0))
        self.assertIn("code 1", report.error)


if __name__ == "__main__":
    unittest.main()
