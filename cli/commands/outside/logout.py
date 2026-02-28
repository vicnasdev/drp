"""
cli/commands/outside/logout.py
"""
from __future__ import annotations
from cli.base import BaseCommand, AuthCommand
from cli.api import APIClient
from cli.api import auth as auth_api
from cli import config as cfg


class LogoutCommand(BaseCommand, AuthCommand):
    name        = "logout"
    description = "Log out and clear local credentials"

    def run(self, args: list[str]) -> int:
        self.require_auth()
        client = APIClient.from_config(self.config, authed=True)
        try:
            auth_api.logout(client)
        except Exception:
            pass  # clear locally regardless
        cfg.clear_auth()
        self.success("logged out")
        return 0
