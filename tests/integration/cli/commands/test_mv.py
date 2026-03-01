"""Integration test for the mv command."""


def test_mv_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("mv old.txt new.txt")
    assert "[stub]" in output()
