"""
DrpPath — pathlib-style wrapper over the drp API.

Locally, paths are displayed WITHOUT the @user prefix:

    /                               root (user's drops + folders)
    docs/                           folder
    docs/sub/                       nested folder
    docs/sub/readme                 drop inside a nested folder
    key                             standalone drop

The @user prefix is an online/web concept — the CLI never shows it.
Local filesystem paths (starting with ./ ../ / ~) are handled by pathlib.Path.
The shell treats drp as a virtual mount alongside the local FS:

    cp ./readme.md docs/            upload local file into docs folder
    cp docs/readme.md ./            download to local
    cp a.txt b.txt                  drp-to-drp copy
    ls                              list drp cwd
    ls ./                           list local files

The shell's cwd is a DrpPath pointing at a folder (or root).
All shell commands (ls, cd, mv, cp, rm, cat, …) delegate to DrpPath methods,
so the command layer stays thin.
"""

from __future__ import annotations

import os
import posixpath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union


# ── Entry: one item returned by ls ────────────────────────────────────────────

@dataclass
class Entry:
    """Represents a drop or folder returned by a listing."""
    name: str                          # display name (filename or folder slug)
    is_dir: bool = False               # True for folders
    key: str = ""                      # drop key (empty for folders)
    kind: str = ""                     # "text" | "file" | ""
    size: int = 0                      # bytes (files only)
    created: str = ""                  # ISO timestamp
    expires: str = ""                  # ISO timestamp or ""
    locked: bool = False
    view_count: int = 0
    folder_id: int = 0                 # server-side folder PK (folders only)
    children: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


# ── DrpPath ───────────────────────────────────────────────────────────────────

