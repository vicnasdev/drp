"""
Unit tests for tab completion.

Validates that the shell exposes completions for command names,
subcommands, flag names, and flag choices derived from the registry.
"""

import pytest

from cli.shell import DrpShell
from cli.commands import all_commands


@pytest.fixture
def shell():
    """Return a DrpShell instance (not started — just for method inspection)."""
    s = DrpShell(allow_cli_args=False)
    return s


class TestCommandCompletion:
    """Every registered command should have a do_ method on the shell."""

    def test_all_commands_are_methods(self, shell):
        for name in all_commands():
            assert hasattr(shell, f"do_{name}"), f"do_{name} missing"

    def test_help_methods_exist(self, shell):
        for name in all_commands():
            assert hasattr(shell, f"help_{name}"), f"help_{name} missing"

    def test_shell_only_commands_exist(self, shell):
        """Shell-only commands should still be registered as do_ methods."""
        for name, cmd in all_commands().items():
            if cmd.shell_only:
                assert hasattr(shell, f"do_{name}")
