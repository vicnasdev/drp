"""logout — Revoke the current bearer token and clear local config."""

import requests
from rich import print

from . import Command, register
from cli.config import del_secret, get as get_config, get_secret


def run(_):
    server = get_config("server")
    token = get_secret("token")

    if token and server:
        try:
            requests.post(f"https://{server}/api/v1/auth/logout/", headers={"Authorization": f"Token {token}"})
        except Exception:
            pass

    del_secret("token")
    print("[green]✓[/green] Logged out.")
    
    
cmd = register(Command(
    name="logout",
    description="Revoke the current bearer token on the server and clear local config.",
    run=run
))