class DrpPath:
    """
    Immutable path object that lazily hits the API.

    Does NOT cache state — every method call that needs data makes a request.
    Callers (shell, commands) handle spinners, formatting, and retries.
    """

    __slots__ = ("_host", "_session", "_parts", "_username")

    def __init__(self, path: str, host: str, session, username: str = ""):
        self._host = host
        self._session = session
        self._username = username
        # Normalise: strip @, slashes, collapse empties
        clean = path.strip("/")
        if clean.startswith("@"):
            clean = clean[1:]
        self._parts = tuple(p for p in clean.split("/") if p)

    # ── Path algebra ──────────────────────────────────────────────────────────

    @property
    def parts(self) -> tuple[str, ...]:
        return self._parts

    @property
    def name(self) -> str:
        """Last component (like pathlib)."""
        return self._parts[-1] if self._parts else ""

    @property
    def parent(self) -> DrpPath:
        """Parent path (one level up)."""
        return DrpPath(
            "/".join(self._parts[:-1]) if self._parts else "",
            self._host, self._session, self._username,
        )

    @property
    def is_root(self) -> bool:
        """True when pointing at the user root (@user)."""
        return len(self._parts) == 0 or (
            len(self._parts) == 1 and self._parts[0] == self._username
        )

    def __truediv__(self, child: str) -> DrpPath:
        """p / 'sub' → child path."""
        return DrpPath(
            "/".join(self._parts) + "/" + child,
            self._host, self._session, self._username,
        )

    def __str__(self) -> str:
        """Display path locally — never shows @user."""
        display = self._parts
        if display and display[0] == self._username:
            display = display[1:]
        if not display:
            return "/"
        return "/".join(display)

    def __repr__(self) -> str:
        return f"DrpPath({str(self)!r})"

    @property
    def api_path(self) -> str:
        """Full path with username for API URLs (e.g. 'user/docs')."""
        return "/".join(self._parts) if self._parts else self._username

    def resolve(self, target: str) -> DrpPath:
        """Resolve *target* relative to self (supports . / .. / absolute @paths)."""
        if target.startswith("@"):
            return DrpPath(target, self._host, self._session, self._username)
        if target.startswith("/"):
            # Absolute from user root
            return DrpPath(
                self._username + "/" + target,
                self._host, self._session, self._username,
            )
        combined = "/".join(self._parts) + "/" + target
        normalised = posixpath.normpath(combined)
        return DrpPath(normalised, self._host, self._session, self._username)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _json_get(self, url: str, **kw) -> dict | None:
        """GET with Accept: application/json. Returns parsed dict or None."""
        kw.setdefault("timeout", 15)
        headers = kw.pop("headers", {})
        headers["Accept"] = "application/json"
        res = self._session.get(url, headers=headers, **kw)
        if res.ok:
            return res.json()
        return None

    def _csrf(self) -> str:
        from cli.api.auth import get_csrf
        return get_csrf(self._host, self._session)

    # ── Core operations ───────────────────────────────────────────────────────

    def ls(self) -> list[Entry]:
        """
        List contents.

        At root (/)  → fetches /auth/account/ and returns drops + folders.
        At a folder  → fetches /@<user>/path/ API and returns folder items + children.
        """
        if self.is_root:
            return self._ls_root()
        return self._ls_folder()

    def _ls_root(self) -> list[Entry]:
        data = self._json_get(f"{self._host}/auth/account/")
        if data is None:
            return []
        entries: list[Entry] = []
        # Folders first (top-level only)
        for f in data.get("folders", []):
            if f.get("parent_id"):
                continue  # only show root-level folders in root listing
            entries.append(Entry(
                name=f.get("slug", ""),
                is_dir=True,
                folder_id=f.get("id", 0),
                children=f.get("children", []),
            ))
        # Then drops
        for d in data.get("drops", []):
            entries.append(_entry_from_drop(d))
        return entries

    def _ls_folder(self) -> list[Entry]:
        url = f"{self._host}/@{self.api_path}/"
        data = self._json_get(url)
        if data is None:
            return []
        entries: list[Entry] = []
        # Sub-folders
        for slug in data.get("children", []):
            entries.append(Entry(name=slug, is_dir=True))
        # Drops
        for item in data.get("drops", []):
            key = item.get("key", "")
            # The folder view only returns keys — fetch metadata
            entries.append(Entry(name=key, key=key))
        return entries

    def stat(self) -> Entry | None:
        """Fetch metadata for a single drop or folder."""
        # Try as a drop first
        data = self._json_get(f"{self._host}/{self.name}/")
        if data and not data.get("error"):
            return _entry_from_drop(data)
        return None

    def read(self, password: str = "") -> dict | None:
        """
        Fetch drop content (text or file metadata).
        Returns the full JSON dict from the server or None.
        """
        headers: dict = {"Accept": "application/json"}
        if password:
            headers["X-Drop-Password"] = password
        res = self._session.get(
            f"{self._host}/{self.name}/", headers=headers, timeout=30,
        )
        if res.ok:
            return res.json()
        if res.status_code == 401:
            return {"error": "password_required"}
        return None

    def rm(self) -> bool:
        """Delete a drop. Returns True on success."""
        csrf = self._csrf()
        res = self._session.delete(
            f"{self._host}/{self.name}/delete/",
            headers={"X-CSRFToken": csrf},
            timeout=10,
        )
        if res.ok:
            from cli.config import remove_local_drop
            remove_local_drop(self.name)
            return True
        return False

    def cp(self, dst_key: str) -> str | None:
        """Server-side copy. Returns new key on success."""
        csrf = self._csrf()
        res = self._session.post(
            f"{self._host}/{self.name}/copy/",
            data={"new_key": dst_key, "csrfmiddlewaretoken": csrf},
            timeout=10,
        )
        if res.ok:
            data = res.json()
            new_key = data.get("key", dst_key)
            from cli.config import record_drop
            record_drop(new_key, data.get("kind", "text"), host=self._host)
            return new_key
        return None

    def mv(self, new_name: str) -> str | None:
        """
        Rename a drop (change its filename / display name).
        Returns the new key on success, None on failure.

        NOTE: right now the server's rename endpoint changes the *key* (URL slug).
        When we add a proper filename field, this will change to update that instead.
        For now mv == rekey.
        """
        return self.rekey(new_name)

    def rekey(self, new_key: str) -> str | None:
        """Change the URL key (slug). Returns new key on success."""
        csrf = self._csrf()
        res = self._session.post(
            f"{self._host}/{self.name}/rename/",
            data={"new_key": new_key, "csrfmiddlewaretoken": csrf},
            timeout=10,
        )
        if res.ok:
            data = res.json()
            actual = data.get("key", new_key)
            from cli.config import rename_local_drop
            rename_local_drop(self.name, actual)
            return actual
        return None

    def mkdir(self, name: str = "", parent_id: int | None = None) -> dict | None:
        """
        Create a folder.
        If called on root, creates a top-level folder named *name*.
        Returns the server response dict on success.
        """
        csrf = self._csrf()
        payload: dict = {"name": name or self.name}
        if parent_id:
            payload["parent_id"] = parent_id
        res = self._session.post(
            f"{self._host}/folders/create/",
            json=payload,
            headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
            timeout=10,
        )
        if res.status_code == 201:
            return res.json()
        return None

    def add_to_folder(self, folder_id: int) -> bool:
        """Add this drop (by key) to a folder."""
        csrf = self._csrf()
        res = self._session.post(
            f"{self._host}/folders/{folder_id}/add/",
            json={"key": self.name},
            headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
            timeout=10,
        )
        return res.ok

    def remove_from_folder(self, folder_id: int) -> bool:
        """Remove this drop from a folder."""
        csrf = self._csrf()
        res = self._session.post(
            f"{self._host}/folders/{folder_id}/remove/",
            json={"key": self.name},
            headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
            timeout=10,
        )
        return res.ok

    def exists(self) -> bool:
        """HEAD-style check: does this key exist on the server?"""
        res = self._session.get(
            f"{self._host}/check-key/",
            params={"key": self.name},
            timeout=10,
        )
        if res.ok:
            return not res.json().get("available", True)
        return False

    def lock(self, password: str | None = None, remove: bool = False) -> bool:
        """Set or remove password on a drop."""
        csrf = self._csrf()
        payload: dict = {"csrfmiddlewaretoken": csrf}
        if remove:
            payload["action"] = "remove"
        elif password:
            payload["password"] = password
        res = self._session.post(
            f"{self._host}/{self.name}/set-password/",
            data=payload, timeout=10,
        )
        return res.ok

    def send(self) -> str | None:
        """Create a transfer token. Returns the token string."""
        csrf = self._csrf()
        res = self._session.post(
            f"{self._host}/{self.name}/send/",
            headers={"X-CSRFToken": csrf},
            timeout=10,
        )
        if res.ok:
            return res.json().get("token")
        return None

    def claim(self, token: str) -> dict | None:
        """Claim a drop via transfer token."""
        csrf = self._csrf()
        res = self._session.post(
            f"{self._host}/claim/{token}/",
            headers={"X-CSRFToken": csrf},
            timeout=10,
        )
        if res.ok:
            return res.json()
        return None

    def share(self, role: str = "reader") -> str | None:
        """Create a folder invite token. Returns the token string."""
        # First resolve the folder to get its ID
        url = f"{self._host}/@{self.api_path}/"
        data = self._json_get(url)
        if not data or not data.get("id"):
            return None
        folder_id = data["id"]
        csrf = self._csrf()
        res = self._session.post(
            f"{self._host}/folders/{folder_id}/invite/",
            json={"role": role},
            headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
            timeout=10,
        )
        if res.ok or res.status_code == 201:
            return res.json().get("token")
        return None

    def info(self) -> dict | None:
        """Full metadata dict for a drop — same as read() but named for clarity."""
        return self.read()

    def url(self) -> str:
        """Return the web URL for this path (uses @user — online only)."""
        if self.is_root:
            return f"{self._host}/@{self._username}/"
        return f"{self._host}/@{self.api_path}/"

    def open_url(self) -> str:
        """Return a URL suitable for opening in browser."""
        return self.url()

    def download_url(self) -> str:
        """Return the download URL for a file drop."""
        return f"{self._host}/{self.name}/download/"

    def raw_url(self) -> str:
        """Return the raw content URL for a text drop."""
        return f"{self._host}/raw/{self.name}/"

    def save_bookmark(self) -> bool:
        """Bookmark this drop."""
        csrf = self._csrf()
        res = self._session.post(
            f"{self._host}/{self.name}/save/",
            data={"csrfmiddlewaretoken": csrf},
            timeout=10,
            allow_redirects=False,
        )
        return res.ok and res.status_code not in (301, 302, 303)

    def renew(self) -> tuple[str | None, int | None]:
        """Renew expiry. Returns (new_expires_at, renewal_count) or (None, None)."""
        csrf = self._csrf()
        res = self._session.post(
            f"{self._host}/{self.name}/renew/",
            data={"csrfmiddlewaretoken": csrf},
            timeout=10,
        )
        if res.ok:
            data = res.json()
            return data.get("expires_at"), data.get("renewals")
        return None, None

    # ── Upload / Download (mount bridge) ──────────────────────────────────────

    def upload_file(self, local: Path, key: str = "",
                    expires: int | None = None, burn: bool = False,
                    password: str = "") -> str | None:
        """
        Upload a local file as a drop and (if inside a folder) add it.
        Returns the new key on success, None on failure.
        """
        from cli.api.file import upload_file as _upload_file
        from cli.config import record_drop

        result = _upload_file(
            self._host, self._session, str(local),
            key=key or None, expiry_days=expires,
            password=password or None,
        )
        if not result:
            return None
        new_key = result if isinstance(result, str) else result.get("key", key)
        record_drop(new_key, "file", filename=local.name, host=self._host)
        # Auto-add to folder if we're inside one
        self._auto_add_to_folder(new_key)
        return new_key

    def upload_text(self, content: str, key: str = "",
                    expires: int | None = None, burn: bool = False,
                    password: str = "") -> str | None:
        """
        Upload text as a drop and (if inside a folder) add it.
        Returns the new key on success, None on failure.
        """
        from cli.api.text import upload_text as _upload_text
        from cli.config import record_drop

        result = _upload_text(
            self._host, self._session, content,
            key=key or None, expiry_days=expires, burn=burn,
            password=password or None,
        )
        if not result:
            return None
        new_key = result if isinstance(result, str) else result.get("key", key)
        record_drop(new_key, "text", host=self._host)
        self._auto_add_to_folder(new_key)
        return new_key

    def download(self, dest: Path) -> Path | None:
        """
        Download this drop to *dest* (file or directory).
        If dest is a directory, uses the drop's filename.
        Returns the final Path on success, None on failure.
        """
        data = self.read()
        if data is None or data.get("error"):
            return None

        kind = data.get("kind", "text")

        if kind == "text":
            content = data.get("content", "")
            if dest.is_dir():
                dest = dest / (self.name + ".txt")
            dest.write_text(content, encoding="utf-8")
            return dest

        # File drop — use presigned URL or /download/
        url = data.get("presigned_url") or f"{self._host}/{self.name}/download/"
        res = self._session.get(url, stream=True, timeout=60)
        if not res.ok:
            return None

        filename = data.get("filename") or self.name
        if dest.is_dir():
            dest = dest / filename

        with open(dest, "wb") as f:
            for chunk in res.iter_content(8192):
                f.write(chunk)
        return dest

    def _auto_add_to_folder(self, key: str) -> None:
        """If this path points at a folder, add the drop to it."""
        if self.is_root or not self._parts:
            return
        # Try to get the folder ID
        url = f"{self._host}/@{self.api_path}/"
        data = self._json_get(url)
        if data and data.get("id"):
            csrf = self._csrf()
            self._session.post(
                f"{self._host}/folders/{data['id']}/add/",
                json={"key": key},
                headers={"X-CSRFToken": csrf, "Content-Type": "application/json"},
                timeout=10,
            )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _entry_from_drop(d: dict) -> Entry:
    """Convert a drop dict (from server JSON) to an Entry."""
    key = d.get("key", "")
    return Entry(
        name=d.get("filename") or key,
        key=key,
        kind=d.get("kind", "text"),
        size=d.get("filesize", 0),
        created=d.get("created_at", ""),
        expires=d.get("expires_at", ""),
        locked=d.get("locked", False) or d.get("password_protected", False),
        view_count=d.get("view_count", 0),
        extra=d,
    )


