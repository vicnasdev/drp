"""drp CLI — file and text sharing from the command line."""

__version__ = open(
    __import__("pathlib").Path(__file__).resolve().parent.parent / "VERSION"
).read().strip()
