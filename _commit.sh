#!/bin/bash
trap '' INT
cd /home/vic/Desktop/Code/Github/drp
git add -A
git diff --cached --stat
git commit -m "fix: render CLI docs from argparse instead of stripping template

The cli.html template is almost entirely {{ }} variables injected by
_get_parser_info(). Stripping template tags left the bot with an empty
skeleton. Now _cli_docs_as_text() renders real command names, flags,
and descriptions directly from the parser."
git push
echo "COMMIT_DONE"
rm -f /home/vic/Desktop/Code/Github/drp/_commit.sh
