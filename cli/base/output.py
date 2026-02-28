"""
cli/base/output.py

Rich output helpers shared across all commands.
All methods are mixed into BaseCommand — not instantiated directly.
"""
from __future__ import annotations
import sys
from .color import Color
from .highlight import Highlight


class OutputMixin:

    # ------------------------------------------------------------------ basics

    def out(self, text: str = "") -> None:
        print(text)

    def err(self, text: str) -> None:
        print(Color.error("error: ") + text, file=sys.stderr)

    def success(self, text: str) -> None:
        print(Color.success("✓ ") + text)

    def warn(self, text: str) -> None:
        print(Color.warn("warn: ") + text, file=sys.stderr)

    def dim(self, text: str) -> None:
        print(Color.dim(text))

    def info(self, text: str) -> None:
        print(Color.info(text))

    # ------------------------------------------------------------------ rich

    def print_key(self, key: str, base_url: str) -> None:
        url = f"{base_url.rstrip('/')}/{key}/"
        self.out(f"{Color.dim('key')}  {Color.key(key)}")
        self.out(f"{Color.dim('url')}  {Color.url(url)}")

    def print_content(
        self,
        content: str,
        filename: str | None = None,
        lexer: str | None = None,
    ) -> None:
        self.out(Highlight.code(content, lexer_name=lexer, filename=filename))

    def print_table(self, rows: list[dict], columns: list[str]) -> None:
        if not rows:
            self.dim("(empty)")
            return

        widths = {c: len(c) for c in columns}
        for row in rows:
            for c in columns:
                widths[c] = max(widths[c], len(str(row.get(c, ""))))

        sep   = "  "
        head  = sep.join(Color.dim(c.upper().ljust(widths[c])) for c in columns)
        ruler = Color.dim("-" * (sum(widths.values()) + len(sep) * (len(columns) - 1)))
        self.out(head)
        self.out(ruler)
        for row in rows:
            self.out(sep.join(str(row.get(c, "")).ljust(widths[c]) for c in columns))

    def print_drop_table(self, drops: list[dict]) -> None:
        """
        Specialised table for ls output.
        Columns: FILENAME, PREVIEW, OWNER, SIZE, EXP, KEY
        PREVIEW only shown for text files (non-empty preview field).
        KEY is always dimmed.
        """
        if not drops:
            self.dim("(empty)")
            return

        cols = ["filename", "preview", "owner", "size", "exp", "key"]
        widths = {c: len(c) for c in cols}
        for d in drops:
            for c in cols:
                widths[c] = max(widths[c], len(str(d.get(c, ""))))

        sep = "  "
        self.out(sep.join(Color.dim(c.upper().ljust(widths[c])) for c in cols))
        self.out(Color.dim("-" * (sum(widths.values()) + len(sep) * (len(cols) - 1))))

        for d in drops:
            owner_str = Color.owner(f"→ {d['owner']}") if d.get("owner") else ""
            exp_str   = Color.warn(d.get("exp", "")) if d.get("exp") == "expired" else d.get("exp", "")
            key_str   = Color.dim(d.get("key", ""))
            row = (
                str(d.get("filename", "")).ljust(widths["filename"]) + sep
                + Color.dim(str(d.get("preview", "")).ljust(widths["preview"])) + sep
                + owner_str.ljust(widths["owner"]) + sep
                + str(d.get("size", "")).ljust(widths["size"]) + sep
                + exp_str.ljust(widths["exp"]) + sep
                + key_str
            )
            self.out(row)

    def confirm(self, prompt: str, default: bool = False) -> bool:
        """y/N prompt. Returns bool."""
        hint  = "[y/N]" if not default else "[Y/n]"
        try:
            answer = input(f"{prompt} {hint} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if not answer:
            return default
        return answer in ("y", "yes")
