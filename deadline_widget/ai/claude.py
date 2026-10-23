"""claude.py - the one place that starts `claude -p`. extract.py and plan.py both call run().

Every call is locked down the same way:
    - untrusted text travels only on stdin, inside a JSON document, never on the command line
    - --tools "" and --safe-mode: no tools, no CLAUDE.md, hooks, plugins or MCP servers
    - --json-schema: the answer comes back already parsed, in the envelope's structured_output
    - thinking is off (MAX_THINKING_TOKENS=0), which took a call from ~110 s to ~8 s
The caller still validates everything in the answer; this module only checks its shape.
"""

import json
import os
import subprocess
import tempfile

from .. import config

TIMEOUT_SECONDS = 240


class ClaudeError(RuntimeError):
    """claude -p failed or returned something unreadable."""


def run(instruction: str, system_prompt: str, schema: dict, document: dict) -> dict:
    """Send `document` to Claude on stdin. Returns the structured answer, not yet validated."""
    command = [
        "claude", "-p", instruction,
        "--model", config.CLAUDE_MODEL,
        "--system-prompt", system_prompt,
        "--json-schema", json.dumps(schema),
        "--output-format", "json",
        "--tools", "",  # no tools: Claude can only answer, never act
        "--safe-mode",  # no CLAUDE.md, hooks, plugins or MCP servers...
        "--strict-mcp-config",  # ...and no MCP servers even if safe mode changes
        "--no-session-persistence",  # don't save a session for every refresh
    ]
    try:
        result = subprocess.run(
            command,
            input=json.dumps(document, ensure_ascii=False),  # untrusted text goes on stdin only
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            cwd=tempfile.gettempdir(),  # run away from this repo's files
            env={**os.environ, "MAX_THINKING_TOKENS": "0"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),  # no console flash under pythonw
        )
    except FileNotFoundError:
        raise ClaudeError("the claude command was not found. Is Claude Code installed?") from None
    except subprocess.TimeoutExpired:
        raise ClaudeError(f"claude -p took longer than {TIMEOUT_SECONDS} seconds") from None
    if result.returncode != 0:
        raise ClaudeError(f"claude -p exited with code {result.returncode}: {_tail(result.stderr or result.stdout)}")
    return parse_response(result.stdout)


def parse_response(stdout: str) -> dict:
    """The structured answer from `claude -p --output-format json --json-schema ...` output."""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        raise ClaudeError("claude -p did not return JSON") from None
    if not isinstance(envelope, dict):
        raise ClaudeError("claude -p returned unexpected JSON")
    if envelope.get("is_error"):
        reason = envelope.get("result") or envelope.get("subtype") or "unknown error"
        raise ClaudeError(f"Claude reported an error: {_tail(str(reason))}")
    answer = envelope.get("structured_output")
    if not isinstance(answer, dict):
        raise ClaudeError("Claude's answer did not match the output schema")
    return answer


def _tail(text: str) -> str:
    return " ".join(text.split())[-300:]
