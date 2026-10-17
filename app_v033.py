#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.3 — resilient player autocomplete."""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import app_v032 as base

APP_VERSION = "0.3.3"
HOST, PORT = base.HOST, base.PORT
LOCK = threading.Lock()
DIRECTORIES = {}


def directory_cache_path(position):
    return base.core.BACKEND_CACHE / "player_directories" / f"{position}.json"


def get_player_directory(position):
    """Load the player picker independently of the FantasyPros rankings API.

    Prefer an in-memory/model copy, then a lightweight local directory cache.
    Only if needed, refresh from the public FantasyPros rankings page. A failed
    public refresh never destroys the last-known-good directory.
    """
    if position in DIRECTORIES:
        return DIRECTORIES[position]

    model = base.core.STATE.get("position_models", {}).get(position)
    if model is not None and model.get("directory") is not None:
        DIRECTORIES[position] = model["directory"]
        return DIRECTORIES[position]

    path = directory_cache_path(position)
    if path.exists():
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            df = base.core.pd.DataFrame(rows)
            if not df.empty:
                DIRECTORIES[position] = df
                return df
        except Exception:
            pass

    try:
        df, _active_ids = base.core.legacy.load_position_directory(position)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(df.to_dict("records"), indent=2), encoding="utf-8")
        tmp.replace(path)
        DIRECTORIES[position] = df
        return df
    except Exception:
        # One final attempt to use a cache that may have been created by another
        # request/process while the live refresh was failing.
        if path.exists():
            rows = json.loads(path.read_text(encoding="utf-8"))
            df = base.core.pd.DataFrame(rows)
            if not df.empty:
                DIRECTORIES[position] = df
                return df
        raise


def players_payload(position, scoring):
    if position not in base.core.POSITIONS:
        raise ValueError("Choose QB, RB, WR, or TE.")
    scoring = base.core.norm_scoring(scoring)
    directory = get_player_directory(position)

    # Cached here means the rankings backend has at least one current group on
    # disk; autocomplete itself does not require that ranking cache to exist.
    rankings_cached = False
    model = base.core.STATE.get("position_models", {}).get(position)
    if model:
        ids = model.get("active_ids") or []
        first = ids[:base.core.GROUP_SIZE]
        if first:
            rankings_cached = base.core.group_path(position, scoring, first).exists()

    players = []
    for _, row in directory.sort_values("directory_rank", na_position="last").iterrows():
        players.append({
            "player": row.get("player"),
            "team": row.get("team"),
            "player_id": str(row.get("player_id")),
            "cached": rankings_cached,
        })
    return {
        "position": position,
        "scoring": scoring,
        "players": players,
        "cached_count": len(players) if rankings_cached else 0,
        "total_count": len(players),
    }


class Handler(base.Handler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(base.core.ui.HOME_HTML.replace("v0.2 ·", "v0.3.3 ·"))
            return
        if parsed.path == "/api/players":
            q = parse_qs(parsed.query)
            position = ((q.get("position") or ["WR"])[0]).upper()
            scoring = base.core.norm_scoring((q.get("scoring") or ["PPR"])[0])
            try:
                with LOCK:
                    self.send_json(players_payload(position, scoring))
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        return super().do_GET()


def main():
    print(f"Loading Fantasy Decision Lab v{APP_VERSION}…", flush=True)
    base.core.initialize()
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
