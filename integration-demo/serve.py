#!/usr/bin/env python3
"""Static file server for the Kirana Mart integration demo.

Python standard library ONLY — no pip install, no requirements.txt, and (the
whole point of this demo) no AI/LLM package of any kind. It does exactly two
things:

  1. serves index.html / app.js / styles.css from this directory
  2. reverse-proxies /api/* and /health to the merchant platform backend

(2) exists purely because of CORS. The backend allows exactly one browser
origin, `settings.frontend_url` (http://127.0.0.1:3000 by default), and a
demo served on any other port gets "Disallowed CORS origin" on the preflight.
Proxying makes every call same-origin from the browser's point of view, so
CORS never enters the picture and this demo can run on any free port without
touching the backend's configuration.

If you would rather not run a proxy at all, see README.md: serve the folder
with `python -m http.server 3000 --bind 127.0.0.1` while the main Next.js
frontend is stopped, and the page will call http://127.0.0.1:8842 directly —
that origin is already on the backend's allowlist.

Usage:
    python serve.py                       # http://127.0.0.1:3000
    python serve.py --port 3100
    python serve.py --backend http://127.0.0.1:8842
"""

import argparse
import sys
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROXY_PREFIXES = ("/api/", "/health", "/.well-known/")

# Agent chat is a real multi-step LLM run on the platform side and can take a
# minute or more; a short timeout here would look like a demo bug.
PROXY_TIMEOUT_SECONDS = 300

# Hop-by-hop headers must not be forwarded (RFC 7230 §6.1).
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}


class DemoHandler(SimpleHTTPRequestHandler):
    backend = "http://127.0.0.1:8842"

    def _is_proxied(self) -> bool:
        return self.path.startswith(PROXY_PREFIXES)

    # --- proxy ------------------------------------------------------------
    def _proxy(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        req = urllib.request.Request(self.backend + self.path, data=body, method=self.command)
        for name, value in self.headers.items():
            if name.lower() not in _HOP_BY_HOP:
                req.add_header(name, value)  # X-Agent-Key rides through untouched

        try:
            with urllib.request.urlopen(req, timeout=PROXY_TIMEOUT_SECONDS) as upstream:
                self._relay(upstream.status, upstream.headers, upstream.read())
        except urllib.error.HTTPError as e:
            # A 4xx/5xx from the platform is a real answer the page must see
            # (401 for a bad key, 403 for an agent hitting a buyer endpoint) —
            # relay it verbatim rather than turning it into a proxy error.
            self._relay(e.code, e.headers, e.read())
        except Exception as e:  # noqa: BLE001 - connection refused, DNS, timeout
            msg = f'{{"detail":"Demo proxy could not reach {self.backend}: {type(e).__name__}: {e}"}}'
            self._relay(502, {"Content-Type": "application/json"}, msg.encode())

    def _relay(self, status, headers, payload: bytes) -> None:
        self.send_response(status)
        for name, value in (headers.items() if hasattr(headers, "items") else headers):
            if name.lower() not in _HOP_BY_HOP and name.lower() != "content-length":
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    # --- routing ----------------------------------------------------------
    def do_GET(self):
        self._proxy() if self._is_proxied() else super().do_GET()

    def do_HEAD(self):
        self._proxy() if self._is_proxied() else super().do_HEAD()

    def do_POST(self):
        if self._is_proxied():
            self._proxy()
        else:
            self.send_error(405, "This demo server only accepts POST on proxied /api/* paths.")

    def end_headers(self):
        # Static assets only; the demo is edited live during a walkthrough.
        if not self._is_proxied():
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=3000)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--backend", default="http://127.0.0.1:8842")
    args = p.parse_args()

    DemoHandler.backend = args.backend.rstrip("/")
    handler = partial(DemoHandler, directory=str(HERE))

    try:
        httpd = ThreadingHTTPServer((args.host, args.port), handler)
    except OSError as e:
        print(f"Cannot bind {args.host}:{args.port} — {e}", file=sys.stderr)
        print("Something else is already listening there (the main Next.js frontend uses 3000).", file=sys.stderr)
        print("Try:  python serve.py --port 3100", file=sys.stderr)
        return 1

    print("Kirana Mart integration demo")
    print(f"  page     http://{args.host}:{args.port}/")
    print(f"  proxying {', '.join(PROXY_PREFIXES)} -> {DemoHandler.backend}")
    print("  no AI dependency in this process: stdlib only")
    print("Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
