"""login — Authenticate"""

import requests
from rich import print

from . import Arg, Command, register
from cli.config import set as set_config, set_secret, get_secret
from cli.defaults import server
from cli.utils import spin

def parse_server(value: str) -> str:
    from urllib.parse import urlparse
    if "://" not in value:
        value = f"https://{value}"
    return urlparse(value).netloc

def run(args: dict[str, str]):
    if get_secret("token"):
        print("Please logout first")
        return 1
            
    args["server"] = parse_server(server)
    set_config("server", args["server"])

    if args.get("token"):
        set_secret("token", args["token"])
        print("[green]✓[/green] Token saved.")
        return

    if args.get("username") and args.get("password"):
        body = {"username": args["username"], "password": args["password"]}
        if args.get("duration"):
            body["duration"] = args["duration"]
        resp = requests.post(f"https://{args['server']}/api/v1/auth/login/", json=body)
        if resp.status_code != 200:
            print(f"[red]✗[/red] Login failed: {resp.json().get('error', 'unknown error')}")
            return
        set_secret("token", resp.json()["token"])
        print(f"[green]✓[/green] Logged in as {args['username']}.")
        return

    resp = requests.post(f"https://{args['server']}/api/v1/auth/guest/")
    if resp.status_code != 200:
        print("[red]✗[/red] Could not create guest session.")
        return
    set_secret("token", resp.json()["token"])
    print("[green]✓[/green] Guest session started.")

cmd = register(Command(
    name="login",
    description="Authenticate.",
    args=(
        Arg("-s/--server", "drp server", required=True, default=server),
        Arg("-t/--token", "Authentication token"),
        Arg("username", "Username or email"),
        Arg("password", "Password"),
        Arg("-d/--duration", "Duration of the session (e.g. 7d, 2h)"),
    ),
    run=spin(run, "Contacting server")
))