"""
test_lock.py — password protection: lock, unlock, get with password.

Runs real CLI commands against the live server.
"""

import pytest

from tests.integration.test_lifecycle import drp, unique_key


class TestLock:

    def test_lock_unlock(self):
        """drp lock <key> --password <pw> then drp get <key> --password <pw>."""
        k = unique_key("lock")
        pw = "test-pass-123"
        drp("up", "secret stuff", "-k", k)

        # Lock it
        rc, out, err = drp("lock", k, "--password", pw)
        combined = (out + err).lower()
        if rc != 0 and ("plan" in combined or "paid" in combined):
            pytest.skip("Password protection requires paid plan")
        if rc != 0 and ("protected" in combined or "locked" in combined):
            pytest.skip("Drop is locked (24h protection)")
        assert rc == 0
        assert "password-protected" in out.lower() or "✓" in out

        # Get without password fails
        rc, _, err = drp("get", k)
        assert rc != 0 or "password" in (err + "").lower()

        # Get with password succeeds
        rc, out, _ = drp("get", k, "--password", pw)
        assert rc == 0
        assert "secret stuff" in out

        # Unlock
        rc, out, _ = drp("lock", k, "--remove")
        assert rc == 0
        assert "removed" in out.lower() or "✓" in out

        # Get without password works again
        rc, out, _ = drp("get", k)
        assert rc == 0
        assert "secret stuff" in out

        drp("rm", k)
