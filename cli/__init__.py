"""drp CLI — file and text sharing from the command line."""

from pathlib import Path as _Path

_version_file = _Path(__file__).resolve().parent.parent / "VERSION"
try:
    __version__ = _version_file.read_text().strip()
except FileNotFoundError:
    __version__ = "0.0.0"
