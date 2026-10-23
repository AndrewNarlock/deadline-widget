"""cache.py - plain code. Small JSON files on disk, and the hash cache for Claude's answers."""

import hashlib
import json
import os
from pathlib import Path


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data) -> None:
    """Write to a temp file and swap it in, so a reader never sees a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def text_key(*parts: object) -> str:
    """A stable hash of everything that shapes Claude's answer."""
    return hashlib.sha256("\x1f".join(map(str, parts)).encode("utf-8")).hexdigest()


class AnswerCache:
    """Claude's raw answers keyed by text_key(), so the same question is never asked twice.

    Answers are stored unvalidated and validated again on every run. Entries that are not
    looked up or added during a run are dropped on save, so the file only holds current answers.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        entries = read_json(path, {})
        self._entries: dict[str, object] = entries if isinstance(entries, dict) else {}
        self._used: dict[str, object] = {}

    def get(self, key: str) -> object | None:
        if key not in self._entries:
            return None
        self._used[key] = self._entries[key]
        return self._entries[key]

    def put(self, key: str, answer: object) -> None:
        self._entries[key] = self._used[key] = answer

    def save(self) -> None:
        write_json(self.path, self._used)
