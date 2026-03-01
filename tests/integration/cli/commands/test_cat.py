"""Integration test for the cat command."""


def test_cat_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("cat xK9mZ2")
    assert "[stub]" in output()
