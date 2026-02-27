"""drp CLI — command-line tool for drp.

Drop, share, and manage text snippets and files from the terminal.
https://drp.fyi
"""  # noqa: D400

# VERSION file holds major.minor (e.g. "1.0") — only bumped manually.
# CI queries PyPI for latest published version, bumps patch +1,
# and seds this line to a literal before building: __version__ = '1.0.42'
# Nothing committed back — merges between dev↔main stay clean.
# Fallback: importlib.metadata for installed packages.

def _resolve_version():
    from pathlib import Path
    vf = Path(__file__).resolve().parent.parent / 'VERSION'
    if vf.is_file():
        return vf.read_text().strip()
    try:
        from importlib.metadata import version
        return version('drp-dev')
    except Exception:
        pass
    try:
        from importlib.metadata import version
        return version('drp')
    except Exception:
        return '0.0.0'

__version__ = _resolve_version()
DEFAULT_HOST = 'https://drp.fyi'