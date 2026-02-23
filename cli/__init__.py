"""drp CLI — command-line tool for drp."""

# Version is read from the VERSION file during development.
# CI stamps a literal string here before building the wheel.
# Fallback: importlib.metadata for installed packages.

def _resolve_version():
    from pathlib import Path
    vf = Path(__file__).resolve().parent.parent / 'VERSION'
    if vf.is_file():
        return vf.read_text().strip()
    try:
        from importlib.metadata import version
        return version('drp-cli')
    except Exception:
        pass
    try:
        from importlib.metadata import version
        return version('drp')
    except Exception:
        return '0.0.0'

__version__ = _resolve_version()
DEFAULT_HOST = 'https://drp.fyi'