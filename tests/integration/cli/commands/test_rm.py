"""Integration test for the rm command."""


def test_rm_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("rm xK9mZ2")
    assert "[stub]" in output()
