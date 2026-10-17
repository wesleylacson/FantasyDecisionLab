#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.6 — three-tier Start/Sit fallback."""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import app as legacy
import app_v035 as base

APP_VERSION = "0.3.6"
HOST, PORT = base.HOST, base.PORT
LOCK = threading.Lock()
PUBLIC_DIRS = {}


def public_dir_cache_path(position: str, scoring: str):
    return base.compare_base.core.BACKEND_CACHE / "public_ecr" / scoring / f"{position}.json"


def get_public_directory(position: str, scoring: str):
    """Get scoring-aware public-page ECR without touching the FantasyPros API."""
    key = (position, scoring)
    if key in PUBLIC_DIRS:
        return PUBLIC_DIRS[key]

    path = public_dir_cache_path(position, scoring)
    try:
        legacy.SCORING = "STD" if position == "QB" else scoring
        df, _active = legacy.load_position_directory(position)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(df.to_dict("records"), indent=2), encoding="utf-8")
        tmp.replace(path)
        PUBLIC_DIRS[key] = df
        return df
    except Exception:
        if path.exists():
            rows = json.loads(path.read_text(encoding="utf-8"))
            df = base.picker_base.base.core.pd.DataFrame(rows)
            if not df.empty:
                PUBLIC_DIRS[key] = df
                return df
        # Fall back to the autocomplete directory as a final local source.
        df = base.picker_base.get_player_directory(position)
        PUBLIC_DIRS[key] = df
        return df


def magnitude_label(gap: float) -> str:
    if gap < 0.35:
        return "TINY"
    if gap < 1.0:
        return "SMALL"
    if gap < 2.5:
        return "MEANINGFUL"
    return "LARGE"


def public_ecr_compare(position: str, scoring: str, a_name: str, b_name: str):
    directory = get_public_directory(position, scoring)
    a = legacy.resolve_player(a_name, directory)
    b = legacy.resolve_player(b_name, directory)
    ar = a.get("directory_rank")
    br = b.get("directory_rank")
    if ar is None or br is None:
        raise RuntimeError("Public FantasyPros rankings did not include a usable ECR rank for one or both selected players.")
    ar, br = float(ar), float(br)
    winner = a if ar <= br else b
    gap = abs(ar - br)
    panel = {
        "name": "Public ECR",
        "available": True,
        "experts": 0,
        "weighted": False,
        "a_avg_rank": ar,
        "b_avg_rank": br,
        "a_vote_share": 0.5,
        "b_vote_share": 0.5,
        "winner": "A" if ar <= br else "B",
        "rank_gap": gap,
    }
    unavailable = lambda name: {"name": name, "experts": 0, "available": False}
    return {
        "position": position,
        "scoring": "STD" if position == "QB" else scoring,
        "player_a": a["player"], "team_a": a.get("team"),
        "player_b": b["player"], "team_b": b.get("team"),
        "recommendation": winner["player"],
        "confidence": "DEGRADED",
        "experts_used": 0,
        "a_weighted_avg_rank": ar, "b_weighted_avg_rank": br,
        "a_unweighted_avg_rank": ar, "b_unweighted_avg_rank": br,
        "a_weighted_vote_share": 0.5, "b_weighted_vote_share": 0.5,
        "a_unweighted_vote_share": 0.5, "b_unweighted_vote_share": 0.5,
        "weighted_rank_gap": gap,
        "weighted_std_expert_margin": float("nan"),
        "directional_signal": "UNAVAILABLE",
        "magnitude_signal": magnitude_label(gap),
        "agreement_signal": "UNAVAILABLE",
        "margin_stability_ratio": float("nan"),
        "evidence_score": 0.0,
        "panels": [panel, unavailable("Weighted full"), unavailable("Elite 15"), unavailable("Elite 10"), unavailable("Elite 5")],
        "elite_experts": [],
        "why": "FantasyPros' API is unavailable and these players are not in the local expert-ballot cache, so this is a degraded recommendation using only the public-page consensus rank. Elite-panel and confidence signals are intentionally withheld.",
        "last_refreshed": None,
        "warning": "FantasyPros API unavailable — using public-page ECR only. Elite panels and model confidence are unavailable for this matchup.",
        "source_note": "Emergency fallback: public FantasyPros weekly ranking-page ECR only. This is not the normal Rank-the-Rankers model and should be treated as a temporary consensus-only result until the API recovers.",
        "degraded": True,
    }


def resilient_compare(position: str, scoring: str, a_name: str, b_name: str):
    # Tier 1: current live grouped rankings backend.
    try:
        return base.compare_base.core.compare(position, scoring, a_name, b_name)
    except Exception as live_exc:
        msg = str(live_exc)
        transient = any(x in msg for x in (
            "temporarily unavailable", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "after retries"
        ))
        if not transient:
            raise

        # Tier 2: exact locally cached per-expert ballots from the original backend.
        try:
            return base.legacy_cached_compare(position, scoring, a_name, b_name)
        except Exception:
            # Tier 3: public-page consensus ECR. Never manufacture elite-panel data.
            try:
                return public_ecr_compare(position, scoring, a_name, b_name)
            except Exception as public_exc:
                raise RuntimeError(
                    "FantasyPros live API is unavailable, no local expert-ballot cache exists for this matchup, "
                    "and the public ranking fallback could not produce usable ranks: " + str(public_exc)
                ) from live_exc


def start_sit_html():
    h = base.start_sit_html()
    # Make the hero copy honest in degraded mode.
    h = h.replace(
        "$('heroKicker').textContent=j.position+' • '+(j.scoring==='STD'?'Standard':'PPR')+' • weighted-full recommendation';",
        "$('heroKicker').textContent=j.degraded?(j.position+' • '+(j.scoring==='STD'?'Standard':'PPR')+' • public ECR fallback'):(j.position+' • '+(j.scoring==='STD'?'Standard':'PPR')+' • weighted-full recommendation');"
    )
    return h


class Handler(base.Handler):
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
            self.send_html(base.compare_base.core.ui.HOME_HTML.replace("v0.2 ·", "v0.3.6 ·"))
            return
        if parsed.path == "/start-sit":
            self.send_html(start_sit_html())
            return
        if parsed.path == "/api/compare":
            q = parse_qs(parsed.query)
            position = ((q.get("position") or ["WR"])[0]).upper()
            scoring = base.compare_base.core.norm_scoring((q.get("scoring") or ["PPR"])[0])
            try:
                with LOCK:
                    result = resilient_compare(position, scoring, (q.get("a") or [""])[0], (q.get("b") or [""])[0])
                self.send_json(result)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        # Preserve v0.3.5 -> v0.3.3 autocomplete path and v0.3.2 refresh behavior.
        return super().do_GET()


def main():
    print(f"Loading Fantasy Decision Lab v{APP_VERSION}…", flush=True)
    base.compare_base.core.initialize()
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
