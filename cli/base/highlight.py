"""
cli/base/highlight.py

Pygments wrapper for syntax-highlighted output in the terminal.
Degrades silently: no pygments installed → plain text. Color disabled → plain text.
"""
from __future__ import annotations
from .color import Color


class Highlight:

    @staticmethod
    def code(
        content: str,
        lexer_name: str | None = None,
        filename: str | None = None,
    ) -> str:
        if not Color.ENABLED:
            return content
        try:
            from pygments import highlight
            from pygments.formatters import TerminalTrueColorFormatter
            from pygments.lexers import (
                get_lexer_by_name,
                guess_lexer,
                guess_lexer_for_filename,
            )
            from pygments.util import ClassNotFound

            if lexer_name:
                lexer = get_lexer_by_name(lexer_name, stripall=True)
            elif filename:
                try:
                    lexer = guess_lexer_for_filename(filename, content)
                except ClassNotFound:
                    lexer = guess_lexer(content)
            else:
                lexer = guess_lexer(content)

            return highlight(content, lexer, TerminalTrueColorFormatter(style="monokai"))
        except Exception:
            return content

    @staticmethod
    def preview(content: str, max_chars: int = 60) -> str:
        """Single-line preview snippet, no color codes — safe for table cells."""
        line = content.splitlines()[0] if content else ""
        line = line.strip()
        if len(line) > max_chars:
            line = line[:max_chars] + "…"
        return line
