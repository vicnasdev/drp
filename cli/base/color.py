"""
cli/base/color.py

Central ANSI color palette. Every escape code in the codebase comes from here.
Toggle off globally with Color.disable() or set NO_COLOR / TERM=dumb env vars.
"""
from __future__ import annotations
import os
import sys


class Color:
    ENABLED: bool = (
        sys.stdout.isatty()
        and os.environ.get("NO_COLOR") is None
        and os.environ.get("TERM") != "dumb"
    )

    # Raw codes
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    GREEN  = "\033[32m"
    YELLOW = "\033[33m"
    RED    = "\033[31m"
    CYAN   = "\033[36m"
    BLUE   = "\033[34m"
    GRAY   = "\033[90m"

    @classmethod
    def wrap(cls, text: str, *codes: str) -> str:
        if not cls.ENABLED:
            return text
        return "".join(codes) + text + cls.RESET

    @classmethod
    def disable(cls) -> None:
        cls.ENABLED = False

    # Semantic shorthands
    @classmethod
    def success(cls, t: str) -> str: return cls.wrap(t, cls.GREEN, cls.BOLD)

    @classmethod
    def error(cls, t: str) -> str:   return cls.wrap(t, cls.RED, cls.BOLD)

    @classmethod
    def warn(cls, t: str) -> str:    return cls.wrap(t, cls.YELLOW)

    @classmethod
    def info(cls, t: str) -> str:    return cls.wrap(t, cls.CYAN)

    @classmethod
    def dim(cls, t: str) -> str:     return cls.wrap(t, cls.DIM)

    @classmethod
    def key(cls, t: str) -> str:     return cls.wrap(t, cls.BLUE, cls.BOLD)

    @classmethod
    def url(cls, t: str) -> str:     return cls.wrap(t, cls.CYAN)

    @classmethod
    def owner(cls, t: str) -> str:   return cls.wrap(t, cls.GRAY)
