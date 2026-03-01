"""Integration test for the cd command."""


def test_cd_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("cd /")
    assert "[stub]" in output()
