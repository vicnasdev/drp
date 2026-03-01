"""Integration test for the share command."""


def test_share_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("share")
    assert "[stub]" in output()
