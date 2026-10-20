#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.17 — wire Weekly Projection into home navigation."""
from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import app_v0316 as prev

APP_VERSION = "0.3.17"
ns = prev.ns
ns["APP_VERSION"] = APP_VERSION

fp038 = ns["base"]
fp035 = fp038.base.base.base

ROOT = Path(__file__).resolve().parent
PROJECTION_PORT = 8766
PROJECTION_URL = f"http://127.0.0.1:{PROJECTION_PORT}"


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def _start_projection_workbench() -> None:
    if _port_open(PROJECTION_PORT):
        return
    env = os.environ.copy()
    key_file = Path.home() / ".fantasy_decision_lab" / "openai_api_key"
    if not env.get("OPENAI_API_KEY") and key_file.exists():
        env["OPENAI_API_KEY"] = key_file.read_text(encoding="utf-8").strip()
    # The main navigation already owns the browser transition, so suppress the
    # workbench's standalone auto-open behavior when it is launched from here.
    env["FANTASY_PROJECTION_NO_BROWSER"] = "1"
    python_bin = ROOT / ".venv" / "bin" / "python"
    if not python_bin.exists():
        python_bin = Path("python3")
    log_path = ROOT / "projection_workbench.log"
    with log_path.open("a", encoding="utf-8") as log:
        subprocess.Popen(
            [str(python_bin), str(ROOT / "projection_workbench_app.py")],
            cwd=str(ROOT),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    for _ in range(30):
        if _port_open(PROJECTION_PORT):
            return
        time.sleep(0.1)
    raise RuntimeError("Projection Workbench did not start on port 8766.")


def home_html_v317() -> str:
    h = fp035.compare_base.core.ui.HOME_HTML.replace("v0.2 ·", "v0.3.17 ·")
    old = '<div class="module dead"><div class="icon">📈</div><h3>Weekly Projection</h3><p>Our projection workflow, matchup layers, and app-comparison tracker.</p></div>'
    new = '<a class="module live" href="/weekly-projection"><div class="icon">📈</div><h3><span class="dot"></span>Weekly Projection</h3><p>Our projection workflow, matchup layers, and app-comparison tracker.</p></a>'
    if old not in h:
        raise RuntimeError("Could not find Weekly Projection home tile to wire in v0.3.17")
    return h.replace(old, new, 1)


OldHandler = ns["Handler"]


class Handler(OldHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(home_html_v317())
            return
        if parsed.path == "/weekly-projection":
            try:
                _start_projection_workbench()
            except Exception as exc:
                self.send_response(500)
                data = f"Could not start Projection Workbench: {exc}".encode("utf-8")
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(302)
            self.send_header("Location", PROJECTION_URL)
            self.end_headers()
            return
        return super().do_GET()


ns["Handler"] = Handler

if __name__ == "__main__":
    ns["main"]()
