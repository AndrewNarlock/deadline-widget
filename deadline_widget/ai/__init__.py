"""ai - everything Claude does, and the code that checks it.

Each step sends untrusted text on stdin, gets a structured answer back, and passes it through
its own validator before anything can be shown. Nothing outside this folder talks to Claude.

    claude.py       the one place that runs `claude -p` (no tools, untrusted text on stdin only)
    extract.py      step 1: messy text -> to-do items, and validate_items()
    plan.py         step 2: today's plan and a section for every item, and validate_plan()
    mail_filter.py  step 3: the emails that fit the user's rule, and validate_matches()
"""
