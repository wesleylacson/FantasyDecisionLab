#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3 — rankings-endpoint backend.

Uses FantasyPros consensus-rankings with small accuracy-sorted expert groups.
This removes the app's dependency on the flaky compare-players endpoint while
preserving the Full / Weighted / Elite 15 / Elite 10 / Elite 5 lenses.
"""
from __future__ import annotations

import json
import math
import shutil
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pandas as pd
import requests

import app as legacy
import app_v02 as ui

APP_VERSION = "0.3.0"
YEAR = legacy.YEAR
WEEK = legacy.WEEK
POSITIONS = legacy.POSITIONS
HOST = legacy.HOST
PORT = legacy.PORT
LOCK = threading.Lock()

API_BASE = "https://api.fantasypros.com/public/v2/json"
RANKINGS_EXPERTS_URL = f"{API_BASE}/nfl/{YEAR}/rankings/experts"
CONSENSUS_URL = f"{API_BASE}/nfl/{YEAR}/consensus-rankings"
BACKEND_CACHE = legacy.CACHE_ROOT / "rankings_backend"
BACKEND_CACHE.mkdir(parents=True, exist_ok=True)
GROUP_SIZE = 5

STATE = {
    "current_accuracy": None,
    "prior_accuracy": None,
    "expert_names": {},
    "position_models": {},
}


def norm_scoring(x: str) -> str:
    x = str(x or "PPR").upper()
    if x not in {"PPR", "STD"}:
        raise ValueError("Choose PPR or STD scoring.")
    return x


def api_get(url: str, params: dict, attempts: int = 5) -> dict:
    key = legacy.get_api_key()
    if not key:
        raise RuntimeError("FantasyPros API key is not configured. Double-click First-time Setup.command in the app folder.")
    delay = 2
    last_status = None
    for attempt in range(attempts):
        try:
            r = requests.get(url, params=params, headers={"x-api-key": key}, timeout=40)
        except requests.RequestException as e:
            if attempt == attempts - 1:
                raise RuntimeError(f"FantasyPros request failed after retries: {e}")
            time.sleep(delay); delay *= 2; continue
        last_status = r.status_code
        if r.status_code == 200:
            return r.json()
        if r.status_code in {429, 500, 502, 503, 504}:
            if attempt < attempts - 1:
                time.sleep(delay); delay *= 2; continue
            break
        raise RuntimeError(f"FantasyPros rankings request failed with HTTP {r.status_code}: {r.text[:180]}")
    raise RuntimeError(f"FantasyPros rankings service is temporarily unavailable after automatic retries (HTTP {last_status}).")


def cache_file(*parts: str):
    p = BACKEND_CACHE.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_expert_names(force=False):
    path = cache_file(f"experts_{YEAR}.json")
    if path.exists() and not force:
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = api_get(RANKINGS_EXPERTS_URL, {"include_overall": "true"})
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    experts = data.get("experts") or []
    if isinstance(experts, dict):
        experts = list(experts.values())
    out = {}
    for e in experts:
        if not isinstance(e, dict):
            continue
        eid = e.get("expert_id") or e.get("id")
        name = e.get("name") or e.get("expert_name")
        if eid is not None and name:
            out[str(eid)] = str(name)
    return out


def build_position_model(position: str, force_experts=False):
    directory, active_ids = legacy.load_position_directory(position)
    if force_experts or not STATE["expert_names"]:
        STATE["expert_names"] = load_expert_names(force=force_experts)
    names = STATE["expert_names"]
    cur, prev = STATE["current_accuracy"], STATE["prior_accuracy"]
    cur_lookup = {r["NORM_NAME"]: r for _, r in cur.iterrows()}
    prev_lookup = {r["NORM_NAME"]: r for _, r in prev.iterrows()}
    pops = {
        "cur_pos": int(pd.to_numeric(cur[position], errors="coerce").notna().sum()),
        "cur_all": int(pd.to_numeric(cur["RANK"], errors="coerce").notna().sum()),
        "prev_pos": int(pd.to_numeric(prev[position], errors="coerce").notna().sum()),
        "prev_all": int(pd.to_numeric(prev["RANK"], errors="coerce").notna().sum()),
    }
    details = []
    for eid in active_ids:
        name = names.get(str(eid))
        if not name:
            continue
        n = legacy.norm_name(name)
        c, p = cur_lookup.get(n), prev_lookup.get(n)
        vals = {
            "cur_pos": c[position] if c is not None else None,
            "cur_all": c["RANK"] if c is not None else None,
            "prev_pos": p[position] if p is not None else None,
            "prev_all": p["RANK"] if p is not None else None,
        }
        num = den = 0.0
        for k, coef in legacy.FORMULA.items():
            s = legacy.percentile_score(vals[k], pops[k])
            if s is not None:
                num += coef * s; den += coef
        accuracy_score = num / den if den else 0.5
        weight = 0.75 + 0.65 * accuracy_score
        details.append({"expert_id": str(eid), "name": name, "accuracy_score": accuracy_score, "weight": weight})
    details.sort(key=lambda x: (x["accuracy_score"], x["weight"]), reverse=True)
    if len(details) < 5:
        raise RuntimeError(f"Only {len(details)} active {position} experts could be matched to the accuracy data. Refresh expert metadata and confirm the accuracy CSVs are still in Downloads.")
    model = {
        "position": position,
        "directory": directory,
        "active_ids": [d["expert_id"] for d in details],
        "details": details,
        "weights": {d["expert_id"]: d["weight"] for d in details},
        "refreshed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    STATE["position_models"][position] = model
    return model


def get_model(position):
    return STATE["position_models"].get(position) or build_position_model(position)


def resolve(name, position):
    return legacy.resolve_player(name, get_model(position)["directory"])


def group_path(position, scoring, expert_ids):
    sig = "-".join(expert_ids)
    return cache_file(str(YEAR), f"week_{WEEK}", scoring, position, f"group_{sig}.json")


def fetch_group(position, scoring, expert_ids, force=False):
    path = group_path(position, scoring, expert_ids)
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))
    params = {
        "position": position,
        "scoring": "STD" if position == "QB" else scoring,
        "week": WEEK,
        "filters": ":".join(expert_ids),
        "experts": "show",
    }
    data = api_get(CONSENSUS_URL, params)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def player_row(data, pid):
    for row in data.get("players") or []:
        rid = row.get("player_id") if isinstance(row, dict) else None
        if str(rid) == str(pid):
            return row
    return None


def rank_value(row, *keys):
    if not row:
        return None
    for key in keys:
        v = row.get(key)
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    return None


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def group_pair_stats(data, aid, bid, requested_ids, weights):
    arow, brow = player_row(data, aid), player_row(data, bid)
    aavg = rank_value(arow, "rank_ave", "rank_ecr", "rank_avg")
    bavg = rank_value(brow, "rank_ave", "rank_ecr", "rank_avg")
    if aavg is None or bavg is None:
        return None
    n = int(data.get("total_experts") or len(requested_ids) or 1)
    n = max(1, min(n, len(requested_ids)))
    asd = rank_value(arow, "rank_std", "std_dev", "rank_stdev") or 0.0
    bsd = rank_value(brow, "rank_std", "std_dev", "rank_stdev") or 0.0
    gap_signed = bavg - aavg
    sigma = math.sqrt(asd * asd + bsd * bsd)
    if sigma < 1e-9:
        ashare = 1.0 if gap_signed > 0 else 0.0 if gap_signed < 0 else 0.5
    else:
        ashare = norm_cdf(gap_signed / sigma)
    included = requested_ids[:n]
    mean_weight = sum(weights.get(e, 1.0) for e in included) / len(included) if included else 1.0
    return {"n": n, "a_avg": aavg, "b_avg": bavg, "a_std": asd, "b_std": bsd, "a_share": ashare, "mean_weight": mean_weight}


def combine_groups(name, groups, weighted=False):
    groups = [g for g in groups if g]
    if not groups:
        return {"name": name, "experts": 0, "available": False}
    mass = [(g["n"] * g["mean_weight"] if weighted else g["n"]) for g in groups]
    den = sum(mass)
    aavg = sum(g["a_avg"] * m for g, m in zip(groups, mass)) / den
    bavg = sum(g["b_avg"] * m for g, m in zip(groups, mass)) / den
    ashare = sum(g["a_share"] * m for g, m in zip(groups, mass)) / den
    return {
        "name": name, "available": True, "experts": sum(g["n"] for g in groups), "weighted": weighted,
        "a_avg_rank": aavg, "b_avg_rank": bavg, "a_vote_share": ashare, "b_vote_share": 1 - ashare,
        "winner": "A" if aavg <= bavg else "B", "rank_gap": abs(aavg - bavg),
    }


def compare(position, scoring, a_name, b_name, force=False):
    if position not in POSITIONS:
        raise ValueError("Choose QB, RB, WR, or TE.")
    scoring = norm_scoring(scoring)
    model = get_model(position)
    a, b = resolve(a_name, position), resolve(b_name, position)
    aid, bid = str(a["player_id"]), str(b["player_id"])
    ids, weights = model["active_ids"], model["weights"]
    chunks = [ids[i:i + GROUP_SIZE] for i in range(0, len(ids), GROUP_SIZE)]
    stats, newest = [], None
    for chunk in chunks:
        data = fetch_group(position, scoring, chunk, force=force)
        stats.append(group_pair_stats(data, aid, bid, chunk, weights))
        path = group_path(position, scoring, chunk)
        if path.exists():
            newest = max(newest or 0, path.stat().st_mtime)
    usable = [g for g in stats if g]
    if not usable:
        raise RuntimeError("FantasyPros rankings returned no usable ranks for one or both selected players.")

    full = combine_groups("Full consensus", usable, False)
    weighted = combine_groups("Weighted full", usable, True)
    elite15 = combine_groups("Elite 15", usable[:3], False)
    elite10 = combine_groups("Elite 10", usable[:2], False)
    elite5 = combine_groups("Elite 5", usable[:1], False)
    panels = [full, weighted, elite15, elite10, elite5]

    aavg, bavg = weighted["a_avg_rank"], weighted["b_avg_rank"]
    winner = a if aavg <= bavg else b
    winner_share = weighted["a_vote_share"] if aavg <= bavg else weighted["b_vote_share"]
    gap = abs(aavg - bavg)
    mden = sum(g["n"] * g["mean_weight"] for g in usable)
    margin_var = sum((g["a_std"] ** 2 + g["b_std"] ** 2) * g["n"] * g["mean_weight"] for g in usable) / mden
    margin_std = math.sqrt(max(0.0, margin_var))
    cp = legacy.confidence_components(winner_share, gap, margin_std)

    if cp["final"] == "TOSS-UP":
        why = "The grouped expert rankings do not show enough directional or rank separation to call this more than a coin flip."
    elif cp["final"] == "LEAN":
        why = "There is a small rankings edge, but matchup or projection context can reasonably overturn it."
    elif cp["final"] == "MODERATE":
        why = "The accuracy-grouped expert pool shows a meaningful preference. A contrary start needs a substantive football reason."
    else:
        why = "The accuracy-grouped expert pool is strongly aligned. This should usually control absent major contextual news."

    return {
        "position": position, "scoring": "STD" if position == "QB" else scoring,
        "player_a": a["player"], "team_a": a["team"], "player_b": b["player"], "team_b": b["team"],
        "recommendation": winner["player"], "confidence": cp["final"], "experts_used": weighted["experts"],
        "a_weighted_avg_rank": aavg, "b_weighted_avg_rank": bavg,
        "a_unweighted_avg_rank": full["a_avg_rank"], "b_unweighted_avg_rank": full["b_avg_rank"],
        "a_weighted_vote_share": weighted["a_vote_share"], "b_weighted_vote_share": weighted["b_vote_share"],
        "a_unweighted_vote_share": full["a_vote_share"], "b_unweighted_vote_share": full["b_vote_share"],
        "weighted_rank_gap": gap, "weighted_std_expert_margin": margin_std,
        "directional_signal": cp["direction"], "magnitude_signal": cp["magnitude"], "agreement_signal": cp["agreement"],
        "margin_stability_ratio": cp["stability_ratio"], "evidence_score": cp["evidence_score"], "panels": panels,
        "elite_experts": model["details"][:15], "why": why,
        "last_refreshed": datetime.fromtimestamp(newest, tz=timezone.utc).astimezone().isoformat(timespec="seconds") if newest else None,
        "source_note": (
            f"{position} rankings now come from FantasyPros weekly consensus-rankings, not compare-players. "
            f"Experts are sorted by the same 50/25/20/5 accuracy model and fetched in groups of {GROUP_SIZE}. "
            "Elite 5/10/15 average those top groups directly; Weighted full combines all groups using their mean accuracy weight. "
            "Directional vote share is estimated from each group's rank gap and rank dispersion, so confidence is comparable but not mathematically identical to the old per-expert-ballot backend."
        ),
    }


def players_payload(position, scoring):
    model = get_model(position)
    directory = model["directory"]
    players = []
    for _, r in directory.sort_values("directory_rank", na_position="last").iterrows():
        players.append({"player": r["player"], "team": r["team"], "player_id": str(r["player_id"]), "cached": False})
    ids = model["active_ids"]
    first = ids[:GROUP_SIZE]
    cached = bool(first and group_path(position, scoring, first).exists())
    if cached:
        for p in players:
            p["cached"] = True
    return {"position": position, "scoring": scoring, "players": players, "cached_count": len(players) if cached else 0, "total_count": len(players)}


def clear_position_cache(position, scoring=None):
    base = BACKEND_CACHE / str(YEAR) / f"week_{WEEK}"
    if scoring:
        target = base / scoring / position
        if target.exists():
            shutil.rmtree(target)
    else:
        for s in ("PPR", "STD"):
            target = base / s / position
            if target.exists():
                shutil.rmtree(target)


def initialize():
    STATE["current_accuracy"] = legacy.read_accuracy(2026)
    STATE["prior_accuracy"] = legacy.read_accuracy(2025)
    STATE["expert_names"] = load_expert_names(False)
    for p in POSITIONS:
        build_position_model(p)


class Handler(legacy.Handler):
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
            scoring = norm_scoring(body.get("scoring"))
            with LOCK:
                if scope == "matchup":
                    result = compare(position, scoring, str(body.get("a") or ""), str(body.get("b") or ""), force=True)
                    result = {"scope": scope, "position": position, "scoring": scoring, "refreshed_at": result.get("last_refreshed")}
                elif scope == "position":
                    clear_position_cache(position, scoring)
                    build_position_model(position)
                    result = {"scope": scope, "position": position, "scoring": scoring, "refreshed_at": datetime.now().astimezone().isoformat(timespec="seconds")}
                elif scope == "all":
                    root = BACKEND_CACHE / str(YEAR) / f"week_{WEEK}"
                    if root.exists():
                        shutil.rmtree(root)
                    STATE["expert_names"] = load_expert_names(True)
                    for p in POSITIONS:
                        build_position_model(p)
                    result = {"scope": scope, "refreshed_at": datetime.now().astimezone().isoformat(timespec="seconds")}
                else:
                    raise ValueError("Refresh scope must be matchup, position, or all.")
            self.send_json(result)
        except Exception as e:
            self.send_json({"error": str(e)}, status=400)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(ui.HOME_HTML.replace("v0.2 ·", "v0.3 ·")); return
        if parsed.path == "/start-sit":
            self.send_html(ui.start_sit_html()); return
        if parsed.path in {"/api/players", "/api/compare"}:
            q = parse_qs(parsed.query)
            position = ((q.get("position") or ["WR"])[0]).upper()
            scoring = norm_scoring((q.get("scoring") or ["PPR"])[0])
            try:
                with LOCK:
                    if parsed.path == "/api/players":
                        self.send_json(players_payload(position, scoring))
                    else:
                        self.send_json(compare(position, scoring, (q.get("a") or [""])[0], (q.get("b") or [""])[0]))
            except Exception as e:
                self.send_json({"error": str(e)}, status=400)
            return
        super().do_GET()


def main():
    print(f"Loading Fantasy Decision Lab v{APP_VERSION}…")
    initialize()
    for p in POSITIONS:
        print(f"{p}: {len(get_model(p)['active_ids'])} active accuracy-matched experts.")
    print(f"Fantasy Decision Lab: http://{HOST}:{PORT}")
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
