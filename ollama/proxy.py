#!/usr/bin/env python3
"""Lightweight auth-proxy for Ollama.

Sits between the public internet and Ollama, validates a shared
Bearer token, and forwards authenticated requests.  Health-check
on GET / is public so Railway (or any orchestrator) can probe it.

Env vars
--------
PORT           – listen port (Railway sets this automatically)
OLLAMA_API_KEY – shared secret; leave empty for open access (private networking)
OLLAMA_HOST    – backend address (default http://localhost:11434)
"""

import http.server
import json
import os
import sys
import urllib.error
import urllib.request
from socketserver import ThreadingMixIn

PORT = int(os.environ.get("PORT", 8080))
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
API_KEY = os.environ.get("OLLAMA_API_KEY", "")


class _Handler(http.server.BaseHTTPRequestHandler):
    """Minimal reverse-proxy with optional Bearer-token auth."""

    # ── auth ──────────────────────────────────────────────────

    def _authorised(self) -> bool:
        if not API_KEY:
            return True
        token = self.headers.get("Authorization", "")
        return token == f"Bearer {API_KEY}"

    def _reject(self):
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"unauthorized"}')

    # ── proxy core ────────────────────────────────────────────

    def _forward(self, method: str, *, public: bool = False):
        if not public and not self._authorised():
            return self._reject()

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else None

        url = f"{OLLAMA_HOST}{self.path}"
        req = urllib.request.Request(url, data=body, method=method)
        ctype = self.headers.get("Content-Type")
        if ctype:
            req.add_header("Content-Type", ctype)

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(e.read())

        except Exception as exc:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode())

    # ── HTTP verbs ────────────────────────────────────────────

    def do_GET(self):
        # Root = healthcheck, always public
        self._forward("GET", public=self.path in ("/", "/health"))

    def do_POST(self):
        self._forward("POST")

    def do_DELETE(self):
        self._forward("DELETE")

    # ── CORS pre-flight (for future browser-based use cases) ─

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    # ── logging ───────────────────────────────────────────────

    def log_message(self, fmt, *args):  # noqa: ARG002
        if len(args) >= 2:
            print(f"[proxy] {args[0]} → {args[1]}", flush=True)
        else:
            print(f"[proxy] {args[0]}", flush=True)


class _ThreadingServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    auth = "enabled" if API_KEY else "disabled (open)"
    print(f"proxy :{PORT} → {OLLAMA_HOST}  auth={auth}", flush=True)
    _ThreadingServer(("0.0.0.0", PORT), _Handler).serve_forever()
