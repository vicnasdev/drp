"""
Scrub user-identifying data from traceback text before it leaves the machine.

Replaces:
    - Home directory paths  →  ~
    - Environment variables that look like secrets  →  ***
    - Email addresses  →  <email>
    - Bearer / token strings  →  <token>
"""

from __future__ import annotations

import os
import re

_HOME = os.path.expanduser("~")

# Patterns compiled once
_SECRET_ENV_RE = re.compile(
    r"(TOKEN|SECRET|KEY|PASSWORD|CREDENTIAL|AUTH)[=:]\s*\S+",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_BEARER_RE = re.compile(r"(Bearer\s+)\S+", re.IGNORECASE)
_HEX_TOKEN_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")


def scrub(text: str) -> str:
    """Remove user-identifying information from *text*."""
    # Order matters: home path first (longest match), then patterns.
    out = text.replace(_HOME, "~")
    out = _SECRET_ENV_RE.sub(r"\1=***", out)
    out = _BEARER_RE.sub(r"\1<token>", out)
    out = _HEX_TOKEN_RE.sub("<token>", out)
    out = _EMAIL_RE.sub("<email>", out)
    return out
