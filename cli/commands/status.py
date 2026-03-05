"""status — Display account info."""

import requests
from rich import print

from . import Command, register
from cli.config import get as get_config, get_secret


def run(args: dict[str, str]):
    server = get_config("server")
    token = get_secret("token")

    if not server or not token:
        print("[yellow]Not logged in.[/yellow] Run [bold]drp login[/bold].")
        return

    resp = requests.get(f"https://{server}/api/v1/auth/status/", headers={"Authorization": f"Token {token}"})
    if resp.status_code != 200:
        print("[red]✗[/red] Could not fetch status.")
        return

    data = resp.json()
    print(f"[bold]{data['username']}[/bold] — {data['plan']}")
    print(f"Storage: {data['storage_used_gb']} GB / {data['storage_limit_gb']} GB")
    print(f"Files: {data['file_count']}")

cmd = register(Command(
    name="status",
    description="Display account info: username, plan, storage, file count.",
    run=run
))