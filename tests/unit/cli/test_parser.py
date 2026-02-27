"""
Tests for the CLI argument parser — build_parser, subcommand registration,
argument validation.
"""

import pytest
from cli.drp import build_parser, COMMANDS, COMMAND_GROUPS, EXAMPLES, _build_epilog


# ── Parser structure ──────────────────────────────────────────────────────────

class TestParserStructure:
    @pytest.fixture(autouse=True)
    def _parser(self):
        self.parser = build_parser()

    def test_prog_is_drp(self):
        assert self.parser.prog == 'drp'

    def test_all_commands_registered(self):
        names = {name for name, _, _ in COMMANDS}
        sub_actions = [a for a in self.parser._subparsers._actions
                       if hasattr(a, '_name_parser_map')]
        registered = set(sub_actions[0]._name_parser_map.keys())
        assert names == registered

    def test_has_version_flag(self):
        with pytest.raises(SystemExit) as exc_info:
            self.parser.parse_args(['--version'])
        assert exc_info.value.code == 0

    def test_has_help_flag(self):
        # Our custom help action calls parser.exit, so SystemExit
        with pytest.raises(SystemExit):
            self.parser.parse_args(['--help'])

    def test_no_command_returns_none(self):
        args = self.parser.parse_args([])
        assert args.command is None


# ── Subcommand arguments ─────────────────────────────────────────────────────

class TestUpSubcommand:
    @pytest.fixture(autouse=True)
    def _parser(self):
        self.parser = build_parser()

    def test_up_target_optional(self):
        args = self.parser.parse_args(['up'])
        assert args.target is None

    def test_up_target_positional(self):
        args = self.parser.parse_args(['up', 'hello.txt'])
        assert args.target == 'hello.txt'

    def test_up_burn_flag(self):
        args = self.parser.parse_args(['up', '--burn'])
        assert args.burn is True

    def test_up_key_flag(self):
        args = self.parser.parse_args(['up', '-k', 'mykey'])
        assert args.key == 'mykey'

    def test_up_expires_flag(self):
        args = self.parser.parse_args(['up', '--expires', '30d'])
        assert args.expires == '30d'

    def test_up_password_prompt_mode(self):
        args = self.parser.parse_args(['up', '--password'])
        assert args.password == '__prompt__'

    def test_up_password_explicit(self):
        args = self.parser.parse_args(['up', '--password', 'secret'])
        assert args.password == 'secret'

    def test_up_remote_flag(self):
        args = self.parser.parse_args(['up', '--remote'])
        assert args.remote is True

    def test_up_public_flag(self):
        args = self.parser.parse_args(['up', '--public'])
        assert args.public is True


class TestGetSubcommand:
    @pytest.fixture(autouse=True)
    def _parser(self):
        self.parser = build_parser()

    def test_get_key_required(self):
        with pytest.raises(SystemExit):
            self.parser.parse_args(['get'])

    def test_get_key_positional(self):
        args = self.parser.parse_args(['get', 'mykey'])
        assert args.key == 'mykey'

    def test_get_output_flag(self):
        args = self.parser.parse_args(['get', 'k', '-o', 'out.txt'])
        assert args.output == 'out.txt'

    def test_get_url_flag(self):
        args = self.parser.parse_args(['get', 'k', '--url'])
        assert args.url is True

    def test_get_parse_flag(self):
        args = self.parser.parse_args(['get', 'k', '--parse'])
        assert args.parse is True

    def test_get_field_flag(self):
        args = self.parser.parse_args(['get', 'k', '--field', 'data.name'])
        assert args.field == 'data.name'

    def test_get_password_flag(self):
        args = self.parser.parse_args(['get', 'k', '-p', 'pw'])
        assert args.password == 'pw'


class TestTokenSubcommand:
    @pytest.fixture(autouse=True)
    def _parser(self):
        self.parser = build_parser()

    def test_token_create(self):
        args = self.parser.parse_args(['token', 'create', '--expires', '90d'])
        assert args.token_action == 'create'
        assert args.expires == '90d'

    def test_token_list(self):
        args = self.parser.parse_args(['token', 'list'])
        assert args.token_action == 'list'

    def test_token_revoke(self):
        args = self.parser.parse_args(['token', 'revoke', '42'])
        assert args.token_action == 'revoke'
        assert args.token_id == 42


class TestAskSubcommand:
    @pytest.fixture(autouse=True)
    def _parser(self):
        self.parser = build_parser()

    def test_ask_question_optional(self):
        args = self.parser.parse_args(['ask'])
        assert args.question is None

    def test_ask_history_flag(self):
        args = self.parser.parse_args(['ask', '--history'])
        assert args.history is True

    def test_ask_clear_flag(self):
        args = self.parser.parse_args(['ask', '--clear'])
        assert args.clear is True


# ── COMMANDS / COMMAND_GROUPS / EXAMPLES consistency ─────────────────────────

class TestMetadataConsistency:
    def test_all_group_commands_exist(self):
        cmd_names = {name for name, _, _ in COMMANDS}
        for _, names in COMMAND_GROUPS:
            for name in names:
                assert name in cmd_names, f'{name} in COMMAND_GROUPS but not COMMANDS'

    def test_all_commands_in_a_group(self):
        grouped = set()
        for _, names in COMMAND_GROUPS:
            grouped.update(names)
        cmd_names = {name for name, _, _ in COMMANDS}
        assert cmd_names == grouped

    def test_epilog_not_empty(self):
        assert len(_build_epilog()) > 100

    def test_examples_list_not_empty(self):
        assert len(EXAMPLES) > 10

    def test_each_command_has_non_empty_help(self):
        for name, _, help_str in COMMANDS:
            assert len(help_str) > 5, f'{name} has no help text'
