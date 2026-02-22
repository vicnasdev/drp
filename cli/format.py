"""
Formatting helpers: human-readable sizes, times, and minimal ANSI color.

Color is gated on the 'ansi' key in config (set by drp setup) and
os.isatty() on the underlying file descriptor so nothing leaks into pipes
or logs — and argcomplete wrapping doesn't break TTY detection.

Override with FORCE_COLOR=1 env var for terminals that don't report isatty()
correctly (some tmux, screen, VS Code, SSH setups).
"""

import math
import os
import sys
from datetime import datetime, timezone as tz


# ── Human-readable sizes and times ────────────────────────────────────────────

def human_size(n):
    """1234567 → '1.2 M'  (like ls -lh)"""
    if not n:
        return '-'
    units = ['B', 'K', 'M', 'G', 'T']
    i = int(math.log(max(n, 1), 1024))
    i = min(i, len(units) - 1)
    val = n / (1024 ** i)
    if i == 0:
        return f'{n}B'
    return f'{val:.1f}{units[i]}'


def human_time(iso_str):
    """ISO datetime → human-friendly relative or absolute."""
    if not iso_str:
        return '-'
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        now = datetime.now(tz.utc)
        secs = (now - dt).total_seconds()
        if secs < 60:
            return 'just now'
        if secs < 3600:
            return f'{int(secs / 60)}m ago'
        if secs < 86400:
            return f'{int(secs / 3600)}h ago'
        if secs < 86400 * 7:
            return f'{int(secs / 86400)}d ago'
        return dt.strftime('%Y-%m-%d')
    except Exception:
        return iso_str[:10]


# ── ANSI color ─────────────────────────────────────────────────────────────────
#
# Uses os.isatty(fd) on the underlying file descriptor rather than
# stream.isatty() so that argcomplete's stdout wrapper (which returns
# isatty()=False) doesn't suppress colors on bare `drp`.
#
# Priority:
#   NO_COLOR env var → always off
#   FORCE_COLOR env var → on if config ansi=true (skips TTY check)
#   Normal → config ansi=true AND underlying fd is a real TTY

def _ansi_on(stream=None) -> bool:
    # NO_COLOR always wins
    if os.environ.get('NO_COLOR'):
        return False
    # Config gate — must be explicitly enabled by drp setup
    try:
        from cli import config as _cfg
        if not _cfg.load().get('ansi', False):
            return False
    except Exception:
        return False
    # FORCE_COLOR skips TTY detection (useful for tmux/screen/VS Code/SSH)
    if os.environ.get('FORCE_COLOR'):
        return True
    # Check the real underlying fd — immune to argcomplete wrapper
    target = stream if stream is not None else sys.stdout
    try:
        return os.isatty(target.fileno())
    except Exception:
        return getattr(target, 'isatty', lambda: False)()


def _c(code: str, text: str, stream=None) -> str:
    if _ansi_on(stream):
        return f'\033[{code}m{text}\033[0m'
    return text


# ── Color palette ─────────────────────────────────────────────────────────────
# Brighter variants (bold+color) so output is visible on both dark and light
# terminals without being garish. dim() stays subtle intentionally.

def green(text, stream=None):    return _c('1;32', text, stream)   # bold green
def red(text, stream=None):      return _c('1;31', text, stream)   # bold red
def dim(text, stream=None):      return _c('2',    text, stream)   # faint/dim
def bold(text, stream=None):     return _c('1',    text, stream)   # bold white
def cyan(text, stream=None):     return _c('1;36', text, stream)   # bold cyan
def yellow(text, stream=None):   return _c('1;33', text, stream)   # bold yellow
def magenta(text, stream=None):  return _c('1;35', text, stream)   # bold magenta (collections)
def blue(text, stream=None):     return _c('1;34', text, stream)   # bold blue (files)
def grey(text, stream=None):     return _c('38;5;245', text, stream) # mid-grey (metadata)