"""Integration test for the setup command."""


def test_setup_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("setup")
    assert "[stub]" in output()
