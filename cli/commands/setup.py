"""
cli/commands/outside/setup.py

First-run interactive wizard.
Sets server URL, authenticates, configures shell completion and color prefs.
"""
from __future__ import annotations
import subprocess
import sys
from cli.base import BaseCommand
from cli.api import APIClient
from cli.api.auth import login_password, ping
from cli.base.errors import NetworkError
from cli import config as cfg


class SetupCommand(BaseCommand):
    name        = "setup"
    description = "First-run setup wizard"

    def run(self, args: list[str]) -> int:
        self.out()
        self.info("drp setup")
        self.dim("─" * 40)
        self.out()

        conf = cfg.load()

        # server URL
        current = conf.get("server", {}).get("url", "https://drp.fyi")
        self.out(f"Server URL [{current}]: ", end="")  # type: ignore[call-arg]
        url = input("").strip() or current
        cfg.set_server(url)
        self.out()

        # verify reachable
        client = APIClient(url)
        try:
            ping(client)
            self.success(f"connected to {url}")
        except NetworkError:
            self.warn(f"could not reach {url} — saved anyway, check later")
        self.out()

        # auth
        self.out("Login (leave blank to skip): ")
        username = input("  username: ").strip()
        if username:
            import getpass
            password = getpass.getpass("  password: ")
            try:
                result = login_password(client, username, password)
                cfg.set_auth(result["username"], result["token"])
                self.success(f"logged in as {result['username']}")
            except Exception as e:
                self.warn(f"login failed: {e} — run: drp login later")
        self.out()

        # color pref
        color_input = input("Enable color? [Y/n]: ").strip().lower()
        color = color_input not in ("n", "no")
        conf  = cfg.load()
        conf.setdefault("prefs", {})["color"] = color
        cfg.save(conf)

        # shell completion
        self.out()
        self.dim("To enable tab completion, add to your shell profile:")
        shell = _detect_shell()
        if shell == "bash":
            self.dim('  eval "$(drp --completion bash)"')
        elif shell == "zsh":
            self.dim('  eval "$(drp --completion zsh)"')
        else:
            self.dim('  eval "$(drp --completion <bash|zsh|fish>)"')

        self.out()
        self.success("setup complete — run: drp up <file>")
        return 0


def _detect_shell() -> str:
    import os
    shell = os.environ.get("SHELL", "")
    if "zsh" in shell:
        return "zsh"
    if "fish" in shell:
        return "fish"
    return "bash"
