"""Integration test for the logout command."""


def test_logout_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("logout")
    assert "[stub]" in output()
