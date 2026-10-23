"""parts.py - what both pages share: sizes, colors, fonts, the scrolling list and clickable cards."""

import tkinter as tk
import webbrowser
from tkinter import ttk

WIDTH = 420  # at 100% display scaling; see App.px
PAD = 14
SCROLLBAR = 8
CARD_WRAP = WIDTH - 2 * PAD - SCROLLBAR - 28  # text width inside a card
LIST_WIDTH = WIDTH - 2 * PAD - SCROLLBAR - 4

BG = "#18191d"
CARD = "#23252b"
CARD_HOVER = "#2c2f37"
FG = "#e8e8ea"
MUTED = "#9a9ca5"
AI_COLOR = "#c39bff"  # everything Claude produced is marked in this color

FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
SMALL = ("Segoe UI", 8)
SMALL_BOLD = ("Segoe UI", 8, "bold")
HEADING = ("Segoe UI Semibold", 9)
TITLE = ("Segoe UI", 11, "bold")

SCROLLBAR_STYLE = "Dark.Vertical.TScrollbar"


def set_scrollbar_style(root: tk.Tk, px) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")  # the only built-in theme whose scrollbar colors can be changed
    style.configure(
        SCROLLBAR_STYLE, background=CARD_HOVER, troughcolor=BG, bordercolor=BG,
        lightcolor=CARD_HOVER, darkcolor=CARD_HOVER, arrowcolor=MUTED, arrowsize=px(SCROLLBAR),
    )
    style.map(SCROLLBAR_STYLE, background=[("active", MUTED)])


class ScrollList:
    """A column of widgets (`box`) that scrolls, with a thin scrollbar shown only when it doesn't fit."""

    def __init__(self, parent: tk.Widget, px) -> None:
        width = px(LIST_WIDTH)
        self.frame = tk.Frame(parent, bg=BG)
        self.frame.grid_rowconfigure(0, weight=1)
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_columnconfigure(1, minsize=px(SCROLLBAR + 4))  # room for the scrollbar, shown or not
        self.view = tk.Canvas(self.frame, bg=BG, highlightthickness=0, width=width, yscrollincrement=px(24))
        self.view.grid(row=0, column=0, sticky="nsew")
        self.box = tk.Frame(self.view, bg=BG)
        self.view.create_window(0, 0, window=self.box, anchor="nw", width=width)
        self.scrollbar = ttk.Scrollbar(self.frame, orient="vertical", command=self.view.yview, style=SCROLLBAR_STYLE)
        self.scrollbar.grid(row=0, column=1, sticky="nse")
        self.view.configure(yscrollcommand=self.scrollbar.set)
        for part in (self.view, self.box):
            part.bind("<Configure>", self.update_scrollbar)

    def clear(self) -> None:
        for child in self.box.winfo_children():
            child.destroy()

    def update_scrollbar(self, _=None) -> None:
        """Show the scrollbar only while the list is taller than the space it has."""
        content = self.box.winfo_reqheight()
        self.view.configure(scrollregion=(0, 0, 0, content))
        if content > self.view.winfo_height():
            self.scrollbar.grid()
        else:
            self.scrollbar.grid_remove()
            self.view.yview_moveto(0)

    def scroll(self, event: tk.Event) -> None:
        if self.box.winfo_reqheight() > self.view.winfo_height():
            self.view.yview_scroll(-event.delta // 120, "units")


def icon_button(parent: tk.Widget, text: str, command) -> tk.Label:
    button = tk.Label(parent, text=text, font=TITLE, bg=BG, fg=MUTED, cursor="hand2")
    button.bind("<Button-1>", lambda _: command())
    return button


def ai_line(parent: tk.Widget, text: str, wrap: int) -> None:
    """A small "AI" badge followed by text Claude wrote, under a card's title."""
    line = tk.Frame(parent, bg=CARD)
    line.pack(fill="x", pady=(2, 0))
    tk.Label(line, text="AI", font=SMALL_BOLD, bg=CARD, fg=AI_COLOR).pack(side="left", anchor="n")
    tk.Label(line, text=text, font=SMALL, bg=CARD, fg=MUTED, anchor="w", justify="left", wraplength=wrap).pack(
        side="left", fill="x", padx=(4, 0)
    )


def make_clickable(card: tk.Frame, url: str) -> None:
    """Open `url` on click and light the card up on hover. Only web links are opened."""
    if not url.startswith(("https://", "http://")):
        return
    widgets = [card, *_descendants(card)]
    painted = [w for w in widgets if w.cget("bg") == CARD]  # leave the accent bar alone

    def paint(color: str) -> None:
        for widget in painted:
            widget.configure(bg=color)

    def leave(_) -> None:  # <Leave> also fires when moving onto a child, so check the pointer
        x, y = card.winfo_pointerxy()
        inside = 0 <= x - card.winfo_rootx() < card.winfo_width() and 0 <= y - card.winfo_rooty() < card.winfo_height()
        if not inside:
            paint(CARD)

    for widget in widgets:
        widget.configure(cursor="hand2")
        widget.bind("<Button-1>", lambda _: webbrowser.open(url))
        widget.bind("<Enter>", lambda _: paint(CARD_HOVER))
        widget.bind("<Leave>", leave)


def _descendants(widget: tk.Widget) -> list[tk.Widget]:
    found = []
    for child in widget.winfo_children():
        found += [child, *_descendants(child)]
    return found
