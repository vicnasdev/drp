"""Shared fixtures for CLI command integration tests."""

import io

import pytest

from cli.shell import DrpShell


@pytest.fixture
def shell():
    """DrpShell with stdout captured to a StringIO buffer."""
    out = io.StringIO()
    s = DrpShell(allow_cli_args=False)
    s.stdout = out
    return s


@pytest.fixture
def shell_output(shell):
    """Return (shell, get_output_fn) where get_output_fn() returns captured text."""
    def get_output():
        shell.stdout.seek(0)
        return shell.stdout.read()
    return shell, get_output
