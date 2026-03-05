"""
CLI crash reporter.

Catches unhandled exceptions, builds a scrubbed payload, and POSTs it to
``/api/v1/crash/`` in a background thread so the user is never blocked.

Usage — top-level handler::

    from cli.crash.reporter import report
    try:
        run_command(...)
    except Exception as exc:
        report("up", exc)
"""

from __future__ import annotations

import hashlib
import platform
import sys
import threading
import traceback
from typing import Any

from cli import __version__
from cli.crash.scrub import scrub


# ── Fingerprinting ────────────────────────────────────────────────────────────

def fingerprint(exc: BaseException) -> str:
    """
    SHA-256 hash of exception type + *simplified* traceback.

    "Simplified" means each frame is ``filename:lineno:funcname`` with the
    home directory stripped — so two users hitting the same bug produce the
    same fingerprint even though their absolute paths differ.
    """
    tb = traceback.extract_tb(exc.__traceback__)
    # Use only the relative frame info (file basename, line, func).
    frames = "|".join(
        f"{f.filename.rsplit('/', 1)[-1]}:{f.lineno}:{f.name}" for f in tb
    )
    raw = f"{type(exc).__qualname__}|{frames}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ── Payload ───────────────────────────────────────────────────────────────────

def _build_payload(command: str, exc: BaseException) -> dict[str, Any]:
    """Build the JSON body sent to ``/api/v1/crash/``."""
    tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return {
        "fingerprint": fingerprint(exc),
        "command": command,
        "exc_type": type(exc).__qualname__,
        "exc_message": scrub(str(exc)),
        "traceback": scrub(tb_text),
        "cli_version": __version__,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }


# ── Sending ───────────────────────────────────────────────────────────────────


def _post(payload: dict[str, Any], url: str) -> None:
    """Fire-and-forget POST. Failures are silently swallowed."""
    try:
        import urllib.request
        import json

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)  # noqa: S310
    except Exception:
        # Never let reporting crash the CLI.
        pass


def report(
    command: str,
    exc: BaseException,
    *,
    url: str,
    _sync: bool = False,
) -> str:
    """
    Report *exc* to the drp server.

    Returns the fingerprint so callers can reference it if needed.
    ``_sync=True`` is only used by tests to avoid thread races.
    """
    payload = _build_payload(command, exc)
    fp = payload["fingerprint"]

    if _sync:
        _post(payload, url)
    else:
        t = threading.Thread(target=_post, args=(payload, url), daemon=True)
        t.start()

    return fp


# ── User message ──────────────────────────────────────────────────────────────

def user_message(command: str, fp: str) -> str:
    """One-line message shown to the user after a crash."""
    return (
        f"drp: '{command}' crashed (ref {fp[:8]}). "
        "An error report has been sent."
    )
