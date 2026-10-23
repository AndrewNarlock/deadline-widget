# Deadline Widget

A small always-on-top desktop window with two pages:

- **Calendar:** my upcoming due dates and readings, with a short plan for today. Due dates come from my Canvas
  calendar feed, readings from the public course site.
- **Email:** my Gmail inbox, filtered by a rule I type in plain words, like "only job postings".

TCSS 490, Artifact 3: AI Inside It.

## What the model does vs. what the code checks

Claude has three narrow jobs. Plain code does everything else, and checks every answer before it's shown.

| Piece | Who does it | Where |
|---|---|---|
| Fetch the Canvas feed, course pages and Gmail (read-only) | Code | `sources/` |
| **1. Extraction:** turn messy text (reading lists, event descriptions) into `{task, due, est_minutes}` items | **Claude** | `ai/extract.py` |
| **2. Planning:** pick up to 3 things to do today (minutes + a reason), and sort every item into Assignments, Readings or Exams & quizzes | **Claude** | `ai/plan.py` |
| **3. Email filtering:** pick the recent emails that fit my rule, each with a short "why" | **Claude** | `ai/mail_filter.py` |
| Validate each answer (below); skip text Claude has already read | Code | same files, `cache.py` |
| Merge, sort, save `data/cache.json` and `data/mail.json` | Code | `pipeline.py` |
| Display, with an **AI** badge on everything Claude produced | Code | `ui/` |

### The validators

Anything that fails is dropped and counted in the footer ("N rejected by the validator").
`python -m deadline_widget.pipeline` prints the reason for each one.

- **Extraction:** the task text must appear word for word in its source, which catches invented readings. `due`
  must be a real date inside the term, and must match any weekday or date the text names ("due Saturday").
  Minutes must be 1–1440, and the source must be one that was sent.
- **Planning:** at most 3 steps, only real items, each planned once (an event and its own detail count as one).
  Each step must be due within 14 days, at least 10 minutes, and all steps together must fit in `DAILY_MINUTES`
  (180). Reasons must be short and have no links. If a category is missing or invalid, code guesses one from the
  title.
- **Email:** Claude can only pick ids of emails it was sent, each once. Each "why" must be short and have no links.
  If Claude fails, the page shows Gmail's own "important" emails instead.

Both of the first two checks have caught real mistakes (see [LOG.md](LOG.md)).

**What the validators can't catch:**
- a wrong date that is still in the term and isn't named in the text
- a bad time estimate
- unhelpful advice in a plan reason
- an email that doesn't really fit the rule

Text written to look like a task, or an email written to look like a match, can get through. The damage is one
extra row: Claude has no tools, and every link comes from the feed, the page or Gmail, never from Claude.

## How Claude is called

`ai/claude.py` is the only code that starts Claude:

```
claude -p "<instruction>" --model haiku --system-prompt "..." --json-schema "{...}" --output-format json
       --tools "" --safe-mode --strict-mcp-config --no-session-persistence
```

- **Untrusted text** (pages, event descriptions, emails) goes in on **stdin** as JSON, never on the command line.
  Only my own email rule goes in the instruction. Emails are sent as sender, subject and Gmail's short preview only.
- **`--tools ""` and `--safe-mode`:** no tools, CLAUDE.md, hooks, plugins or MCP servers. Claude can only answer.
- **`--json-schema`:** the answer comes back already parsed.
- **Thinking off** (`MAX_THINKING_TOKENS=0`): a call went from about 110 s to about 8 s. A weekday table in the
  request and the date checks make up for it.
- **Caching:** answers are keyed by a hash of exactly what was sent, so a refresh makes a call per step only when
  something changed. That means new or changed text, a new day or item list for the plan, and new mail or a new
  rule for email. `--fresh` asks again anyway.

## Setup (Windows)

1. **Python with Tcl/Tk.** If `python -c "import tkinter"` fails: Settings > Apps > Python > Modify > tick
   **tcl/tk and IDLE**.
2. **Install:**
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   pip install -r requirements.txt
   copy .env.example .env
   ```
3. **Settings.** In `.env`, paste your Canvas calendar feed URL after `CANVAS_FEED_URL=`. Optionally, add course
   page URLs to `COURSE_PAGES`.
4. **Claude Code.** It must be installed and logged in, with `claude` on your PATH.
5. **Gmail** (for the Email page):
   1. In Google Cloud Console, make a project and enable the **Gmail API**.
   2. Under **Google Auth Platform**, choose **External**, and add yourself as a **test user**.
   3. Under **Clients**, create a **Desktop app** client and save its JSON as `data/gmail_credentials.json`.
   4. Run `python -m deadline_widget.sources.gmail` once to sign in. It lists your newest emails when it works.

   In Google's testing mode the login expires after 7 days. The Email page will say Gmail isn't connected; run
   step 4 again.

## Run

```powershell
python -m deadline_widget                    # open the widget (pythonw: without a console window)
python -m deadline_widget.pipeline           # refresh deadlines and print what the widget will show
python -m deadline_widget.pipeline --fresh   # same, but ask Claude again even about unchanged text
python -m unittest                           # run the tests (no network, no model)
```

**Desktop icon.** Make a shortcut to `<project folder>\.venv\Scripts\pythonw.exe -m deadline_widget`, with
"Start in" set to the project folder and the icon `assets\icon.ico`. To start it at login, copy the shortcut into
the folder `shell:startup` opens.

**Using it.** The widget refreshes when it opens and every 30 minutes.

- **Window:** drag the title to move it. Drag the bottom edge to resize, and double-click that edge to fit the
  contents again. ↻ refreshes now, and × or Esc closes.
- **Calendar:** checkboxes pick which sections and courses to show, and ▾ hides the list. Click a card to open it
  in Canvas.
- **Email:** type a rule in **Show me** and press Enter; × clears it. With no rule, it shows Gmail's important
  emails. Click an email to open it in Gmail.

## Files

```
deadline_widget/
  config.py  models.py  cache.py  pipeline.py     settings, records, JSON cache, runs everything
  sources/   feed.py  pages.py  gmail.py          plain code that fetches text (no model)
  ai/        claude.py                            the only code that runs claude -p
             extract.py  plan.py  mail_filter.py  Claude's three steps, each with its validator
  ui/        app.py                               the window: header, page links, footer, refresh
             calendar_page.py  email_page.py      one file per page
             parts.py                             shared colors, scrolling list, clickable cards
assets/      icon.ico
tests/       unit tests (Claude and the network are faked)
data/        results, Claude's cached answers, Gmail login (gitignored)
LOG.md       plans and what changed along the way
CLAUDE.md    standing instructions for Claude Code in this repo
```

## Security notes

- **Secrets:** `.env` (the feed URL) and `data/` (the Gmail login files) are gitignored. Error messages never
  include the feed URL.
- **Gmail access** is read-only (`gmail.readonly`), so nothing can be sent or deleted.
- **Untrusted text:** course pages, event descriptions and emails are treated as data, never instructions. Claude
  runs with no tools, and its output is validated in code before anything is shown.
