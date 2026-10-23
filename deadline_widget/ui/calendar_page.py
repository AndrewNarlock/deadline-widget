"""calendar_page.py - the Calendar page. Only displays data/cache.json.

Today's plan on top, then checkboxes for the sections (assignments, readings, exams & quizzes)
and for each course, then one list with the checked sections, filtered to the checked courses.
AI-found details of a Canvas event show under that event's card. ▾ in the header hides the list.
"""

import tkinter as tk
from datetime import date

from .. import config, pipeline
from ..models import AI, ASSIGNMENT, EXAM, READING, Item, moment, parents
from .parts import (
    AI_COLOR, BG, CARD, CARD_WRAP, FG, FONT, HEADING, MUTED, PAD, SMALL, SMALL_BOLD, TITLE, WIDTH, ScrollList,
    ai_line, make_clickable,
)

MAX_CARDS = 8  # per section; the rest are counted as "+N more"
MAX_DETAILS = 3  # AI-found details shown under a Canvas card
DUE_TODAY = "#ff7b72"
DUE_SOON = "#f0b45b"  # due within two days
NO_COURSE = "Other"  # course checkbox for items without a course code
SECTIONS = [  # (category, heading, accent color)
    (ASSIGNMENT, "Assignments", "#6cb6ff"),
    (READING, "Readings", "#7ee2a8"),
    (EXAM, "Exams & quizzes", "#ff9bce"),
]


