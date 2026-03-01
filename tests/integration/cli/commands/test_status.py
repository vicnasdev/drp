"""Integration test for the status command."""


def test_status_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("status")
    assert "[stub]" in output()
