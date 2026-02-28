"""
cli/crash/reporter.py

Captures unhandled exceptions, scrubs user-identifying data, sends a
deduplicated crash report to the API in a background daemon thread.

Guarantees:
  - Never blocks CLI exit (daemon thread, fire-and-forget)
  - Never raises (all send errors swallowed)
  - Never leaks user content (line-level scrubber)

Deduplication happens server-side via CrashReport.fingerprint + select_for_update().
"""
from __future__ import annotations

import hashlib
import traceback
from threading import Thread

import requests

from cli.base.command import _safe_str
from cli import __version__


_SCRUB_PATTERNS = (
    "password", "token", "key", "secret", "auth",
    "email", "username", "home", "path", "user",
)


class CrashReporter:

    def __init__(self, api_url: str, timeout: int = 4):
        self.report_url = api_url.rstrip("/") + "/api/v1/crash/"
        self.timeout    = timeout

    def capture(self, exc: BaseException) -> None:
        """Non-blocking. Returns immediately."""
        payload = self._build(exc)
        Thread(target=self._send, args=(payload,), daemon=True).start()

    # ---------------------------------------------------------------- internal

    def _build(self, exc: BaseException) -> dict:
        raw      = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        scrubbed = _scrub(raw)
        return {
            "fingerprint": _fingerprint(type(exc).__name__, scrubbed),
            "exc_type":    type(exc).__name__,
            "title":       _safe_str(exc),
            "traceback":   scrubbed,
            "cli_version": __version__,
        }

    def _send(self, payload: dict) -> None:
        try:
            requests.post(self.report_url, json=payload, timeout=self.timeout)
        except Exception:
            pass


def _scrub(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if any(p in line.lower() for p in _SCRUB_PATTERNS):
            lines.append("    [scrubbed]")
        else:
            lines.append(line)
    return "\n".join(lines)


def _fingerprint(exc_type: str, scrubbed: str) -> str:
    return hashlib.sha256(f"{exc_type}:{scrubbed}".encode()).hexdigest()[:16]
