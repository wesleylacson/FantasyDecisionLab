#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.2 — transactional refresh + last-known-good fallback."""
from __future__ import annotations

import json
import os
import threading
import webbrowser
from datetime import datetime
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import app_v03 as core

APP_VERSION = "0.3.2"
HOST, PORT = core.HOST, core.PORT
LOCK = threading.Lock()

# A manual position/all refresh marks data for replacement on next use instead
# of deleting good cache files. This keeps the app usable during FP outages.
FORCE_NEXT = set()
REFRESH_STATE = {"outage": None, "used_stale": False}


def reset_refresh_state():
    REFRESH_STATE["outage"] = None
    REFRESH_STATE["used_stale"] = False


def transactional_fetch_group(position, scoring, expert_ids, force=False):
    """Fetch into a temp file and replace cache only after success.

    During a forced refresh, if FantasyPros is unavailable and a prior cache
    exists, return that last-known-good payload rather than failing/deleting it.
    A small circuit breaker prevents one outage from causing retries per group.
    """
    path = core.group_path(position, scoring, expert_ids)
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))

    # Once one forced request establishes an outage, immediately reuse any
    # remaining cached groups during this operation instead of hammering FP.
    if force and REFRESH_STATE["outage"] and path.exists():
        REFRESH_STATE["used_stale"] = True
        return json.loads(path.read_text(encoding="utf-8"))

    params = {
        "position": position,
        "scoring": "STD" if position == "QB" else scoring,
        "week": core.WEEK,
        "filters": ":".join(expert_ids),
        "experts": "show",
    }
    try:
        data = core.api_get(core.CONSENSUS_URL, params)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return data
    except Exception as exc:
        if force and path.exists():
            REFRESH_STATE["outage"] = str(exc)
            REFRESH_STATE["used_stale"] = True
            return json.loads(path.read_text(encoding="utf-8"))
        raise


# core.compare resolves core.fetch_group dynamically, so this safely upgrades
# both ordinary and forced comparisons without duplicating the model logic.
core.fetch_group = transactional_fetch_group


def warning_text():
    if REFRESH_STATE["used_stale"]:
        return "FantasyPros unavailable — kept and used the last known-good cached rankings."
    return None


def start_sit_html():
    h = core.ui.start_sit_html()
    # Surface fallback notices instead of overwriting them with generic success.
    h = h.replace("$('status').textContent='Comparison complete';", "$('status').textContent=j.warning||'Comparison complete';")
    h = h.replace("$('status').textContent='Current matchup refreshed';", "$('status').textContent=j.warning||'Current matchup refreshed';")
    # Position/all refresh no longer destructively clears cache; update wording.
    h = h.replace("Clear cached ${position} ballots? Fresh ballots will be fetched on demand.", "Mark ${position} data for a fresh replacement? Existing cache will be kept until that succeeds.")
    h = h.replace("Clear all cached QB/RB/WR/TE ballots? Fresh ballots will be fetched on demand.", "Mark all Start/Sit data for refresh? Existing caches will be kept until fresh replacements succeed.")
    return h


class Handler(core.Handler):
    def send_html(self, h):
        data = h.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/refresh":
            return super().do_POST()
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n).decode() or "{}")
            scope = str(body.get("scope") or "").lower()
            position = str(body.get("position") or "WR").upper()
            scoring = core.norm_scoring(body.get("scoring"))
            reset_refresh_state()

            with LOCK:
                if scope == "matchup":
                    result = core.compare(
                        position, scoring,
                        str(body.get("a") or ""), str(body.get("b") or ""),
                        force=True,
                    )
                    result = {
                        "scope": scope,
                        "position": position,
                        "scoring": scoring,
                        "refreshed_at": result.get("last_refreshed"),
                        "warning": warning_text(),
                    }
                elif scope == "position":
                    # Do not delete files. Force one safe replacement attempt on
                    # the next comparison for this position/scoring combination.
                    FORCE_NEXT.add((position, scoring))
                    result = {
                        "scope": scope,
                        "position": position,
                        "scoring": scoring,
                        "refreshed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                        "warning": "Refresh queued — existing cached rankings are being kept until a fresh replacement succeeds.",
                    }
                elif scope == "all":
                    for p in core.POSITIONS:
                        for s in ("PPR", "STD"):
                            FORCE_NEXT.add((p, s))
                    result = {
                        "scope": scope,
                        "refreshed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                        "warning": "All Start/Sit data is queued for safe refresh; no existing cache was deleted.",
                    }
                else:
                    raise ValueError("Refresh scope must be matchup, position, or all.")
            self.send_json(result)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(core.ui.HOME_HTML.replace("v0.2 ·", "v0.3.2 ·"))
            return
        if parsed.path == "/start-sit":
            self.send_html(start_sit_html())
            return
        if parsed.path == "/api/compare":
            q = parse_qs(parsed.query)
            position = ((q.get("position") or ["WR"])[0]).upper()
            scoring = core.norm_scoring((q.get("scoring") or ["PPR"])[0])
            key = (position, scoring)
            reset_refresh_state()
            try:
                with LOCK:
                    result = core.compare(
                        position, scoring,
                        (q.get("a") or [""])[0],
                        (q.get("b") or [""])[0],
                        force=key in FORCE_NEXT,
                    )
                    warn = warning_text()
                    if key in FORCE_NEXT and not warn:
                        FORCE_NEXT.discard(key)
                    if warn:
                        result["warning"] = warn
                self.send_json(result)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        return super().do_GET()


def main():
    print(f"Loading Fantasy Decision Lab v{APP_VERSION}…", flush=True)
    core.initialize()
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
