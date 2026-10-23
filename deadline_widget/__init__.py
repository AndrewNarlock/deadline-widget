"""Deadline Widget: Canvas due dates, course readings and a filtered Gmail inbox in one small desktop window.

The folders follow the split between plain code and the model:
    sources/   fetch the raw text: Canvas feed, course pages, Gmail (plain code)
    ai/        Claude's three steps, each with the validator that checks it
    ui/        the Tkinter window, which only displays what the pipeline saved

And at the top level:
    config.py    settings and file paths (reads .env)
    models.py    the Item and Email records every step passes along
    cache.py     JSON files and the hash cache for Claude's answers
    pipeline.py  runs sources -> ai -> data/cache.json and data/mail.json
"""