# ── Path resolver ─────────────────────────────────────────────────────────────

def is_drp_path(s: str) -> bool:
    """True if *s* looks like a drp path (starts with @). Mainly for outside-shell use."""
    return s.startswith("@")


def is_local_path(s: str) -> bool:
    """True if *s* explicitly references the local filesystem."""
    return s.startswith(("./", "../", "/", "~"))


def resolve_any(
    s: str,
    host: str,
    session,
    username: str = "",
    cwd: "DrpPath | None" = None,
) -> Union[DrpPath, Path]:
    """
    Resolve a user-typed path to either a DrpPath or a local Path.

    Inside the shell (cwd is set), the drp mount is the default:
        docs/readme     → DrpPath  (drp child of cwd)
        ./foo           → Path     (explicit local)
        ../bar          → Path     (explicit local)
        /abs/path       → Path     (absolute local)
        ~/stuff         → Path     (home-relative local)

    Outside the shell (cwd is None):
        @user/…         → DrpPath  (absolute drp path — kept for programmatic use)
        anything else   → Path     (local)
    """
    s = s.strip()
    # Explicit local path prefix → always local
    if is_local_path(s):
        return Path(os.path.expanduser(s)).resolve()
    # Explicit @ prefix → always drp (works inside and outside shell)
    if is_drp_path(s):
        return DrpPath(s, host, session, username)
    # Inside shell: bare name → drp child of cwd
    if cwd is not None:
        return cwd / s
    # Outside shell: bare name → local
    return Path(s).resolve()
