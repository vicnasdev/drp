"""Integration test for the token command."""


def test_token_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("token list")
    assert "[stub]" in output()
