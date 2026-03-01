"""Integration test for the edit command."""


def test_edit_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("edit test.txt")
    assert "[stub]" in output()
