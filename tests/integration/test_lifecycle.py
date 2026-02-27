"""
test_lifecycle.py — full drop lifecycle: up → get → status → mv → cp → renew → rm.

Runs real CLI commands against the live server, exactly as a user would.
"""

import json
import os
import subprocess
import uuid

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ENV = {
    **os.environ,
    "DRP_TEST_MODE": "1",
    "NO_COLOR": "1",
    "TERM": "dumb",
}


def drp(*args, stdin=None, timeout=30):
    cmd = ["python", "-m", "cli.drp"] + list(args)
    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=timeout, cwd=ROOT, env=ENV,
        input=stdin,
    )
    return proc.returncode, proc.stdout, proc.stderr


def unique_key(prefix="t"):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ── Upload + Get ──────────────────────────────────────────────────────────────

class TestUpGet:

    def test_text_roundtrip(self, text_drop):
        """drp up <text> then drp get <key> returns the same text."""
        key, content = text_drop
        rc, out, _ = drp("get", key)
        assert rc == 0
        assert content in out

    def test_stdin_upload(self, key):
        """echo ... | drp up -k <key> works."""
        rc, out, _ = drp("up", "-k", key, stdin="piped from stdin")
        assert rc == 0
        assert key in out  # URL printed

        rc, out, _ = drp("get", key)
        assert rc == 0
        assert "piped from stdin" in out

    def test_file_roundtrip(self, file_drop, tmp_path):
        """drp up <file> then drp get <key> -o <path> saves the file."""
        key, _ = file_drop
        dest = tmp_path / "downloaded.txt"
        rc, out, _ = drp("get", key, "-o", str(dest))
        assert rc == 0
        assert dest.exists()
        assert "file content for integration test" in dest.read_text()

    def test_upload_with_burn(self):
        """--burn drop is deleted after first get."""
        k = unique_key("burn")
        rc, _, _ = drp("up", "burn me", "-k", k, "--burn")
        assert rc == 0

        # First get succeeds
        rc, out, _ = drp("get", k)
        assert rc == 0
        assert "burn me" in out

        # Second get fails (already burned)
        rc, _, err = drp("get", k)
        assert rc != 0

    def test_get_nonexistent(self):
        """drp get <bogus> exits nonzero."""
        rc, _, err = drp("get", "nonexistent-key-zzz999")
        assert rc != 0
        assert "not found" in (err.lower() + "")


# ── Status ────────────────────────────────────────────────────────────────────

class TestStatus:

    def test_drop_status(self, text_drop):
        """drp status <key> shows view count and kind."""
        key, _ = text_drop
        rc, out, _ = drp("status", key)
        assert rc == 0
        assert key in out
        assert "views" in out.lower() or "kind" in out.lower()

    def test_status_nonexistent(self):
        """drp status <bogus> exits nonzero."""
        rc, _, err = drp("status", "nonexistent-key-zzz999")
        assert rc != 0

    def test_global_status(self):
        """drp status (no key) shows config info."""
        rc, out, _ = drp("status")
        assert rc == 0
        assert "host" in out.lower() or "drp" in out.lower()


# ── Rename ────────────────────────────────────────────────────────────────────

class TestRename:

    def test_mv(self, text_drop):
        """drp mv <old> <new> renames the drop."""
        old_key, content = text_drop
        new_key = unique_key("mv")

        rc, out, err = drp("mv", old_key, new_key)
        combined = (out + err).lower()
        if rc != 0 and ("protected" in combined or "locked" in combined):
            pytest.skip("Drop is locked (24h protection on paid accounts)")
        assert rc == 0
        assert new_key in out

        # Old key gone
        rc, _, _ = drp("get", old_key)
        assert rc != 0

        # New key has the content
        rc, out, _ = drp("get", new_key)
        assert rc == 0
        assert content in out

        # Cleanup moved key
        drp("rm", new_key)

    def test_mv_conflict(self, text_drop):
        """drp mv to an existing key fails."""
        key, _ = text_drop
        other = unique_key("conflict")
        drp("up", "blocker", "-k", other)

        rc, out, err = drp("mv", key, other)
        combined = (out + err).lower()
        # Either conflict (taken) or lock (protected) — both are valid rejections
        assert rc != 0

        drp("rm", other)


# ── Copy ──────────────────────────────────────────────────────────────────────

