"""
tests/unit/test_base.py

Unit tests for cli.base — no network, no filesystem, no auth server.
"""
from __future__ import annotations

import sys
import pytest
from unittest.mock import MagicMock, patch
from io import StringIO

from cli.base.command import BaseCommand, AuthCommand, SpinnerCommand
from cli.base.errors import (
    DrpError, AuthError, NotFoundError, PermissionDeniedError,
    KeyTakenError, FileTooLargeError, NetworkError, parse_response,
)


# ---------------------------------------------------------------------------
# Helpers — minimal concrete commands for testing
# ---------------------------------------------------------------------------

class _EchoCommand(BaseCommand):
    """No-op command that returns a fixed exit code."""
    name = "echo"

    def __init__(self, exit_code=0, **kw):
        super().__init__(config={}, **kw)
        self._exit_code = exit_code

    def run(self, args):
        return self._exit_code


class _RaisingCommand(BaseCommand):
    """Command that raises a given exception on run()."""
    name = "raise"

    def __init__(self, exc, **kw):
        super().__init__(config={}, **kw)
        self._exc = exc

    def run(self, args):
        raise self._exc


class _AuthEchoCommand(AuthCommand):
    """Auth command that calls require_auth() then returns 0."""
    name = "auth-echo"

    def __init__(self, config, **kw):
        super().__init__(config=config, **kw)

    def run(self, args):
        self.require_auth()
        return 0


# ---------------------------------------------------------------------------
# MRO / inheritance
# ---------------------------------------------------------------------------

class TestMRO:
    def test_auth_command_is_base_command(self):
        assert issubclass(AuthCommand, BaseCommand)

    def test_spinner_command_is_base_command(self):
        assert issubclass(SpinnerCommand, BaseCommand)

    def test_command_inheriting_only_auth_command_is_valid(self):
        """The bug: class Foo(BaseCommand, AuthCommand) raised TypeError."""
        # If the MRO fix regressed, this class definition itself would raise.
        class GoodCommand(AuthCommand):
            name = "good"
            def run(self, args): return 0

        assert issubclass(GoodCommand, BaseCommand)
        assert issubclass(GoodCommand, AuthCommand)

    def test_mixed_spinner_auth_mro(self):
        """SpinnerCommand + AuthCommand should also resolve cleanly."""
        class Mixed(SpinnerCommand, AuthCommand):
            name = "mixed"
            def run(self, args): return 0

        assert issubclass(Mixed, BaseCommand)


# ---------------------------------------------------------------------------
# BaseCommand.execute() — exit-code & exception handling
# ---------------------------------------------------------------------------

class TestExecute:
    def test_returns_zero_on_success(self):
        assert _EchoCommand(exit_code=0).execute([]) == 0

    def test_returns_nonzero_exit_code(self):
        assert _EchoCommand(exit_code=3).execute([]) == 3

    def test_none_return_treated_as_zero(self):
        class NoneCommand(BaseCommand):
            name = "none"
            def __init__(self): super().__init__(config={})
            def run(self, args): return None   # explicit None

        assert NoneCommand().execute([]) == 0

    def test_drp_error_returns_exit_code(self, capsys):
        cmd = _RaisingCommand(DrpError("boom", code=42))
        assert cmd.execute([]) == 42
        assert "boom" in capsys.readouterr().err

    def test_keyboard_interrupt_returns_130(self):
        cmd = _RaisingCommand(KeyboardInterrupt())
        assert cmd.execute([]) == 130

    def test_unexpected_exception_returns_1(self, capsys):
        cmd = _RaisingCommand(RuntimeError("oops"))
        assert cmd.execute([]) == 1
        assert "unexpected error" in capsys.readouterr().err

    def test_unexpected_exception_captured_by_reporter(self):
        reporter = MagicMock()
        exc = RuntimeError("oops")
        cmd = _RaisingCommand(exc, reporter=reporter)
        cmd.execute([])
        reporter.capture.assert_called_once_with(exc)


# ---------------------------------------------------------------------------
# AuthCommand.require_auth()
# ---------------------------------------------------------------------------

class TestRequireAuth:
    _AUTHED_CONFIG = {"auth": {"token": "tok123", "username": "alice"}}
    _EMPTY_CONFIG  = {}
    _PARTIAL_CONFIG = {"auth": {"token": "tok123"}}  # missing username

    def test_sets_token_and_username_when_config_present(self):
        cmd = _AuthEchoCommand(config=self._AUTHED_CONFIG)
        cmd.require_auth()
        assert cmd.token    == "tok123"
        assert cmd.username == "alice"

    def test_auth_headers_contain_bearer_token(self):
        cmd = _AuthEchoCommand(config=self._AUTHED_CONFIG)
        cmd.require_auth()
        assert cmd.auth_headers == {"Authorization": "Bearer tok123"}

    def test_exits_when_no_auth_config(self, capsys):
        cmd = _AuthEchoCommand(config=self._EMPTY_CONFIG)
        with pytest.raises(SystemExit) as exc_info:
            cmd.require_auth()
        assert exc_info.value.code == 1

    def test_exits_when_username_missing(self, capsys):
        cmd = _AuthEchoCommand(config=self._PARTIAL_CONFIG)
        with pytest.raises(SystemExit):
            cmd.require_auth()

    def test_execute_exits_1_without_auth(self):
        cmd = _AuthEchoCommand(config=self._EMPTY_CONFIG)
        with pytest.raises(SystemExit) as exc_info:
            cmd.execute([])
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# parse_response()
# ---------------------------------------------------------------------------

def _mock_resp(status: int, body: dict):
    r = MagicMock()
    r.status_code = status
    r.ok = status < 400
    r.json.return_value = body
    return r


class TestParseResponse:
    def test_200_returns_data(self):
        assert parse_response(_mock_resp(200, {"key": "abc"})) == {"key": "abc"}

    def test_201_returns_data(self):
        assert parse_response(_mock_resp(201, {"key": "new"})) == {"key": "new"}

    def test_401_raises_auth_error(self):
        with pytest.raises(AuthError):
            parse_response(_mock_resp(401, {"error": "bad token"}))

    def test_403_raises_permission_denied(self):
        with pytest.raises(PermissionDeniedError):
            parse_response(_mock_resp(403, {"key": "xyz"}))

    def test_404_raises_not_found(self):
        with pytest.raises(NotFoundError):
            parse_response(_mock_resp(404, {"key": "xyz"}))

    def test_409_raises_key_taken(self):
        with pytest.raises(KeyTakenError):
            parse_response(_mock_resp(409, {"key": "taken"}))

    def test_413_raises_file_too_large(self):
        with pytest.raises(FileTooLargeError):
            parse_response(_mock_resp(413, {}))

    def test_429_raises_drp_error(self):
        with pytest.raises(DrpError, match="rate limited"):
            parse_response(_mock_resp(429, {}))

    def test_500_raises_drp_error(self):
        with pytest.raises(DrpError):
            parse_response(_mock_resp(500, {"error": "server exploded"}))

    def test_invalid_json_raises_network_error(self):
        r = MagicMock()
        r.status_code = 200
        r.ok = True
        r.json.side_effect = ValueError("not json")
        with pytest.raises(NetworkError):
            parse_response(r)