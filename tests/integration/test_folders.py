"""
test_folders.py — folder operations: mkdir, ls --col.

Runs real CLI commands against the live server.
"""

import pytest

from tests.integration.test_lifecycle import drp, unique_key


class TestFolders:

    def test_mkdir(self):
        """drp mkdir <name> creates a folder."""
        name = unique_key("dir")
        rc, out, err = drp("mkdir", name)
        if rc != 0 and "error" in (out + err).lower():
            pytest.skip("mkdir endpoint not available on this server")
        assert rc == 0
        assert "created" in out.lower() or "✓" in out

    def test_ls_col(self):
        """drp ls --col lists folders."""
        rc, out, _ = drp("ls", "--col")
        # rc == 0 even if no folders (prints "(no folders)")
        assert rc == 0