class CalendarPage:
    def __init__(self, app) -> None:
        self.app = app
        px = app.px
        self.collapsed = False
        self._items: list[Item] = []
        self._hidden_sections: set[str] = set()  # unchecked boxes; anything new starts checked
        self._hidden_courses: set[str] = set()

        self.frame = tk.Frame(app.root, bg=BG)
        self.plan_box = tk.Frame(self.frame, bg=CARD, padx=px(10), pady=px(8))
        self.plan_box.pack(fill="x", padx=PAD)
        self.body = tk.Frame(self.frame, bg=BG)  # the checkboxes and the list; ▾ hides it
        self.body.pack(fill="both", expand=True, padx=PAD, pady=(12, 0))
        self.filters = tk.Frame(self.body, bg=BG)
        self.filters.pack(fill="x")
        self.list = ScrollList(self.body, px)
        self.list.frame.pack(fill="both", expand=True, pady=(8, 0))

    def pack(self) -> None:
        self.frame.pack(fill="both", expand=True)

    def show(self, snapshot: dict, error: str | None = None) -> None:
        for child in self.plan_box.winfo_children():
            child.destroy()
        self._show_plan(pipeline.todays_plan(snapshot))
        start = moment(date.today())
        self._items = [item for item in pipeline.snapshot_items(snapshot) if moment(item.due) >= start]
        self._show_list()
        status = pipeline.status_line(snapshot)
        self.app.set_status(self, f"{error}\n{status}" if error else status)
        self.app.fit()

    def toggle_list(self) -> None:
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.body.pack_forget()
        else:
            self.body.pack(fill="both", expand=True, padx=PAD, pady=(12, 0), after=self.plan_box)
        self.app.fit()

    def _show_plan(self, plan: list[tuple[Item, int, str]]) -> None:
        box, px = self.plan_box, self.app.px
        top = tk.Frame(box, bg=CARD)
        top.pack(fill="x")
        tk.Label(top, text="TODAY'S PLAN", font=SMALL_BOLD, bg=CARD, fg=AI_COLOR).pack(side="left")
        tk.Label(top, text="by Claude", font=SMALL, bg=CARD, fg=MUTED).pack(side="left", padx=6)
        if not plan:
            tk.Label(box, text="No plan yet. It appears after the next refresh.", font=FONT, bg=CARD, fg=MUTED).pack(
                anchor="w", pady=(4, 0)
            )
            return
        total = sum(minutes for _, minutes, _ in plan)
        tk.Label(top, text=f"{total} of {config.DAILY_MINUTES} min", font=SMALL, bg=CARD, fg=MUTED).pack(side="right")
        for number, (item, minutes, reason) in enumerate(plan, 1):
            row = tk.Frame(box, bg=CARD)
            row.pack(fill="x", pady=(6, 0))
            tk.Label(row, text=str(number), font=TITLE, bg=CARD, fg=AI_COLOR, width=2, anchor="nw").pack(
                side="left", anchor="n"
            )
            body = tk.Frame(row, bg=CARD)
            body.pack(side="left", fill="x", expand=True)
            line = tk.Frame(body, bg=CARD)
            line.pack(fill="x")
            tk.Label(
                line, text=item.short_title, font=FONT, bg=CARD, fg=FG, anchor="w", justify="left",
                wraplength=px(WIDTH - 2 * PAD - 120),
            ).pack(side="left")
            tk.Label(line, text=f"{minutes} min", font=SMALL_BOLD, bg=CARD, fg=AI_COLOR).pack(side="right")
            meta = " · ".join(part for part in (_due_text(item), item.course, reason) if part)
            tk.Label(
                body, text=meta, font=SMALL, bg=CARD, fg=MUTED, anchor="w", justify="left",
                wraplength=px(WIDTH - 2 * PAD - 60),
            ).pack(fill="x")
            make_clickable(row, item.url)

    def _show_list(self) -> None:
        """Draw the checkboxes, then the checked sections, keeping only the checked courses."""
        for child in self.filters.winfo_children():
            child.destroy()
        self.list.clear()
        self._show_filters()

        box, px = self.list.box, self.app.px
        items = self._items
        details = parents(items)
        groups: dict[str, list[int]] = {category: [] for category, _, _ in SECTIONS}
        children: dict[int, list[Item]] = {}
        for n, item in enumerate(items):
            parent = details.get(n)
            if parent is not None and item.category != READING:
                children.setdefault(parent, []).append(item)  # shown under its Canvas card
            else:
                groups.get(item.category, groups[ASSIGNMENT]).append(n)

        shown_any = False
        for category, heading, accent in SECTIONS:
            if category in self._hidden_sections:
                continue
            indices = [n for n in groups[category] if _course(items[n]) not in self._hidden_courses]
            shown_any = True
            top = tk.Frame(box, bg=BG)
            top.pack(fill="x", pady=(4, 6))
            tk.Frame(top, width=px(8), height=px(8), bg=accent).pack(side="left", padx=(0, 6))
            tk.Label(top, text=heading.upper(), font=HEADING, bg=BG, fg=FG).pack(side="left")
            tk.Label(top, text=str(len(indices)), font=SMALL, bg=BG, fg=MUTED).pack(side="left", padx=6)
            if not indices:
                tk.Label(box, text="Nothing due.", font=FONT, bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 6))
            for n in indices[:MAX_CARDS]:
                self._add_card(items[n], accent, children.get(n, []))
            if len(indices) > MAX_CARDS:
                tk.Label(box, text=f"+{len(indices) - MAX_CARDS} more", font=SMALL, bg=BG, fg=MUTED).pack(
                    anchor="w", pady=(0, 6)
                )
        if not shown_any:
            tk.Label(box, text="Check a section to see its items.", font=FONT, bg=BG, fg=MUTED).pack(anchor="w")
        if self.app.page is self:
            self.app.size_list()

    def _show_filters(self) -> None:
        sections = tk.Frame(self.filters, bg=BG)
        sections.pack(fill="x")
        for category, heading, accent in SECTIONS:
            self._checkbox(sections, heading, accent, self._hidden_sections, category)
        courses = sorted({_course(item) for item in self._items}, key=lambda name: (name == NO_COURSE, name))
        if courses:
            row = tk.Frame(self.filters, bg=BG)
            row.pack(fill="x", pady=(4, 0))
            for course in courses:
                self._checkbox(row, course, FG, self._hidden_courses, course)

    def _checkbox(self, parent: tk.Widget, text: str, color: str, hidden: set[str], key: str) -> None:
        """A box that adds `key` to `hidden` when unchecked, and redraws the list."""
        checked = key not in hidden
        box = tk.Label(
            parent, text=f"{'☑' if checked else '☐'} {text}", font=SMALL_BOLD if checked else SMALL, bg=BG,
            fg=color if checked else MUTED, cursor="hand2",
        )
        box.pack(side="left", padx=(0, 12))

        def toggle(_) -> None:
            hidden.symmetric_difference_update({key})
            self._show_list()
            self.app.fit()

        box.bind("<Button-1>", toggle)

    def _add_card(self, item: Item, accent: str, details: list[Item]) -> None:
        px = self.app.px
        card = tk.Frame(self.list.box, bg=CARD)
        card.pack(fill="x", pady=(0, 6))
        tk.Frame(card, width=px(3), bg=accent).pack(side="left", fill="y")
        body = tk.Frame(card, bg=CARD, padx=px(8), pady=px(5))
        body.pack(side="left", fill="x", expand=True)
        wrap = px(CARD_WRAP)
        tk.Label(body, text=item.short_title, font=FONT, bg=CARD, fg=FG, anchor="w", justify="left", wraplength=wrap).pack(
            fill="x"
        )

        meta = tk.Frame(body, bg=CARD)
        meta.pack(fill="x")
        days_left = (item.day - date.today()).days
        due_color = DUE_TODAY if days_left <= 0 else DUE_SOON if days_left <= 2 else MUTED
        tk.Label(meta, text=_due_text(item), font=SMALL, bg=CARD, fg=due_color).pack(side="left")
        if item.course:
            tk.Label(meta, text=item.course, font=SMALL, bg=CARD, fg=MUTED).pack(side="left", padx=(6, 0))
        if item.kind == AI:
            tk.Label(meta, text="AI", font=SMALL_BOLD, bg=CARD, fg=AI_COLOR).pack(side="left", padx=(6, 0))
            tk.Label(meta, text=f"~{item.est_minutes} min", font=SMALL, bg=CARD, fg=MUTED).pack(side="left", padx=(4, 0))

        for detail in details[:MAX_DETAILS]:
            ai_line(body, f"{detail.title}  ~{detail.est_minutes} min", wrap - px(20))
        if len(details) > MAX_DETAILS:
            tk.Label(body, text=f"+{len(details) - MAX_DETAILS} more", font=SMALL, bg=CARD, fg=MUTED).pack(anchor="w")
        make_clickable(card, item.url)


def _due_text(item: Item) -> str:
    """Like "Today 11:59 PM", "Tomorrow", or "Sun Oct 25 11:59 PM"."""
    days_left = (item.day - date.today()).days
    day = "Today" if days_left == 0 else "Tomorrow" if days_left == 1 else item.day_label
    return f"{day} {item.time_label}".strip()


def _course(item: Item) -> str:
    return item.course or NO_COURSE
