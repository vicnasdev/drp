"""Integration test for the ask command."""


def test_ask_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks('ask "what is drp?"')
    assert "[stub]" in output()
