"""Integration test for the mkdir command."""


def test_mkdir_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("mkdir testfolder")
    assert "[stub]" in output()
