"""Integration test for the fork command."""


def test_fork_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("fork xK9mZ2")
    assert "[stub]" in output()