class TestCopy:

    def test_cp(self, text_drop):
        """drp cp <key> <new> duplicates the drop."""
        key, content = text_drop
        copy_key = unique_key("cp")

        rc, out, err = drp("cp", key, copy_key)
        combined = (out + err).lower()
        if rc != 0 and ("protected" in combined or "locked" in combined):
            pytest.skip("Drop is locked (24h protection on paid accounts)")
        assert rc == 0
        assert "→" in out or "✓" in out

        # Extract the actual resulting key from the output (server may auto-generate)
        actual_key = copy_key
        for line in out.splitlines():
            if "→" in line:
                # Format: "  ✓ /old/ → /new/"
                after_arrow = line.split("→")[-1].strip()
                actual_key = after_arrow.strip("/").strip()
                break

        rc, out, _ = drp("get", actual_key)
        assert rc == 0
        assert content in out

        drp("rm", actual_key)

    def test_cp_auto_key(self, text_drop):
        """drp cp <key> (no new_key) auto-generates a key."""
        key, content = text_drop

        rc, out, err = drp("cp", key)
        combined = (out + err).lower()
        if rc != 0 and ("protected" in combined or "locked" in combined):
            pytest.skip("Drop is locked (24h protection on paid accounts)")
        assert rc == 0
        assert "/" in out

        # Extract auto-generated key and clean up
        for line in out.splitlines():
            if "\u2192" in line or "→" in line:
                parts = line.split("/")
                for p in parts:
                    p = p.strip().rstrip("/")
                    if p and p != key and len(p) > 2:
                        drp("rm", p)
                        break


# ── Renew ─────────────────────────────────────────────────────────────────────

class TestRenew:

    def test_renew(self, text_drop):
        """drp renew <key> extends the expiry."""
        key, _ = text_drop
        rc, out, err = drp("renew", key)
        combined = (out + err).lower()
        if rc != 0 and ("owner" in combined or "protected" in combined):
            pytest.skip("Renew blocked by server policy (ownership/lock)")
        assert rc == 0
        assert "renewed" in out.lower() or "renew" in out.lower() or "✓" in out


# ── Delete ────────────────────────────────────────────────────────────────────

class TestDelete:

    def test_rm(self):
        """drp rm <key> deletes the drop."""
        k = unique_key("rm")
        drp("up", "delete me", "-k", k)

        rc, out, err = drp("rm", k)
        combined = (out + err).lower()
        if rc != 0 and ("protected" in combined or "locked" in combined):
            pytest.skip("Drop is locked (24h protection on paid accounts)")
        assert rc == 0
        assert "deleted" in out.lower() or "✓" in out

        # Confirm gone
        rc, _, _ = drp("get", k)
        assert rc != 0

    def test_rm_nonexistent(self):
        """drp rm <bogus> exits nonzero."""
        rc, _, _ = drp("rm", "nonexistent-key-zzz999")
        assert rc != 0


# ── Ls ────────────────────────────────────────────────────────────────────────

class TestLs:

    def test_ls(self):
        """drp ls runs successfully."""
        rc, out, _ = drp("ls")
        assert rc == 0
        # Either shows drops or "(no drops)"
        assert len(out.strip()) > 0

    def test_ls_long(self):
        """drp ls -l runs and shows extended format."""
        rc, out, _ = drp("ls", "-l")
        assert rc == 0
        assert len(out.strip()) > 0

    def test_ls_export(self):
        """drp ls --export outputs valid JSON (may have trailing version notice)."""
        rc, out, _ = drp("ls", "--export")
        assert rc == 0
        # Strip trailing version notice lines (non-JSON)
        lines = out.strip().splitlines()
        json_lines = []
        for line in lines:
            json_lines.append(line)
            if line.strip() == "}":
                break
        data = json.loads("\n".join(json_lines))
        assert "drops" in data


# ── Ping ──────────────────────────────────────────────────────────────────────

class TestPing:

    def test_ping(self):
        """drp ping succeeds."""
        rc, out, _ = drp("ping")
        assert rc == 0
        assert "reachable" in out.lower() or "✓" in out


# ── Getlink ───────────────────────────────────────────────────────────────────

class TestGetlink:

    def test_getlink(self, text_drop):
        """drp getlink <key> prints the URL."""
        key, _ = text_drop
        rc, out, _ = drp("getlink", key)
        assert rc == 0
        assert key in out
        assert "http" in out.lower()


# ── Rekey (alias for mv) ─────────────────────────────────────────────────────

class TestRekey:

    def test_rekey(self, text_drop):
        """drp rekey <old> <new> renames the drop (same as mv)."""
        old_key, content = text_drop
        new_key = unique_key("rk")

        rc, out, err = drp("rekey", old_key, new_key)
        combined = (out + err).lower()
        if rc != 0 and ("protected" in combined or "locked" in combined):
            pytest.skip("Drop is locked (24h protection on paid accounts)")
        assert rc == 0

        rc, out, _ = drp("get", new_key)
        assert rc == 0
        assert content in out

        drp("rm", new_key)
