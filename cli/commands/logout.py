"""logout — Revoke the current bearer token and clear local config."""

import requests
from rich import print

from . import Command, register
from cli.config import del_secret, get as get_config, get_secret
from cli.utils import spin


def run(args):
    server = get_config("server")
    token = get_secret("token")

    if token and server:
        data = requests.get(f"https://{server}/api/v1/auth/status/", headers={"Authorization": f"Token {token}"}).json()
        if data.get("plan") == "anonymous":
            ans = input("[yellow]Warning: your guest account and all its data will be permanently deleted.[/yellow]\nConfirm(YES/NO): ")
            if ans != "YES":
                print("Operation canceled")
                return 1
        requests.post(f"https://{server}/api/v1/auth/logout/", headers={"Authorization": f"Token {token}"})

    del_secret("token")
    print("[green]✓[/green] Logged out.")

cmd = register(Command(
    name="logout",
    description="Revoke the current bearer token on the server and clear local config.",
    run=spin(run, "Contacting server")
))