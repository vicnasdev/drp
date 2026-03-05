"""
Command registry — single source of truth for every CLI command.

Each command file in this package calls ``register()`` with a ``Command``
that carries the canonical name, description, arguments, and flags.
The shell, help page, and help bot all read from this registry.

    from cli.commands import all_commands, get_command

    for name, cmd in all_commands().items():
        print(cmd.name, cmd.description)
"""

from dataclasses import dataclass
from typing import Any


# ── Spec dataclasses ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Arg:
    """A positional argument or flag on a command."""

    name: str
    """Display name.  Positional: ``target``.  Flag: ``-k/--key``."""

    description: str
    """One-line human-readable help text."""

    required: bool = False
    """Must the user supply this argument?"""

    default: Any = None
    """Default value when omitted.  ``None`` means no default."""

    type: str = "str"
    """Semantic type hint: ``str``, ``bool``, ``int``, ``duration``,
    ``passphrase``, ``path``.  Used for validation and completion."""

    choices: tuple[str, ...] | None = None
    """Fixed set of valid values (e.g. sort fields)."""

    repeatable: bool = False
    """Can appear more than once (e.g. ``--tag python --tag snippet``)."""


@dataclass(frozen=True)
class Command:
    """Canonical definition of a CLI command."""

    name: str
    """Primary command name (``up``, ``cat``, …)."""

    description: str
    """One-line summary shown in help listings."""

    args: tuple[Arg, ...] = ()
    """Positional arguments and flags, in display order."""

    aliases: tuple[str, ...] = ()
    """Alternative names that resolve to this command."""
    
    run: object = lambda *args: None


# ── Registry ──────────────────────────────────────────────────────────────────

_COMMANDS: dict[str, Command] = {}


def register(cmd: Command) -> Command:
    """Add *cmd* to the global registry and return it unchanged."""
    _COMMANDS[cmd.name] = cmd
    for alias in cmd.aliases:
        _COMMANDS[alias] = cmd
    return cmd


def get_command(name: str) -> Command | None:
    """Look up a command by name or alias."""
    return _COMMANDS.get(name)


# Load commands
import importlib, pkgutil, cli.commands

for _, module_name, _ in pkgutil.iter_modules(cli.commands.__path__):
    importlib.import_module(f"cli.commands.{module_name}")