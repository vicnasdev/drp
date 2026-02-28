"""
cli/base/command.py

Base class hierarchy for all drp CLI commands.

    BaseCommand          — output, error handling, crash reporting
        SpinnerCommand   — adds .spin() context manager
        AuthCommand      — adds .require_auth() + .auth_headers

Mix freely:
    class UpCommand(SpinnerCommand, AuthCommand): ...
"""
from __future__ import annotations

import os
import sys
import traceback
from abc import ABC, abstractmethod
from contextlib import contextmanager
from itertools import cycle
from threading import Event, Thread
from typing import NoReturn

from .color import Color
from .errors import DrpError
from .output import OutputMixin


class BaseCommand(OutputMixin, ABC):
    name:        str = ""
    description: str = ""

    def __init__(
        self,
        config: dict,
        reporter: "CrashReporter | None" = None,  # noqa: F821
        in_shell: bool = False,
    ):
        self.config   = config
        self.reporter = reporter
        self.in_shell = in_shell

    # ---------------------------------------------------------------- dispatch

    def execute(self, args: list[str]) -> int:
        """Top-level entry point. Returns exit code."""
        try:
            return self.run(args) or 0
        except DrpError as e:
            self.err(str(e))
            return e.exit_code
        except KeyboardInterrupt:
            self.out("")
            return 130
        except Exception as e:
            self._handle_unexpected(e)
            return 1

    @abstractmethod
    def run(self, args: list[str]) -> int | None:
        """Command logic. Return exit code or None (= 0)."""

    # ---------------------------------------------------------------- exit

    def bail(self, message: str, code: int = 1) -> NoReturn:
        self.err(message)
        sys.exit(code)

    def abort(self, message: str = "cancelled") -> NoReturn:
        self.out(Color.warn(message))
        sys.exit(1)

    # ---------------------------------------------------------------- internal

    def _handle_unexpected(self, exc: Exception) -> None:
        self.err(f"unexpected error: {_safe_str(exc)}")
        self.dim("this has been reported automatically")
        if os.environ.get("DRP_DEBUG"):
            traceback.print_exc(file=sys.stderr)
        if self.reporter:
            self.reporter.capture(exc)

    @property
    def server_url(self) -> str:
        return self.config.get("server_url", "https://drp.fyi").rstrip("/")


# ---------------------------------------------------------------------------
# SpinnerCommand
# ---------------------------------------------------------------------------

_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


class SpinnerCommand(BaseCommand, ABC):
    """Adds .spin() context manager for long-running / network operations."""

    @contextmanager
    def spin(self, label: str):
        if not Color.ENABLED or not sys.stderr.isatty():
            print(Color.dim(f"{label}…"), file=sys.stderr)
            yield
            return

        stop = Event()
        t    = Thread(target=_spin_loop, args=(label, stop), daemon=True)
        t.start()
        try:
            yield
        finally:
            stop.set()
            t.join()
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()


def _spin_loop(label: str, stop: Event) -> None:
    for frame in cycle(_FRAMES):
        sys.stderr.write(f"\r{Color.wrap(frame, Color.CYAN)}  {Color.dim(label)}")
        sys.stderr.flush()
        if stop.wait(0.08):
            break


# ---------------------------------------------------------------------------
# AuthCommand
# ---------------------------------------------------------------------------

class AuthCommand(BaseCommand, ABC):
    """Adds require_auth() + auth_headers. Mix with SpinnerCommand freely."""

    token:    str
    username: str

    def require_auth(self) -> None:
        auth     = self.config.get("auth", {})
        token    = auth.get("token", "")
        username = auth.get("username", "")
        if not token or not username:
            self.err("you are not logged in")
            self.dim("  run: drp login")
            sys.exit(1)
        self.token    = token
        self.username = username

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_str(exc: BaseException) -> str:
    try:
        return type(exc).__name__ + (f": {exc.args[0]}" if exc.args else "")
    except Exception:
        return type(exc).__name__
