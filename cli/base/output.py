"""
cli/base/output.py

Rich output helpers shared across all commands.
All methods are mixed into BaseCommand — not instantiated directly.
"""
from __future__ import annotations
import sys
import time
from .color import Color
from .highlight import Highlight


class OutputMixin:

    # ------------------------------------------------------------------ basics

    def out(self, text: str = "", **kwargs) -> None:
        print(text, **kwargs)

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

        def _cell(text: str, w: int) -> str:
            return f" {text.ljust(w)} "

        top_line = "┬".join("─" * (widths[c] + 2) for c in columns)
        sep_line = "┼".join("─" * (widths[c] + 2) for c in columns)
        bot_line = "┴".join("─" * (widths[c] + 2) for c in columns)

        self.out(Color.dim("┌" + top_line + "┐"))
        header = "│".join(Color.dim(_cell(c.upper(), widths[c])) for c in columns)
        self.out(Color.dim("│") + header + Color.dim("│"))
        self.out(Color.dim("├" + sep_line + "┤"))
        for row in rows:
            line = "│".join(_cell(str(row.get(c, "")), widths[c]) for c in columns)
            self.out(Color.dim("│") + line + Color.dim("│"))
        self.out(Color.dim("└" + bot_line + "┘"))

    def progress_reader(self, file_obj, size: int, label: str):
        """
        Wrap a file-like object so reading it draws a live progress bar with speed.
        Returns an object suitable for passing to requests multipart upload.
        """
        done  = [0]
        start = [time.monotonic()]

        def _draw(n: int) -> None:
            try:
                elapsed = time.monotonic() - start[0]
                pct     = n / size if size else 1
                filled  = int(30 * pct)
                bar     = "=" * filled + "-" * (30 - filled)
                speed   = (_fmt_size(int(n / elapsed)) + "/s") if elapsed > 0.2 else "---"
                sys.stderr.write(
                    f"\r  {Color.dim(label)}  [{Color.wrap(bar, Color.CYAN)}]"
                    f"  {Color.dim(_fmt_size(n) + '/' + _fmt_size(size) + '  ' + speed)}"
                )
                sys.stderr.flush()
            except Exception:
                pass

        class _Reader:
            def read(self, n=-1):
                try:
                    chunk = file_obj.read(n)
                    if chunk:
                        done[0] += len(chunk)
                        _draw(done[0])
                    return chunk
                except Exception:
                    return b""
            def __len__(self):
                return size

        _draw(0)
        return _Reader()

    def progress_clear(self) -> None:
        """Clear the progress line after an upload/download finishes."""
        try:
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()
        except Exception:
            pass

    def progress_stream(self, resp, dest_path, size: int, label: str) -> None:
        """Stream a requests Response to dest_path while drawing a live progress bar."""
        done  = 0
        start = time.monotonic()

        def _draw(n: int) -> None:
            try:
                elapsed = time.monotonic() - start
                pct     = n / size if size else 1
                filled  = int(30 * pct)
                bar     = "=" * filled + "-" * (30 - filled)
                speed   = (_fmt_size(int(n / elapsed)) + "/s") if elapsed > 0.2 else "---"
                sys.stderr.write(
                    f"\r  {Color.dim(label)}  [{Color.wrap(bar, Color.CYAN)}]"
                    f"  {Color.dim(_fmt_size(n) + ('/' + _fmt_size(size) if size else '') + '  ' + speed)}"
                )
                sys.stderr.flush()
            except Exception:
                pass

        _draw(0)
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    done += len(chunk)
                    _draw(done)
        self.progress_clear()

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

def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"