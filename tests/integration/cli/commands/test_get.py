"""Integration test for the get command."""


def test_get_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("get xK9mZ2")
    assert "[stub]" in output()
