"""Unit tests for cli.crash.reporter — fingerprinting & payload."""

from cli.crash.reporter import fingerprint, _build_payload, user_message


class TestFingerprint:
    """Fingerprint is deterministic and ignores absolute paths."""

    def test_same_exception_same_fingerprint(self):
        """Two identical exceptions produce the same fingerprint."""
        def _trigger():
            try:
                raise ValueError("boom")
            except ValueError as exc:
                return fingerprint(exc)

        assert _trigger() == _trigger()

    def test_different_exception_different_fingerprint(self):
        try:
            raise ValueError("boom")
        except ValueError as e1:
            fp1 = fingerprint(e1)

        try:
            raise TypeError("boom")
        except TypeError as e2:
            fp2 = fingerprint(e2)

        assert fp1 != fp2

    def test_fingerprint_is_hex_sha256(self):
        try:
            raise RuntimeError("test")
        except RuntimeError as exc:
            fp = fingerprint(exc)

        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)


class TestBuildPayload:
    """Payload contains required fields and is scrubbed."""

    def test_required_fields_present(self):
        try:
            raise RuntimeError("payload test")
        except RuntimeError as exc:
            payload = _build_payload("up", exc)

        assert payload["fingerprint"]
        assert payload["command"] == "up"
        assert payload["exc_type"] == "RuntimeError"
        assert "payload test" in payload["exc_message"]
        assert "RuntimeError" in payload["traceback"]
        assert payload["cli_version"]
        assert payload["python_version"]
        assert payload["platform"]

    def test_traceback_is_scrubbed(self):
        """Home directory should not appear in traceback."""
        import os

        home = os.path.expanduser("~")
        try:
            raise RuntimeError("scrub test")
        except RuntimeError as exc:
            payload = _build_payload("get", exc)

        assert home not in payload["traceback"]


class TestUserMessage:
    """The one-liner shown to the user."""

    def test_contains_command_and_ref(self):
        msg = user_message("up", "abcdef1234567890" * 4)
        assert "'up'" in msg
        assert "abcdef12" in msg
        assert "error report" in msg.lower()
