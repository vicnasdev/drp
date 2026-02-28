"""
cli/commands/outside/ping.py
"""
from __future__ import annotations
from cli.base import SpinnerCommand
from cli.api import APIClient
from cli.api.auth import ping as api_ping


class PingCommand(SpinnerCommand):
    name        = "ping"
    description = "Check connectivity to the drp server"

    def run(self, args: list[str]) -> int:
        client = APIClient.from_config(self.config)
        with self.spin(f"Pinging {self.server_url}"):
            result = api_ping(client)
        self.success(f"  {self.server_url}  {result.get('version', '')}  {result.get('latency_ms', '')}ms")
        return 0
