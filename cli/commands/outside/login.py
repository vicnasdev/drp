"""
cli/commands/outside/login.py
"""
from __future__ import annotations
import argparse
import getpass
from cli.base import SpinnerCommand
from cli.api import APIClient
from cli.api.auth import login_password, login_token
from cli import config as cfg


class LoginCommand(SpinnerCommand):
    name        = "login"
    description = "Authenticate with drp"

    def run(self, args: list[str]) -> int:
        opts   = _parse(args)
        conf   = cfg.load()
        client = APIClient.from_config(conf)

        if opts.token:
            with self.spin("Verifying token"):
                result = login_token(client, opts.token)
            cfg.set_auth(result["username"], opts.token)
            self.success(f"logged in as {result['username']}")
            return 0

        username = input("username: ").strip()
        password = getpass.getpass("password: ")
        with self.spin("Logging in"):
            result = login_password(client, username, password)
        cfg.set_auth(result["username"], result["token"])
        self.success(f"logged in as {result['username']}")
        return 0


def _parse(args):
    p = argparse.ArgumentParser(prog="login", add_help=False)
    p.add_argument("--token",   default=None)
    p.add_argument("--browser", action="store_true")
    return p.parse_args(args)
