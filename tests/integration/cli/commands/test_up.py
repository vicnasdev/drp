"""Integration test for the up command."""


def test_up_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("up ./test.txt")
    assert "[stub]" in output()
