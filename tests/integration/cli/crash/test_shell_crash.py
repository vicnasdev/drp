"""Integration test: shell crash handler catches exceptions and reports them."""

import io
from unittest.mock import patch

from cli.shell import DrpShell


def test_command_exception_triggers_crash_report():
    """When a do_* method raises, the shell catches it and calls report()."""
    shell = DrpShell(allow_cli_args=False)
    shell.stdout = io.StringIO()

    # Make do_ping raise
    def exploding_ping(self, statement):
        raise RuntimeError("kaboom")

    with patch.object(type(shell), "do_ping", exploding_ping):
        with patch("cli.crash.reporter.report", return_value="ab" * 32) as mock_report:
            with patch.object(shell, "perror"):  # suppress error output
                shell.onecmd_plus_hooks("ping")

    mock_report.assert_called_once()
    args = mock_report.call_args
    assert args[0][0] == "ping"  # command name
    assert isinstance(args[0][1], RuntimeError)  # exception
