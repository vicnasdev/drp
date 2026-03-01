"""drp CLI — file and text sharing from the command line."""

from importlib.metadata import version as _version, PackageNotFoundError

try:
    __version__ = _version("drp-dev")
except PackageNotFoundError:
    # Running from source checkout (not pip-installed)
    from pathlib import Path as _Path
    __version__ = (_Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()
