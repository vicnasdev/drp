"""
cli/commands/token.py

drp token create [--expires 90d] [--label mykey]
drp token list
drp token revoke <id>
"""

import json
import sys

from cli.api.auth import get_csrf
from cli.commands._context import load_context


def cmd_token(args):
    action = getattr(args, "token_action", None)
    if action == "create":
        _create(args)
    elif action == "list":
        _list(args)
    elif action == "revoke":
        _revoke(args)
    else:
        print("Usage: drp token {create|list|revoke}")
        sys.exit(1)


def _create(args):
    cfg, host, session = load_context()
    csrf = get_csrf(host, session)

    payload = {}
    label = getattr(args, "label", None)
    expires = getattr(args, "expires", None)
    if label:
        payload["label"] = label
    if expires:
        payload["expires"] = expires

    from cli.spinner import Spinner
    with Spinner('creating'):
        res = session.post(
            f"{host}/auth/tokens/create/",
            json=payload,
            headers={"X-CSRFToken": csrf, "Referer": f"{host}/"},
            timeout=15,
        )

    if not res.ok:
        try:
            print(f"  ✗ {res.json().get('error', res.text)}")
        except Exception:
            print(f"  ✗ Failed ({res.status_code})")
        sys.exit(1)

    data = res.json()
    print(f"  Token: {data['token']}")
    print(f"  Prefix: {data['prefix']}...")
    if data.get("label"):
        print(f"  Label: {data['label']}")
    if data.get("expires_at"):
        print(f"  Expires: {data['expires_at']}")
    print()
    print("  Save this token now — it won't be shown again.")
    print("  Use it with: DRP_API_KEY=<token> drp up file.py")


def _list(args):
    cfg, host, session = load_context()

    from cli.spinner import Spinner
    with Spinner('loading'):
        res = session.get(
            f"{host}/auth/tokens/",
            headers={"Accept": "application/json"},
            timeout=15,
        )

    if not res.ok:
        try:
            print(f"  ✗ {res.json().get('error', res.text)}")
        except Exception:
            print(f"  ✗ Failed ({res.status_code})")
        sys.exit(1)

    tokens = res.json().get("tokens", [])
    if not tokens:
        print("  No API tokens.")
        return

    for t in tokens:
        status = " (expired)" if t.get("expired") else ""
        label = f" — {t['label']}" if t.get("label") else ""
        last = f", last used {t['last_used']}" if t.get("last_used") else ""
        print(f"  [{t['id']}] {t['prefix']}...{label}{status}{last}")


def _revoke(args):
    token_id = getattr(args, "token_id", None)
    if not token_id:
        print("  ✗ Token ID required. Run `drp token list` to see IDs.")
        sys.exit(1)

    cfg, host, session = load_context()
    csrf = get_csrf(host, session)

    from cli.spinner import Spinner
    with Spinner('revoking'):
        res = session.post(
            f"{host}/auth/tokens/{token_id}/revoke/",
            headers={"X-CSRFToken": csrf, "Referer": f"{host}/"},
            timeout=15,
        )

    if not res.ok:
        try:
            print(f"  ✗ {res.json().get('error', res.text)}")
        except Exception:
            print(f"  ✗ Failed ({res.status_code})")
        sys.exit(1)

    print("  Token revoked.")
