"""Integration test for the ping command."""


def test_ping_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("ping")
    assert "[stub]" in output()
