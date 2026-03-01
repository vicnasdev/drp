"""Integration test for the ls command."""


def test_ls_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("ls")
    assert "[stub]" in output()
