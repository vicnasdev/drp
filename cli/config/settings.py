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

    if tomllib is None:
        return _deep_merge({}, _DEFAULTS)

    try:
        with open(CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)
        return _deep_merge(data, _DEFAULTS)
    except Exception:
        return _deep_merge({}, _DEFAULTS)


def save(config: dict) -> None:
    """Persist config to disk. Silently fails if tomli_w not available."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if tomli_w is None:
        # Fallback: write minimal INI-style TOML manually
        _write_manual(config)
        return
    with open(CONFIG_FILE, "wb") as f:
        tomli_w.dump(config, f)


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
    lines = []
    for section, values in config.items():
        lines.append(f"[{section}]")
        if isinstance(values, dict):
            for k, v in values.items():
                if isinstance(v, bool):
                    lines.append(f"{k} = {'true' if v else 'false'}")
                elif isinstance(v, str):
                    escaped = v.replace('"', '\\"')
                    lines.append(f'{k} = "{escaped}"')
                else:
                    lines.append(f"{k} = {v}")
        lines.append("")
    CONFIG_FILE.write_text("\n".join(lines))
