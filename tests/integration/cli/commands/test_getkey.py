"""Integration test for the getkey command."""


def test_getkey_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("getkey test.txt")
    assert "[stub]" in output()
