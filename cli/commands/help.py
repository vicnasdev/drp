"""help — List commands or describe a specific command."""

from rich import print
from rich.table import Table

from . import Arg, Command, register, _COMMANDS


def run(args):
    target = args.get("command")

    if target:
        c = _COMMANDS.get(target)
        if not c:
            print(f"[red]✗[/red] Unknown command: {target}")
            return
        print(f"[bold]{c.name}[/bold] — {c.description}")
        if c.args:
            table = Table(show_header=True, header_style="bold")
            table.add_column("Argument")
            table.add_column("Required")
            table.add_column("Description")
            for arg in c.args:
                table.add_row(
                    arg.name,
                    "✓" if arg.required else "",
                    arg.description,
                )
            print(table)
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Command")
    table.add_column("Description")
    for name, c in sorted(_COMMANDS.items()):
        if name == c.name:  # skip aliases
            table.add_row(name, c.description)
    print(table)


cmd = register(Command(
    name="help",
    description="List all commands or show help for a specific command.",
    args=(
        Arg("command", "Command to describe"),
    ),
    run=run
))