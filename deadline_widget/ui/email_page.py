"""email_page.py - the Email page. Only displays data/mail.json.

A "Show me" box takes a rule in plain words ("only job postings"). Pressing Enter saves it and
refreshes, so Claude picks the emails that fit (ai/mail_filter.py). Each email Claude picked
shows its "why" with an AI badge. With no rule, it shows Gmail's important emails.
"""

import tkinter as tk
from datetime import date, datetime

from .. import pipeline
from ..models import Email
from ..sources.gmail import LOGIN_COMMAND
from .parts import (
    AI_COLOR, BG, CARD, CARD_HOVER, CARD_WRAP, FG, FONT, FONT_BOLD, MUTED, PAD, SMALL, SMALL_BOLD, WIDTH,
    ScrollList, ai_line, icon_button, make_clickable,
)

UNREAD = "#6cb6ff"  # the bar on an unread email's card
NO_RULE_HINT = 'Type a rule like "only job postings" and press Enter. With no rule, this shows Gmail\'s important emails.'


class EmailPage:
    def __init__(self, app) -> None:
        self.app = app
        px = app.px
        self.frame = tk.Frame(app.root, bg=BG)
        rule_row = tk.Frame(self.frame, bg=BG)
        rule_row.pack(fill="x")
        tk.Label(rule_row, text="SHOW ME", font=SMALL_BOLD, bg=BG, fg=AI_COLOR).pack(side="left", padx=(0, 8))
        icon_button(rule_row, "×", lambda: self._set_rule("")).pack(side="right", padx=(8, 0))
        self.rule_entry = tk.Entry(
            rule_row, font=FONT, bg=CARD, fg=FG, insertbackground=FG, relief="flat", highlightthickness=1,
            highlightbackground=CARD, highlightcolor=AI_COLOR,
        )
        self.rule_entry.pack(side="left", fill="x", expand=True, ipady=px(3))
        self.rule_entry.insert(0, pipeline.load_rule())
        self.rule_entry.bind("<Return>", lambda _: self._set_rule(self.rule_entry.get()))
        self.rule_entry.bind("<Escape>", lambda _: (app.root.focus_set(), "break")[1])  # don't close the window
        self.rule_hint = tk.Label(
            self.frame, font=SMALL, bg=BG, fg=MUTED, anchor="w", justify="left", wraplength=px(WIDTH - 2 * PAD)
        )
        self.rule_hint.pack(fill="x", pady=(4, 0))
        self.list = ScrollList(self.frame, px)
        self.list.frame.pack(fill="both", expand=True, pady=(8, 0))

    def pack(self) -> None:
        self.frame.pack(fill="both", expand=True, padx=PAD, pady=(4, 0))

    def show(self, snapshot: dict, error: str | None = None) -> None:
        """Draw what the rule does, then the emails, newest first."""
        rule = pipeline.load_rule()
        self.rule_hint.configure(text=f'Claude shows the emails that fit "{rule}". × clears it.' if rule else NO_RULE_HINT)
        self.list.clear()
        emails = pipeline.mail_items(snapshot)
        for email, why in emails:
            self._add_card(email, why)
        if not emails:
            if "not connected" in (snapshot.get("error") or ""):
                text = f"Gmail isn't connected. In the project folder, run:\n{LOGIN_COMMAND}"
            else:
                text = "No emails fit the rule." if snapshot.get("rule") else "No emails yet."
            tk.Label(self.list.box, text=text, font=FONT, bg=BG, fg=MUTED, anchor="w", justify="left").pack(anchor="w")
        status = pipeline.mail_status_line(snapshot)
        self.app.set_status(self, f"{error}\n{status}" if error else status)
        if self.app.page is self:
            self.app.size_list()
            self.app.fit()

    def _add_card(self, email: Email, why: str | None) -> None:
        px = self.app.px
        card = tk.Frame(self.list.box, bg=CARD)
        card.pack(fill="x", pady=(0, 6))
        tk.Frame(card, width=px(3), bg=UNREAD if email.unread else CARD_HOVER).pack(side="left", fill="y")
        body = tk.Frame(card, bg=CARD, padx=px(8), pady=px(5))
        body.pack(side="left", fill="x", expand=True)
        wrap = px(CARD_WRAP)
        tk.Label(
            body, text=email.subject, font=FONT_BOLD if email.unread else FONT, bg=CARD, fg=FG, anchor="w",
            justify="left", wraplength=wrap,
        ).pack(fill="x")
        tk.Label(
            body, text=f"{email.sender} · {_received_text(email.received)}", font=SMALL, bg=CARD, fg=MUTED, anchor="w"
        ).pack(fill="x")
        if why:
            ai_line(body, why, wrap - px(20))
        make_clickable(card, email.url)

    def _set_rule(self, text: str) -> None:
        """Save the rule and refresh, so Claude applies it."""
        pipeline.save_rule(text)
        self.rule_entry.delete(0, "end")
        self.rule_entry.insert(0, pipeline.load_rule())
        self.app.root.focus_set()
        self.show(pipeline.load_mail())
        self.app.refresh(again_if_running=True)  # a refresh already running may have read the old rule


def _received_text(when: datetime) -> str:
    """Like "Today 2:14 PM", "Yesterday" or "Oct 21"."""
    days_ago = (date.today() - when.date()).days
    if days_ago == 0:
        return f"Today {when:%I:%M %p}".replace(" 0", " ")
    return "Yesterday" if days_ago == 1 else f"{when:%b} {when.day}"
