"""Integration test for the cp command."""


def test_cp_runs(shell_output):
    """Smoke test: command dispatches without error."""
    shell, output = shell_output
    shell.onecmd_plus_hooks("cp ./test.txt .")
    assert "[stub]" in output()
