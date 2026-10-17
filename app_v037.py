#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.7 — JSON-safe degraded fallback."""
from __future__ import annotations

import math
import threading
import webbrowser
from http.server import ThreadingHTTPServer

import app_v036 as base

APP_VERSION = "0.3.7"
HOST, PORT = base.HOST, base.PORT


def json_safe(value):
    """Recursively replace NaN/Infinity with JSON null.

    Python's float('nan') and infinities are useful internally, but the app's
    JSON encoder correctly rejects them. Degraded-mode unavailable metrics are
    represented as null instead.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    return value


class Handler(base.Handler):
    def send_json(self, obj, status=200):
        # Defensive boundary: no endpoint can leak NaN/Infinity to the browser.
        return super().send_json(json_safe(obj), status=status)

    def do_GET(self):
        # Keep all v0.3.6 routing/behavior; only update the displayed version.
        if self.path == "/":
            self.send_html(base.base.compare_base.core.ui.HOME_HTML.replace("v0.2 ·", "v0.3.7 ·"))
            return
        return super().do_GET()


def main():
    print(f"Loading Fantasy Decision Lab v{APP_VERSION}…", flush=True)
    base.base.compare_base.core.initialize()
    print(f"Fantasy Decision Lab: http://{HOST}:{PORT}", flush=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Timer(0.8, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
