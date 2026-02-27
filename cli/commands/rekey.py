"""
drp rekey — change a drop's URL key.

  drp rekey <old-key> <new-key>        rename a drop's key

This is an alias for `drp mv` but makes the intent clearer:
the drop keeps its content, only the URL changes.
"""

import sys

from cli.commands._context import load_context
from cli.commands.manage import cmd_mv


def cmd_rekey(args):
    """Rekey is just mv with clearer intent."""
    cmd_mv(args)
