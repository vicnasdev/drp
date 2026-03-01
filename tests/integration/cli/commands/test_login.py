"""Integration test for the login command."""


def test_login_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("login")
    assert "[stub]" in output()
