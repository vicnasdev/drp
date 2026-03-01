"""Integration test for the setkey command."""


def test_setkey_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("setkey test.txt newkey")
    assert "[stub]" in output()
