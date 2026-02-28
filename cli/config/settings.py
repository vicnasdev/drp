"""
cli/config/settings.py

Load and save ~/.config/drp/config.toml.

Config structure:
    [server]
    url = "https://drp.fyi"

    [auth]
    username = "vic"
    token    = "<api-token>"

    [prefs]
    color    = true
    editor   = ""        # falls back to $EDITOR
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    import tomllib                          # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib             # type: ignore[no-redef]
    except ImportError:
        tomllib = None                      # type: ignore[assignment]

try:
    import tomli_w                          # type: ignore[import]
except ImportError:
    tomli_w = None                          # type: ignore[assignment]


CONFIG_DIR  = Path(os.environ.get("DRP_CONFIG_DIR", Path.home() / ".config" / "drp"))
CONFIG_FILE = CONFIG_DIR / "config.toml"

_DEFAULTS: dict = {
    "server":  {"url": "https://drp.fyi"},
    "auth":    {"username": "", "token": ""},
    "prefs":   {"color": True, "editor": ""},
}


def load() -> dict:
    """Load config from disk. Returns defaults if file missing or unreadable."""
    if not CONFIG_FILE.exists():
        return _deep_merge({}, _DEFAULTS)

    try:
        if tomllib is not None:
            with open(CONFIG_FILE, "rb") as f:
                data = tomllib.load(f)
        else:
            data = _read_manual()
        return _deep_merge(data, _DEFAULTS)
    except Exception:
        return _deep_merge({}, _DEFAULTS)


def save(config: dict) -> None:
    """Persist config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if tomli_w is not None:
        with open(CONFIG_FILE, "wb") as f:
            tomli_w.dump(config, f)
    else:
        _write_manual(config)


def set_auth(username: str, token: str) -> None:
    cfg = load()
    cfg.setdefault("auth", {})["username"] = username
    cfg["auth"]["token"] = token
    save(cfg)


def clear_auth() -> None:
    cfg = load()
    cfg["auth"] = {"username": "", "token": ""}
    save(cfg)


def set_server(url: str) -> None:
    cfg = load()
    cfg.setdefault("server", {})["url"] = url.rstrip("/")
    save(cfg)


# ------------------------------------------------------------------ helpers

def _deep_merge(data: dict, defaults: dict) -> dict:
    result = dict(defaults)
    for k, v in data.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(v, result[k])
        else:
            result[k] = v
    return result


def _write_manual(config: dict) -> None:
    """Write a minimal but valid TOML file without tomli_w."""
    lines = []
    for section, values in config.items():
        lines.append(f"[{section}]")
        if isinstance(values, dict):
            for k, v in values.items():
                if isinstance(v, bool):
                    lines.append(f"{k} = {'true' if v else 'false'}")
                elif isinstance(v, str):
                    escaped = v.replace("\\", "\\\\").replace('"', '\\"')
                    lines.append(f'{k} = "{escaped}"')
                else:
                    lines.append(f"{k} = {v}")
        lines.append("")   # blank line between sections
    CONFIG_FILE.write_text("\n".join(lines), encoding="utf-8")


def _read_manual() -> dict:
    """Parse the simple TOML subset written by _write_manual."""
    data:    dict = {}
    section: str  = ""
    for raw in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            data.setdefault(section, {})
            continue
        if "=" in line and section:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if val.lower() == "true":
                data[section][key] = True
            elif val.lower() == "false":
                data[section][key] = False
            elif val.startswith('"') and val.endswith('"'):
                data[section][key] = val[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            else:
                try:
                    data[section][key] = int(val)
                except ValueError:
                    data[section][key] = val
    return data