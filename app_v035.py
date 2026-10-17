#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.5 — resilient autocomplete + offline compare fallback."""
from __future__ import annotations

import threading
import webbrowser
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import app as legacy
import app_v02 as ui2
import app_v032 as compare_base
import app_v033 as picker_base

APP_VERSION = "0.3.5"
HOST, PORT = picker_base.HOST, picker_base.PORT
LOCK = threading.Lock()
LEGACY_READY = {}


def _prepare_legacy(position: str, scoring: str):
    key = (position, scoring)
    if LEGACY_READY.get(key):
        return
    legacy.SCORING = scoring
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
        if aid not in ballots:
            missing.append(a["player"])
        if bid not in ballots:
            missing.append(b["player"])
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
        return compare_base.core.compare(position, scoring, a_name, b_name)
    except Exception as live_exc:
        msg = str(live_exc)
        transient = any(x in msg for x in (
            "temporarily unavailable", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "after retries"
        ))
        if not transient:
            raise
        try:
            return legacy_cached_compare(position, scoring, a_name, b_name)
        except Exception as cache_exc:
            raise RuntimeError(str(cache_exc)) from live_exc


def start_sit_html():
    # Keep v0.3.2's non-destructive refresh UX and v0.3.3's player picker route.
    return compare_base.start_sit_html()


class Handler(picker_base.Handler):
    """Important: inherit from v0.3.3 so /api/players stays API-independent."""

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
            self.send_html(compare_base.core.ui.HOME_HTML.replace("v0.2 ·", "v0.3.5 ·"))
            return
        if parsed.path == "/start-sit":
            self.send_html(start_sit_html())
            return
        if parsed.path == "/api/compare":
            q = parse_qs(parsed.query)
            position = ((q.get("position") or ["WR"])[0]).upper()
            scoring = compare_base.core.norm_scoring((q.get("scoring") or ["PPR"])[0])
            try:
                with LOCK:
                    result = resilient_compare(
                        position,
                        scoring,
                        (q.get("a") or [""])[0],
                        (q.get("b") or [""])[0],
                    )
                self.send_json(result)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        # /api/players deliberately falls through to app_v033.Handler,
        # preserving the local/public-directory autocomplete implementation.
        return super().do_GET()


def main():
    print(f"Loading Fantasy Decision Lab v{APP_VERSION}…", flush=True)
    compare_base.core.initialize()
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
