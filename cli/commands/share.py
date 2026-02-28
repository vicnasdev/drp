"""
cli/commands/shell/share.py

Manage share tokens for the current folder or a specific file.

  share                          # share cwd folder
  share myfile.py                # share a specific file
  share --write                  # with write access
  share --expires 7d
  share --group devs
  share list [file]
  share revoke <id>
"""
from __future__ import annotations
import argparse
from cli.base import SpinnerCommand, AuthCommand
from cli.api import APIClient, share as share_api, folders as folders_api
from cli.base.errors import DrpError


class ShareCommand(SpinnerCommand, AuthCommand):
    name        = "share"
    description = "Manage share tokens for folders and files"

    def run(self, args: list[str]) -> int:
        self.require_auth()

        if args and args[0] == "list":
            return self._list(args[1:])
        if args and args[0] == "revoke":
            return self._revoke(args[1:])

        return self._create(args)

    # ---------------------------------------------------------------- create

    def _create(self, args: list[str]) -> int:
        p = argparse.ArgumentParser(prog="share", add_help=False)
        p.add_argument("target",    nargs="?", default=None)
        p.add_argument("--write",   action="store_true")
        p.add_argument("--admin",   action="store_true")
        p.add_argument("--expires", default=None)
        p.add_argument("--group",   default=None)
        opts   = p.parse_args(args)
        client = APIClient.from_config(self.config, authed=True)

        role      = "admin" if opts.admin else "writer" if opts.write else "reader"
        folder_id = _resolve_folder(client, opts.target, self.config)
        group_id  = _resolve_group(client, opts.group) if opts.group else None

        with self.spin("Creating share token"):
            result = share_api.create(
                client, folder_id,
                role=role, expires=opts.expires, group_id=group_id,
            )

        self.success("share link created:")
        self.out(f"  {result['url']}")
        self.dim(f"  role: {role}  expires: {opts.expires or 'default'}")
        return 0

    # ---------------------------------------------------------------- list

    def _list(self, args: list[str]) -> int:
        p = argparse.ArgumentParser(prog="share list", add_help=False)
        p.add_argument("target", nargs="?", default=None)
        opts      = p.parse_args(args)
        client    = APIClient.from_config(self.config, authed=True)
        folder_id = _resolve_folder(client, opts.target, self.config)

        tokens = share_api.list_for_folder(client, folder_id)
        if not tokens:
            self.dim("no share tokens for this folder")
            return 0
        self.print_table(tokens, ["id", "role", "expires_at", "created_at"])
        return 0

    # ---------------------------------------------------------------- revoke

    def _revoke(self, args: list[str]) -> int:
        if not args:
            self.err("usage: share revoke <id>")
            return 1
        client = APIClient.from_config(self.config, authed=True)
        with self.spin("Revoking"):
            share_api.revoke(client, int(args[0]))
        self.success("token revoked")
        return 0


# ------------------------------------------------------------------ helpers

def _resolve_folder(client, target: str | None, config: dict) -> int:
    if target:
        obj = folders_api.resolve_path(client, target)
        if obj["type"] != "folder":
            raise DrpError(f"'{target}' is not a folder")
        return obj["object"]["id"]
    folder_id = config.get("shell", {}).get("cwd_id")
    if not folder_id:
        raise DrpError("not inside a folder — cd into one first, or specify a target")
    return folder_id


def _resolve_group(client, name: str) -> int:
    from cli.api import APIClient
    from cli.base.errors import parse_response
    result = parse_response(client.get("/api/v1/groups/", params={"name": name}))
    groups = result.get("results", [])
    if not groups:
        raise DrpError(f"group '{name}' not found")
    return groups[0]["id"]
