"""app.py - the small always-on-top desktop window (Tkinter) that holds both pages.

The window has a header (title, ▾ ↻ ×), links that switch between the Calendar and Email pages,
and a footer with the open page's status line. Each page only displays a file the pipeline wrote.
To keep them current it runs pipeline.refresh() and pipeline.refresh_mail() on a worker thread at
start-up and every REFRESH_MINUTES, then redraws. Only the main thread touches Tkinter; the
worker just leaves its result behind.

    python -m deadline_widget      # open the widget
    pythonw -m deadline_widget     # same, without a console window

Drag the title to move it, and the bottom edge to resize it (double-click there to fit again).
Click a card to open its link. ▾ hides the calendar list, ↻ refreshes now, × or Esc closes.
"""

import ctypes
import socket
import threading
import tkinter as tk
from datetime import date

from .. import config, pipeline
from .calendar_page import CalendarPage
from .email_page import EmailPage
from .parts import BG, CARD_HOVER, FG, MUTED, PAD, SMALL, SMALL_BOLD, TITLE, WIDTH, icon_button, set_scrollbar_style

GRIP = 12  # the strip along the bottom edge that resizes the window
MIN_HEIGHT = 200
POLL_MS = 300  # how often to check whether a refresh has finished
REJECTED_TIP = "Answers from Claude that failed a code check (like text not found in its source), so they are hidden."


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.scale = root.winfo_fpixels("1i") / 96  # 1.0 at 100% Windows scaling, 1.5 at 150%
        self._worker: threading.Thread | None = None
        self._outcome: tuple[dict | None, str | None] = (None, None)  # (snapshot, error) from the worker
        self._mail_outcome: tuple[dict | None, str | None] = (None, None)
        self._timer: str | None = None
        self._again = False  # refresh again when the current one finishes
        self._placed = False
        self._drag_offset = (0, 0)
        self._height: int | None = None  # set by dragging the bottom edge; None fits the contents
        self._tip: tk.Toplevel | None = None
        self._build()
        self.email.show(pipeline.load_mail())  # draw the last results right away...
        self.calendar.show(pipeline.load_snapshot())
        self.refresh()  # ...then fetch new ones

    def px(self, pixels: int) -> int:
        return round(pixels * self.scale)

    def _build(self) -> None:
        root = self.root
        root.title("Deadlines")
        root.overrideredirect(True)  # borderless, so ×, dragging and resizing are built in below
        root.attributes("-topmost", True)
        root.configure(bg=BG)
        root.bind("<Escape>", lambda _: root.destroy())
        set_scrollbar_style(root, self.px)

        header = tk.Frame(root, bg=BG)
        header.pack(fill="x", padx=PAD, pady=(10, 8))
        title = tk.Label(header, text="Deadlines", font=TITLE, bg=BG, fg=FG)
        title.pack(side="left")
        today = date.today()
        subtitle = tk.Label(header, text=f"{today:%A, %b} {today.day}", font=SMALL, bg=BG, fg=MUTED)
        subtitle.pack(side="left", padx=8, pady=(3, 0))
        for handle in (header, title, subtitle):
            handle.bind("<ButtonPress-1>", self._start_drag)
            handle.bind("<B1-Motion>", self._drag)
        icon_button(header, "×", root.destroy).pack(side="right")
        icon_button(header, "↻", self.refresh).pack(side="right", padx=(0, 8))
        self.collapse_button = icon_button(header, "▾", self._toggle_list)

        tabs = tk.Frame(root, bg=BG)
        tabs.pack(fill="x", padx=PAD, pady=(0, 8))

        # The grip and footer are packed before the pages, so a short window shrinks the list, not them.
        grip = tk.Frame(root, bg=BG, height=self.px(GRIP), cursor="sb_v_double_arrow")
        grip.pack(side="bottom", fill="x")
        tk.Frame(grip, bg=CARD_HOVER, height=self.px(2), width=self.px(40)).place(relx=0.5, rely=0.5, anchor="center")
        for handle in (grip, *grip.winfo_children()):
            handle.bind("<B1-Motion>", self._resize)
            handle.bind("<Double-Button-1>", self._auto_height)
        self.footer = tk.Frame(root, bg=BG)
        self.footer.pack(side="bottom", fill="x", padx=PAD, pady=(8, 0))

        self.calendar = CalendarPage(self)
        self.email = EmailPage(self)
        self.pages = {"Calendar": self.calendar, "Email": self.email}  # the links under the title
        self._statuses = {page: "" for page in self.pages.values()}
        self._tab_links: dict[CalendarPage | EmailPage, tk.Label] = {}
        for name, page in self.pages.items():
            link = tk.Label(tabs, text=name, bg=BG, cursor="hand2")
            link.pack(side="left", padx=(0, 14))
            link.bind("<Button-1>", lambda _, page=page: self.show_page(page))
            self._tab_links[page] = link
        root.bind_all("<MouseWheel>", lambda event: self.page.list.scroll(event))
        self.page = self.calendar
        self.show_page(self.calendar)

    # Pages

    def show_page(self, page) -> None:
        """Show one page. ▾ only hides the calendar list, so it is only shown there."""
        self.page.frame.pack_forget()
        self.page = page
        page.pack()
        if page is self.calendar:
            self.collapse_button.pack(side="right", padx=(0, 8))
        else:
            self.collapse_button.pack_forget()
        for other, link in self._tab_links.items():
            active = other is page
            link.configure(font=SMALL_BOLD + ("underline",) if active else SMALL_BOLD, fg=FG if active else MUTED)
        self._set_footer(self._statuses[page])
        self.size_list()
        self.fit()

    def _toggle_list(self) -> None:
        self.calendar.toggle_list()
        self.collapse_button.configure(text="▸" if self.calendar.collapsed else "▾")

    def set_status(self, page, text: str) -> None:
        """Keep a page's status line, and show it if that page is open."""
        self._statuses[page] = text
        if page is self.page:
            self._set_footer(text)

    def _set_footer(self, text: str) -> None:
        """One label per line. The "N rejected by the validator" part gets a hover tip."""
        for child in self.footer.winfo_children():
            child.destroy()
        for line in text.split("\n"):
            row = tk.Frame(self.footer, bg=BG)
            row.pack(fill="x")
            before, _, rejected = line.rpartition(" | ")
            if not rejected.endswith("rejected by the validator"):
                before, rejected = line, ""
            tk.Label(
                row, text=before, font=SMALL, bg=BG, fg=MUTED, anchor="w", justify="left",
                wraplength=self.px(WIDTH - 2 * PAD),
            ).pack(side="left")
            if rejected:
                tk.Label(row, text="|", font=SMALL, bg=BG, fg=MUTED).pack(side="left")
                hint = tk.Label(row, text=rejected, font=SMALL + ("underline",), bg=BG, fg=MUTED, cursor="question_arrow")
                hint.pack(side="left")
                hint.bind("<Enter>", lambda event: self._show_tip(event, REJECTED_TIP))
                hint.bind("<Leave>", lambda _: self._hide_tip())

    def _show_tip(self, event: tk.Event, text: str) -> None:
        self._hide_tip()
        self._tip = tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tk.Label(
            tip, text=text, font=SMALL, bg=CARD_HOVER, fg=FG, padx=6, pady=3, justify="left", wraplength=self.px(260)
        ).pack()
        tip.geometry(f"+{event.x_root + 12}+{event.y_root - self.px(40)}")

    def _hide_tip(self) -> None:
        if self._tip:
            self._tip.destroy()
            self._tip = None

    # Size and position

    def size_list(self) -> None:
        """Ask for room for the open page's whole list, but no more than keeps the window on the
        screen. After the bottom edge has been dragged, the window height wins and the list scrolls."""
        shown = self.page.list
        self.root.update_idletasks()
        others = self.root.winfo_reqheight() - shown.view.winfo_reqheight()
        room = self.root.winfo_screenheight() - others - self.px(80)  # leave space for the taskbar
        shown.view.configure(height=min(shown.box.winfo_reqheight(), max(self.px(120), room)))
        shown.view.yview_moveto(0)

    def fit(self) -> None:
        """Size the window to its contents. The first time, put it in the top-right corner."""
        self.root.update_idletasks()
        width = self.px(WIDTH)
        if self._placed:
            x, y = self.root.winfo_x(), self.root.winfo_y()
        else:
            x, y = self.root.winfo_screenwidth() - width - self.px(24), self.px(24)
            self._placed = True
        collapsed = self.page is self.calendar and self.calendar.collapsed
        height = self._height if self._height and not collapsed else self.root.winfo_reqheight()
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _resize(self, event: tk.Event) -> None:
        """Dragging the bottom edge sets the window height."""
        most = self.root.winfo_screenheight() - self.root.winfo_rooty()
        self._height = max(self.px(MIN_HEIGHT), min(event.y_root - self.root.winfo_rooty(), most))
        self.root.geometry(f"{self.px(WIDTH)}x{self._height}")

    def _auto_height(self, _=None) -> None:
        """Double-clicking the bottom edge goes back to fitting the contents."""
        self._height = None
        self.fit()

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag(self, event: tk.Event) -> None:
        dx, dy = self._drag_offset
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    # Refreshing

    def refresh(self, again_if_running: bool = False) -> None:
        """Run the pipeline on a worker thread. If one is already running, do nothing, or with
        again_if_running, start another as soon as it finishes."""
        if self._worker and self._worker.is_alive():
            self._again = self._again or again_if_running
            return
        if self._timer:
            self.root.after_cancel(self._timer)
        for page in self.pages.values():
            self.set_status(page, "Refreshing...")
        self._worker = threading.Thread(target=self._run_pipeline, daemon=True)
        self._worker.start()
        self.root.after(POLL_MS, self._finish_refresh)

    def _run_pipeline(self) -> None:
        """Runs on the worker thread: no Tkinter calls in here. Deadlines first, then email."""
        try:
            self._outcome = (pipeline.refresh(), None)
        except Exception as error:  # the window should survive anything a refresh throws
            self._outcome = (None, f"Refresh failed: {error}")
        try:
            self._mail_outcome = (pipeline.refresh_mail(), None)
        except Exception as error:
            self._mail_outcome = (None, f"Email refresh failed: {error}")

    def _finish_refresh(self) -> None:
        if self._worker.is_alive():
            self.root.after(POLL_MS, self._finish_refresh)
            return
        snapshot, error = self._outcome
        self.calendar.show(snapshot if snapshot is not None else pipeline.load_snapshot(), error)
        mail, mail_error = self._mail_outcome
        self.email.show(mail if mail is not None else pipeline.load_mail(), mail_error)
        if self._again:
            self._again = False
            self.refresh()
            return
        self._timer = self.root.after(config.REFRESH_MINUTES * 60_000, self.refresh)


def prefer_ipv4() -> None:
    """Try IPv4 addresses before IPv6. On this PC something blocks IPv6 for pythonw.exe only (see
    LOG.md), so every download waited for an IPv6 timeout first: 21 s and a failure for Gmail, 80 s
    for the feed. IPv6 addresses are still tried after the IPv4 ones."""
    original = socket.getaddrinfo

    def ipv4_first(*args, **kwargs):
        return sorted(original(*args, **kwargs), key=lambda info: info[0] != socket.AF_INET)

    socket.getaddrinfo = ipv4_first


def main() -> None:
    prefer_ipv4()
    try:  # sharp text on high-DPI screens (Windows only)
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
