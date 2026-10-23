"""Tests for today's plan: the validator, the fallback categories and the cache. Claude is faked."""

import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from deadline_widget import config
from deadline_widget.ai.claude import ClaudeError
from deadline_widget.ai.plan import MAX_STEPS, Step, guess_category, make_plan, plan_request, validate_plan
from deadline_widget.cache import AnswerCache
from deadline_widget.models import AI, ASSIGNMENT, CALENDAR, EXAM, READING, Item, parents

TODAY = date(2026, 10, 22)
ITEMS = [
    Item("Unit 3 - Reflection [TCSS 490 A]", TODAY + timedelta(days=3), CALENDAR, "Canvas"),
    Item("submit a single PDF", TODAY + timedelta(days=3), AI, "Unit 3 - Reflection [TCSS 490 A]", est_minutes=60),
    Item("Midterm 1 [TCSS 343 A]", datetime(2026, 10, 28, 13, 30).astimezone(), CALENDAR, "Canvas"),
    Item("Specification and Decomposition", TODAY + timedelta(days=17), AI, "Unit 5 - Quiz [TCSS 490 A]", est_minutes=40),
]


def step(item_id="i1", minutes=60, reason="Due Sunday.") -> dict:
    return {"id": item_id, "minutes": minutes, "reason": reason}


def answer(plan=(), categories=None) -> dict:
    if categories is None:
        categories = [("i1", ASSIGNMENT), ("i2", ASSIGNMENT), ("i3", EXAM), ("i4", READING)]
    return {"categories": [{"id": i, "category": c} for i, c in categories], "plan": list(plan)}


class ValidatePlanTest(unittest.TestCase):
    def test_good_answer_passes(self):
        categories, steps, rejections = validate_plan(
            answer([step("i3", 90, "Midterm on Wednesday."), step("i1", 45)]), ITEMS, TODAY
        )
        self.assertEqual(rejections, [])
        self.assertEqual(categories, [ASSIGNMENT, ASSIGNMENT, EXAM, READING])
        self.assertEqual(steps, [Step(2, 90, "Midterm on Wednesday."), Step(0, 45, "Due Sunday.")])

    def test_bad_steps_are_rejected_with_a_reason(self):
        budget = config.DAILY_MINUTES
        bad = {
            "unknown id": [step("i9")],
            "id zero": [step("i0")],
            "planned twice": [step("i1"), step("i1")],
            "detail of a planned event": [step("i1"), step("i2")],
            "event of a planned detail": [step("i2"), step("i1")],
            "due too far away": [step("i4")],
            "boolean minutes": [step(minutes=True)],
            "too few minutes": [step(minutes=5)],
            "over the daily budget": [step("i3", budget), step("i1", 10)],
            "link in reason": [step(reason="See https://evil.example")],
            "reason too long": [step(reason="word " * 40)],
            "empty reason": [step(reason="  ")],
            "not an object": ["i1"],
        }
        for case, plan in bad.items():
            with self.subTest(case):
                _, steps, rejections = validate_plan(answer(plan), ITEMS, TODAY)
                self.assertEqual(len(steps) + len(rejections), len(plan))
                self.assertEqual(len(rejections), 1)

    def test_at_most_max_steps(self):
        items =ITEMS + [Item(f"Extra {n}", TODAY, CALENDAR, "Canvas") for n in range(MAX_STEPS)]
        many = [step(f"i{n}", 10) for n in (1, 3, 5, 6, 7)]
        _, steps, rejections = validate_plan(answer(many), items, TODAY)
        self.assertEqual(len(steps), MAX_STEPS)
        self.assertEqual(len(rejections), 2)

    def test_missing_or_bad_categories_fall_back_to_a_guess(self):
        categories, _, rejections = validate_plan(
            answer(categories=[("i1", "homework"), ("i9", EXAM)]), ITEMS, TODAY
        )
        self.assertEqual(categories, [ASSIGNMENT, ASSIGNMENT, EXAM, ASSIGNMENT])
        self.assertEqual(len(rejections), 2)

    def test_unusable_answer_still_gives_every_item_a_category(self):
        categories, steps, _ = validate_plan("not an object", ITEMS, TODAY)
        self.assertEqual((len(categories), steps), (len(ITEMS), []))


class GuessCategoryTest(unittest.TestCase):
    def test_guesses(self):
        for title, kind, expected in [
            ("Quiz 2: Data [TCSS 372 A]", CALENDAR, EXAM),
            ("Midterm 1 [TCSS 343 A]", CALENDAR, EXAM),
            ("Unit 3 - Artifact 3: AI Inside It (Final) [TCSS 490 A]", CALENDAR, ASSIGNMENT),
            ("Read Chapter 3", AI, READING),
            ("Assignment 1: Chapter 6 [TCSS 372 A]", CALENDAR, ASSIGNMENT),
        ]:
            with self.subTest(title):
                self.assertEqual(guess_category(Item(title, TODAY, kind, "Canvas")), expected)


class MakePlanTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.cache_path = Path(folder.name) / "plans.json"
        self.requests: list[dict] = []

    def fake_claude(self, document: dict) -> dict:
        self.requests.append(document)
        return answer([step("i3", 90)])

    def run_plan(self, items=ITEMS, today=TODAY, fresh=False):
        return make_plan(items, AnswerCache(self.cache_path), fresh=fresh, ask=self.fake_claude, today=today)

    def test_plans_once_a_day_unless_the_items_change(self):
        first = self.run_plan()
        second = self.run_plan()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual((first.calls, second.calls, second.cached), (1, 0, True))
        self.assertEqual(second.steps, first.steps)

        self.run_plan(today=TODAY + timedelta(days=1))
        self.run_plan(items=ITEMS[:3])
        self.run_plan(fresh=True)
        self.assertEqual(len(self.requests), 4)

    def test_request_marks_details_of_canvas_events(self):
        document = plan_request(ITEMS, TODAY)
        self.assertEqual([entry["id"] for entry in document["items"]], ["i1", "i2", "i3", "i4"])
        self.assertEqual([entry["part_of"] for entry in document["items"]], [None, "i1", None, None])
        self.assertEqual(document["items"][2]["due"], "Wed 2026-10-28 1:30 PM")

    def test_claude_failure_is_reported_not_raised(self):
        def broken(document):
            raise ClaudeError("claude -p exited with code 1")

        report = make_plan(ITEMS, AnswerCache(self.cache_path), ask=broken, today=TODAY)
        self.assertEqual((report.steps, report.calls), ([], 0))
        self.assertEqual(len(report.categories), len(ITEMS))
        self.assertIn("code 1", report.error)

    def test_no_items_means_no_call(self):
        report = self.run_plan(items=[])
        self.assertEqual((self.requests, report.categories, report.steps), ([], [], []))


class ModelsTest(unittest.TestCase):
    def test_course_and_short_title(self):
        self.assertEqual((ITEMS[0].course, ITEMS[0].short_title), ("TCSS 490", "Unit 3 - Reflection"))
        self.assertEqual((ITEMS[1].course, ITEMS[1].short_title), ("TCSS 490", "submit a single PDF"))
        self.assertEqual(Item("Lab", TODAY, CALENDAR, "Canvas").course, "")

    def test_parents_links_details_to_their_event(self):
        self.assertEqual(parents(ITEMS), {1: 0})


if __name__ == "__main__":
    unittest.main()
