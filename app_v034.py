#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.4 — API outage fallback to legacy cached ballots."""
from __future__ import annotations

import threading
import webbrowser
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import app as legacy
import app_v02 as ui2
import app_v032 as current

APP_VERSION = "0.3.4"
HOST, PORT = current.HOST, current.PORT
LOCK = threading.Lock()

LEGACY_READY = {}


def _prepare_legacy(position: str, scoring: str):
    """Build legacy state strictly from local compare caches + public directory."""
    key = (position, scoring)
    if LEGACY_READY.get(key):
        return
    legacy.SCORING = scoring
    # Reuse v0.2's scoring-aware ballot parser so STD/PPR both work.
    legacy.collect_ballots = ui2.collect_ballots
    if legacy.STATE.get("current_accuracy") is None:
        legacy.STATE["current_accuracy"] = legacy.read_accuracy(2026)
    if legacy.STATE.get("prior_accuracy") is None:
        legacy.STATE["prior_accuracy"] = legacy.read_accuracy(2025)
    legacy.rebuild_position_state(position)
    LEGACY_READY[key] = True


def legacy_cached_compare(position: str, scoring: str, a_name: str, b_name: str):
    _prepare_legacy(position, scoring)
    st = legacy.STATE["positions"][position]
    a = legacy.resolve_player(a_name, st["directory"])
    b = legacy.resolve_player(b_name, st["directory"])
    aid, bid = str(a["player_id"]), str(b["player_id"])
    ballots = st.get("ballots") or {}
    if aid not in ballots or bid not in ballots:
        missing = []
        if aid not in ballots: missing.append(a["player"])
        if bid not in ballots: missing.append(b["player"])
        raise RuntimeError(
            "FantasyPros is currently unavailable, and the local backup does not yet have cached expert ballots for "
            + " and ".join(missing)
            + ". Previously-seen players can still be compared until FantasyPros recovers."
        )
    result = legacy.compare(position, a_name, b_name)
    result["scoring"] = "STD" if position == "QB" else scoring
    result["warning"] = "FantasyPros live API is unavailable — using the last known-good local per-expert ballot cache."
    result["source_note"] = (
        result.get("source_note", "")
        + " Live FantasyPros rankings were unavailable, so this result was computed from locally cached per-expert ballots from earlier successful API responses."
    )
    return result


def resilient_compare(position: str, scoring: str, a_name: str, b_name: str):
    try:
        return current.core.compare(position, scoring, a_name, b_name)
    except Exception as live_exc:
        msg = str(live_exc)
        transient = any(x in msg for x in ("temporarily unavailable", "HTTP 502", "HTTP 503", "HTTP 504", "after retries"))
        if not transient:
            raise
        try:
            return legacy_cached_compare(position, scoring, a_name, b_name)
        except Exception as cache_exc:
            # Preserve the more actionable offline/cache explanation.
            raise RuntimeError(str(cache_exc)) from live_exc


def start_sit_html():
    h = current.start_sit_html()
    h = h.replace("$('status').textContent=j.warning||'Comparison complete';", "$('status').textContent=j.warning||'Comparison complete';")
    return h


class Handler(current.Handler):
    def send_html(self, h):
        data = h.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(current.core.ui.HOME_HTML.replace("v0.2 ·", "v0.3.4 ·"))
            return
        if parsed.path == "/start-sit":
            self.send_html(start_sit_html())
            return
        if parsed.path == "/api/compare":
            q = parse_qs(parsed.query)
            position = ((q.get("position") or ["WR"])[0]).upper()
            scoring = current.core.norm_scoring((q.get("scoring") or ["PPR"])[0])
            try:
                with LOCK:
                    result = resilient_compare(
                        position, scoring,
                        (q.get("a") or [""])[0],
                        (q.get("b") or [""])[0],
                    )
                self.send_json(result)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        return super().do_GET()


def main():
    print(f"Loading Fantasy Decision Lab v{APP_VERSION}…", flush=True)
    current.core.initialize()
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
