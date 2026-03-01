"""
Unit tests for the command registry and all command specs.

Verifies every command from ARCH.md is registered with correct
attributes, and that the registry API (all_commands, get) works.
"""

import pytest

from cli.commands import Arg, Command, all_commands, get_command


# ── All commands from ARCH.md ────────────────────────────────────────────────

EXPECTED_COMMANDS = [
    "up", "get", "cat", "cp", "mv", "rm", "ls", "cd", "mkdir",
    "edit", "fork", "share", "ask", "ping", "status", "login",
    "logout", "token", "getkey", "setkey", "setup",
]

SHELL_ONLY = {"cp", "mv", "cd", "mkdir", "edit", "share", "getkey", "setkey"}


class TestRegistry:

    def test_all_commands_present(self):
        cmds = all_commands()
        for name in EXPECTED_COMMANDS:
            assert name in cmds, f"command '{name}' missing from registry"

    def test_no_extra_commands(self):
        cmds = all_commands()
        for name in cmds:
            assert name in EXPECTED_COMMANDS, f"unexpected command '{name}' in registry"

    def test_get_returns_command(self):
        cmd = get_command("up")
        assert isinstance(cmd, Command)
        assert cmd.name == "up"

    def test_get_unknown_returns_none(self):
        assert get_command("nonexistent") is None

    def test_command_count(self):
        assert len(all_commands()) == len(EXPECTED_COMMANDS)


class TestCommandSpecs:
    """Verify structural invariants on every command."""

    @pytest.fixture(params=EXPECTED_COMMANDS)
    def cmd(self, request):
        return get_command(request.param)

    def test_has_name(self, cmd):
        assert cmd.name

    def test_has_description(self, cmd):
        assert cmd.description
        assert len(cmd.description) > 5

    def test_args_are_tuples(self, cmd):
        assert isinstance(cmd.args, tuple)
        for arg in cmd.args:
            assert isinstance(arg, Arg)

    def test_arg_names_unique(self, cmd):
        names = [a.name for a in cmd.args]
        assert len(names) == len(set(names)), f"duplicate arg names in {cmd.name}"

    def test_shell_only_flag(self, cmd):
        if cmd.name in SHELL_ONLY:
            assert cmd.shell_only, f"{cmd.name} should be shell_only"
        else:
            assert not cmd.shell_only, f"{cmd.name} should not be shell_only"

    def test_required_args_come_first(self, cmd):
        """Required positional args should precede optional ones."""
        seen_optional = False
        for arg in cmd.args:
            if arg.name.startswith("-"):
                continue  # flags can be anywhere
            if not arg.required:
                seen_optional = True
            elif seen_optional:
                pytest.fail(f"{cmd.name}: required arg '{arg.name}' after optional")

    def test_choices_are_tuples(self, cmd):
        for arg in cmd.args:
            if arg.choices is not None:
                assert isinstance(arg.choices, tuple)


class TestSpecificCommands:
    """Spot-check key commands for correct arg definitions."""

    def test_up_has_target(self):
        cmd = get_command("up")
        target = next(a for a in cmd.args if a.name == "target")
        assert target.required
        assert target.type == "path"

    def test_up_has_key_flag(self):
        cmd = get_command("up")
        key = next(a for a in cmd.args if a.name == "-k/--key")
        assert not key.required

    def test_up_tag_repeatable(self):
        cmd = get_command("up")
        tag = next(a for a in cmd.args if a.name == "--tag")
        assert tag.repeatable

    def test_get_has_decrypt(self):
        cmd = get_command("get")
        decrypt = next(a for a in cmd.args if a.name == "--decrypt")
        assert decrypt.type == "passphrase"

    def test_ls_sort_choices(self):
        cmd = get_command("ls")
        sort = next(a for a in cmd.args if a.name == "--sort")
        assert sort.choices == ("name", "size", "exp")

    def test_cat_has_parse_and_field(self):
        cmd = get_command("cat")
        names = [a.name for a in cmd.args]
        assert "--parse" in names
        assert "--field" in names

    def test_token_action_choices(self):
        cmd = get_command("token")
        action = next(a for a in cmd.args if a.name == "action")
        assert action.choices == ("create", "list", "revoke")
        assert action.required
