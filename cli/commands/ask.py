"""
drp ask — ask the help bot a question about drp.

  drp ask "how do I upload a file?"
  drp ask                          (prompts interactively)
  drp ask --clear                  clear conversation history
"""

import re
import sys

from cli.commands._context import load_context


# ── Command ───────────────────────────────────────────────────────────────────

def cmd_ask(args):
    cfg, host, session = load_context(require_login=True)

    # Handle --clear (server-side)
    if getattr(args, 'clear', False):
        try:
            session.delete(f"{host}/help/ask/history/", timeout=15)
        except Exception:
            pass
        print('  ✓ Help bot history cleared.')
        return

    question = getattr(args, "question", None)
    if not question:
        try:
            question = input("  ? ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

    if not question:
        return

    url = f"{host}/help/ask/"
    try:
        from cli.spinner import Spinner
        with Spinner('thinking'):
            resp = session.post(url, json={"question": question}, timeout=120)
    except Exception as exc:
        print(f"  ✗ Network error: {exc}")
        sys.exit(1)

    if resp.status_code == 429:
        print("  ✗ Hourly limit reached — try again later.")
        sys.exit(1)

    if resp.status_code == 403:
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        print(f"  ✗ {data.get('error', 'Access denied.')}")
        sys.exit(1)

    if resp.status_code == 503:
        print("  ✗ Help bot is not available on this server.")
        sys.exit(1)

    if resp.status_code != 200:
        print(f"  ✗ Server returned {resp.status_code}")
        sys.exit(1)

    data = resp.json()
    answer_html = data.get("answer", "")

    # Strip HTML tags for terminal display
    text = re.sub(r"<[^>]+>", "", answer_html)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&#x27;", "'").replace("&quot;", '"')
    text = text.strip()

    if text:
        for line in text.splitlines():
            print(f"  {line}")
    else:
        print("  No answer returned.")
