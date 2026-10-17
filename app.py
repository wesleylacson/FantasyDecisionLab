#!/usr/bin/env python3
"""
Fantasy Decision Lab — Start/Sit Web App v5

Adds same-position Start/Sit support for QB / RB / WR / TE.
No FLEX/cross-position comparisons yet.

Run:
  cd ~/Downloads
  export FANTASYPROS_API_KEY="YOUR_KEY_HERE"
  python3 fantasy_decision_lab_app_v5.py

Then open:
  http://127.0.0.1:8765

Requirements already used by the project:
  pandas, requests

Expected accuracy files somewhere in ~/Downloads:
  FantasyPros_Fantasy_Football_2026_SeasonToDate_Accuracy.csv
  FantasyPros_Fantasy_Football_2025_SeasonToDate_Accuracy.csv

Existing WR cache is reused from:
  ~/Downloads/weighted_wr_start_sit_output_v3/

New QB/RB/TE Compare responses are cached under:
  ~/Downloads/fantasy_decision_lab_cache/<POSITION>/
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pandas as pd
import requests

HOST = "127.0.0.1"
PORT = 8765
APP_VERSION = "0.1.0"
YEAR = 2026
WEEK = 6
SCORING = "PPR"
POSITIONS = ("QB", "RB", "WR", "TE")

DOWNLOADS = Path.home() / "Downloads"
LEGACY_WR_BASE = DOWNLOADS / "weighted_wr_start_sit_output_v3"
CACHE_ROOT = DOWNLOADS / "fantasy_decision_lab_cache"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)
CONFIG_DIR = Path.home() / ".fantasy_decision_lab"
CONFIG_FILE = CONFIG_DIR / "config.json"

COMPARE_URL = "https://api.fantasypros.com/public/v2/json/nfl/compare-players"
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0 Safari/537.36"
    )
}

FORMULA = {
    "cur_pos": 0.50,
    "cur_all": 0.25,
    "prev_pos": 0.20,
    "prev_all": 0.05,
}

STATE = {
    "positions": {},
    "current_accuracy": None,
    "prior_accuracy": None,
}
LOCK = threading.Lock()


def norm_name(x: str) -> str:
    x = str(x or "")
    # Accuracy CSVs sometimes append outlet after a spaced dash.
    x = re.sub(r"\s*[-–—]\s*.*$", "", x)
    x = re.sub(r"[^A-Za-z0-9 ]+", "", x).lower()
    return re.sub(r"\s+", " ", x).strip()


def extract_json_object(text: str, marker: str) -> dict:
    idx = text.find(marker)
    if idx < 0:
        raise ValueError(f"Could not find marker: {marker}")
    start = text.find("{", idx + len(marker))
    if start < 0:
        raise ValueError("Could not find JSON object start")
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("Unterminated JSON object")


def rankings_url(position: str) -> str:
    return f"https://www.fantasypros.com/nfl/rankings/{position.lower()}.php?scoring={SCORING}&week={WEEK}"


def load_position_directory(position: str):
    r = requests.get(rankings_url(position), headers=UA, timeout=30)
    r.raise_for_status()
    data = extract_json_object(r.text, "var ecrData =")

    rows = []
    for p in data.get("players") or []:
        rows.append({
            "player_id": str(p.get("player_id")),
            "player": p.get("player_name"),
            "team": p.get("player_team_id"),
            "directory_rank": p.get("rank_ecr"),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(f"FantasyPros {position} directory returned no players.")
    df["norm"] = df["player"].map(norm_name)
    df["directory_rank"] = pd.to_numeric(df["directory_rank"], errors="coerce")

    active_ids = [x.strip() for x in str(data.get("filters") or "").split(",") if x.strip()]
    return df, active_ids


def find_accuracy_file(year: int) -> Path:
    exact = DOWNLOADS / f"FantasyPros_Fantasy_Football_{year}_SeasonToDate_Accuracy.csv"
    if exact.exists():
        return exact
    candidates = list(DOWNLOADS.rglob(f"*FantasyPros*{year}*Accuracy*.csv"))
    if not candidates:
        raise FileNotFoundError(
            f"Could not find the FantasyPros {year} accuracy CSV under ~/Downloads."
        )
    return candidates[0]


def read_accuracy(year: int) -> pd.DataFrame:
    path = find_accuracy_file(year)
    df = pd.read_csv(path)
    df.columns = [str(c).strip().upper() for c in df.columns]
    required = {"RANK", "EXPERT NAME", "QB", "RB", "WR", "TE"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"{path.name} is missing columns: {sorted(missing)}")
    df["NORM_NAME"] = df["EXPERT NAME"].map(norm_name)
    return df


def percentile_score(rank, population: int):
    if rank is None or pd.isna(rank):
        return None
    if population <= 1:
        return 0.5
    rank = float(rank)
    return max(0.0, min(1.0, 1.0 - (rank - 1.0) / (population - 1.0)))


def position_cache_dir(position: str) -> Path:
    pos_dir = CACHE_ROOT / position
    pos_dir.mkdir(parents=True, exist_ok=True)
    return pos_dir


def legacy_ignore_marker(position: str) -> Path:
    return position_cache_dir(position) / ".ignore_legacy_cache"


def position_cache_dirs(position: str):
    dirs = []
    if position == "WR" and LEGACY_WR_BASE.exists() and not legacy_ignore_marker(position).exists():
        dirs.append(LEGACY_WR_BASE)
    dirs.append(position_cache_dir(position))
    return dirs


def iter_json_payloads(position: str):
    seen = set()
    for root in position_cache_dirs(position):
        for path in root.rglob("*.json"):
            rp = str(path.resolve())
            if rp in seen:
                continue
            seen.add(rp)
            try:
                yield path, json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue


def collect_ballots(position: str) -> dict[str, dict[str, float]]:
    ballots: dict[str, dict[str, float]] = {}

    # QB rankings are not reception-scoring dependent, and FantasyPros Compare
    # responses expose them under STD. RB/WR/TE use PPR for this app.
    scoring_key = "STD" if position == "QB" else "PPR"

    def absorb(obj):
        if not isinstance(obj, dict):
            return
        rankings = obj.get("rankings")
        bucket = rankings.get(scoring_key) if isinstance(rankings, dict) else None
        if isinstance(bucket, dict):
            for pid, rows in bucket.items():
                dest = ballots.setdefault(str(pid), {})
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        try:
                            dest[str(row.get("expert_id"))] = float(row.get("rank"))
                        except Exception:
                            pass
        for value in obj.values():
            if isinstance(value, dict):
                absorb(value)

    for _, data in iter_json_payloads(position):
        absorb(data)
    return ballots


def collect_expert_meta_all_positions() -> dict[str, dict]:
    meta = {}
    roots = []
    if LEGACY_WR_BASE.exists():
        roots.append(LEGACY_WR_BASE)
    if CACHE_ROOT.exists():
        roots.append(CACHE_ROOT)

    seen = set()
    for root in roots:
        for path in root.rglob("*.json"):
            rp = str(path.resolve())
            if rp in seen:
                continue
            seen.add(rp)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue

            def absorb(obj):
                if not isinstance(obj, dict):
                    return
                experts = obj.get("experts")
                if isinstance(experts, dict):
                    for eid, e in experts.items():
                        if isinstance(e, dict):
                            meta[str(eid)] = e
                elif isinstance(experts, list):
                    for e in experts:
                        if not isinstance(e, dict):
                            continue
                        eid = e.get("expert_id") or e.get("id")
                        if eid is not None:
                            meta[str(eid)] = e
                for value in obj.values():
                    if isinstance(value, dict):
                        absorb(value)
            absorb(data)
    return meta


def expert_display_name(meta: dict):
    if not isinstance(meta, dict):
        return None
    return meta.get("name") or meta.get("expert_name") or meta.get("display_name") or meta.get("expert")


def build_position_weights(position: str) -> dict[str, float]:
    pos_state = STATE["positions"][position]
    active_ids = pos_state["active_ids"]
    expert_meta = collect_expert_meta_all_positions()
    cur = STATE["current_accuracy"]
    prev = STATE["prior_accuracy"]

    cur_lookup = {r["NORM_NAME"]: r for _, r in cur.iterrows()}
    prev_lookup = {r["NORM_NAME"]: r for _, r in prev.iterrows()}

    populations = {
        "cur_pos": int(pd.to_numeric(cur[position], errors="coerce").notna().sum()),
        "cur_all": int(pd.to_numeric(cur["RANK"], errors="coerce").notna().sum()),
        "prev_pos": int(pd.to_numeric(prev[position], errors="coerce").notna().sum()),
        "prev_all": int(pd.to_numeric(prev["RANK"], errors="coerce").notna().sum()),
    }

    weights = {}
    details = []
    for eid in active_ids:
        meta = expert_meta.get(str(eid), {})
        name = expert_display_name(meta)
        if not name:
            continue
        n = norm_name(name)
        c = cur_lookup.get(n)
        p = prev_lookup.get(n)

        vals = {
            "cur_pos": c[position] if c is not None else None,
            "cur_all": c["RANK"] if c is not None else None,
            "prev_pos": p[position] if p is not None else None,
            "prev_all": p["RANK"] if p is not None else None,
        }

        numerator = 0.0
        denominator = 0.0
        for k, coef in FORMULA.items():
            score = percentile_score(vals[k], populations[k])
            if score is not None:
                numerator += coef * score
                denominator += coef
        accuracy_score = numerator / denominator if denominator else 0.5
        model_weight = 0.75 + 0.65 * accuracy_score
        weights[str(eid)] = model_weight
        details.append({
            "expert_id": str(eid),
            "name": name,
            "position": position,
            **vals,
            "accuracy_score": accuracy_score,
            "model_weight": model_weight,
        })

    if details:
        detail_df = pd.DataFrame(details).sort_values(["accuracy_score", "model_weight"], ascending=False)
        detail_df.to_csv(CACHE_ROOT / position / "expert_weights.csv", index=False)
        pos_state["expert_details"] = detail_df.to_dict("records")
        pos_state["elite_order"] = [str(x) for x in detail_df["expert_id"].tolist()]
    else:
        pos_state["expert_details"] = []
        pos_state["elite_order"] = []
    pos_state["weights"] = weights
    return weights


def resolve_player(name: str, directory: pd.DataFrame) -> dict:
    n = norm_name(name)
    exact = directory[directory["norm"] == n]
    if len(exact) == 1:
        return exact.iloc[0].to_dict()
    contains = directory[directory["norm"].str.contains(re.escape(n), na=False)]
    if len(contains) == 1:
        return contains.iloc[0].to_dict()
    raise ValueError(f"Could not uniquely resolve player: {name}")


def weighted_mean(values, weights):
    den = sum(weights)
    return sum(v * w for v, w in zip(values, weights)) / den if den else float("nan")


def weighted_std(values, weights):
    den = sum(weights)
    if not den:
        return float("nan")
    mu = weighted_mean(values, weights)
    var = sum(w * (v - mu) ** 2 for v, w in zip(values, weights)) / den
    return math.sqrt(var)


def confidence_components(weighted_share_best: float, avg_rank_gap: float, margin_stdev: float) -> dict:
    majority = max(weighted_share_best, 1 - weighted_share_best)
    gap = abs(avg_rank_gap)

    if majority < 0.575:
        direction = "TOSS-UP"
    elif majority < 0.70:
        direction = "LEAN"
    elif majority < 0.82:
        direction = "MODERATE"
    else:
        direction = "STRONG"

    if gap < 0.35:
        magnitude = "TINY"
    elif gap < 1.00:
        magnitude = "SMALL"
    elif gap < 2.50:
        magnitude = "MEANINGFUL"
    else:
        magnitude = "LARGE"

    if math.isnan(margin_stdev):
        stability_ratio = float("nan")
        agreement = "UNKNOWN"
        stability_score = 0.50
    else:
        stability_ratio = margin_stdev / max(gap, 0.25)
        if stability_ratio <= 0.75:
            agreement = "STABLE"
        elif stability_ratio <= 2.0:
            agreement = "MIXED"
        else:
            agreement = "VOLATILE"
        stability_score = max(0.0, min(1.0, 1.0 - stability_ratio / 4.0))

    direction_score = max(0.0, min(1.0, (majority - 0.50) / 0.50))
    magnitude_score = max(0.0, min(1.0, gap / 5.0))
    evidence_score = 0.45 * direction_score + 0.40 * magnitude_score + 0.15 * stability_score

    if evidence_score < 0.16:
        final = "TOSS-UP"
    elif evidence_score < 0.34:
        final = "LEAN"
    elif evidence_score < 0.62:
        final = "MODERATE"
    else:
        final = "STRONG"

    order = {"TOSS-UP": 0, "LEAN": 1, "MODERATE": 2, "STRONG": 3}
    labels = ["TOSS-UP", "LEAN", "MODERATE", "STRONG"]
    if majority < 0.56:
        final = labels[min(order[final], 1)]
    elif majority < 0.80:
        final = labels[min(order[final], 2)]
    if final == "STRONG" and not (majority >= 0.88 and gap >= 2.50):
        final = "MODERATE"

    return {
        "final": final,
        "direction": direction,
        "magnitude": magnitude,
        "agreement": agreement,
        "stability_ratio": stability_ratio,
        "majority_share": majority,
        "evidence_score": evidence_score,
    }


def get_api_key():
    key = os.environ.get("FANTASYPROS_API_KEY")
    if key:
        return key.strip()
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            key = str(data.get("fantasypros_api_key") or "").strip()
            if key:
                return key
    except Exception:
        pass
    return None


def fetch_pair_and_cache(position: str, aid: str, bid: str, force: bool = False):
    key = get_api_key()
    if not key:
        raise RuntimeError(
            "FantasyPros API key is not configured. Double-click First-time Setup.command in the app folder."
        )

    live_cache = CACHE_ROOT / position / "compare_cache"
    live_cache.mkdir(parents=True, exist_ok=True)
    ids = sorted([str(aid), str(bid)])
    cache = live_cache / f"compare_{ids[0]}_{ids[1]}.json"
    if cache.exists() and not force:
        return cache

    params = {
        "players": f"{aid}:{bid}",
        "position": position,
        "year": YEAR,
        "week": WEEK,
        "ranking_type": "weekly",
        "details": "all",
    }
    backoff = 10
    for _ in range(5):
        r = requests.get(COMPARE_URL, params=params, headers={"x-api-key": key}, timeout=30)
        if r.status_code == 200:
            cache.write_text(json.dumps(r.json(), indent=2), encoding="utf-8")
            return cache
        if r.status_code == 429:
            time.sleep(backoff)
            backoff *= 2
            continue
        raise RuntimeError(f"FantasyPros Compare request failed with HTTP {r.status_code}: {r.text[:200]}")
    raise RuntimeError("FantasyPros rate limit retries were exhausted.")


def iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def matchup_last_refreshed(position: str, aid: str, bid: str):
    scoring_key = "STD" if position == "QB" else "PPR"
    newest = None
    for path, data in iter_json_payloads(position):
        try:
            bucket = (data.get("rankings") or {}).get(scoring_key) or {}
            if str(aid) in bucket and str(bid) in bucket:
                mt = path.stat().st_mtime
                newest = mt if newest is None else max(newest, mt)
        except Exception:
            continue
    if newest is None:
        return None
    return datetime.fromtimestamp(newest, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def rebuild_position_state(position: str):
    directory, active_ids = load_position_directory(position)
    STATE["positions"][position] = {
        "directory": directory,
        "active_ids": active_ids,
        "ballots": collect_ballots(position),
        "weights": {},
        "expert_details": [],
        "elite_order": [],
        "directory_refreshed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    try:
        STATE["positions"][position]["weights"] = build_position_weights(position)
    except Exception:
        pass


def refresh_matchup(position: str, a_name: str, b_name: str):
    pos_state = STATE["positions"][position]
    a = resolve_player(a_name, pos_state["directory"])
    b = resolve_player(b_name, pos_state["directory"])
    aid, bid = str(a["player_id"]), str(b["player_id"])
    path = fetch_pair_and_cache(position, aid, bid, force=True)
    pos_state["ballots"] = collect_ballots(position)
    pos_state["weights"] = {}
    ensure_weights(position)
    return {
        "scope": "matchup",
        "position": position,
        "player_a": a["player"],
        "player_b": b["player"],
        "refreshed_at": iso_mtime(path) if path else datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def invalidate_position(position: str):
    pos_dir = CACHE_ROOT / position
    if pos_dir.exists():
        shutil.rmtree(pos_dir)
    pos_dir.mkdir(parents=True, exist_ok=True)
    if position == "WR":
        legacy_ignore_marker(position).write_text(
            "Legacy WR QA cache invalidated by in-app refresh.\n", encoding="utf-8"
        )
    rebuild_position_state(position)
    return {
        "scope": "position",
        "position": position,
        "refreshed_at": STATE["positions"][position]["directory_refreshed_at"],
    }


def invalidate_all():
    global_state_time = datetime.now().astimezone().isoformat(timespec="seconds")
    STATE["current_accuracy"] = read_accuracy(2026)
    STATE["prior_accuracy"] = read_accuracy(2025)
    for position in POSITIONS:
        invalidate_position(position)
    return {"scope": "all", "refreshed_at": global_state_time}


def ensure_weights(position: str):
    pos_state = STATE["positions"][position]
    weights = pos_state.get("weights") or {}
    if weights:
        return weights
    return build_position_weights(position)


def panel_metrics(name: str, expert_ids, aid: str, bid: str, ballots, weights=None) -> dict:
    common = [eid for eid in expert_ids if eid in ballots.get(aid, {}) and eid in ballots.get(bid, {})]
    if not common:
        return {"name": name, "experts": 0, "available": False}
    ar = [ballots[aid][eid] for eid in common]
    br = [ballots[bid][eid] for eid in common]
    diffs = [rb - ra for ra, rb in zip(ar, br)]
    if weights is None:
        ws = [1.0] * len(common)
        weighted = False
    else:
        ws = [float(weights[eid]) for eid in common]
        weighted = True
    a_avg = weighted_mean(ar, ws)
    b_avg = weighted_mean(br, ws)
    total_w = sum(ws)
    a_vote_w = sum(w for d, w in zip(diffs, ws) if d > 0) + 0.5 * sum(w for d, w in zip(diffs, ws) if d == 0)
    a_share = a_vote_w / total_w if total_w else 0.5
    return {
        "name": name, "available": True, "experts": len(common), "weighted": weighted,
        "a_avg_rank": a_avg, "b_avg_rank": b_avg,
        "a_vote_share": a_share, "b_vote_share": 1 - a_share,
        "winner": "A" if a_avg <= b_avg else "B",
        "rank_gap": abs(a_avg - b_avg),
    }


def compare(position: str, a_name: str, b_name: str) -> dict:
    if position not in POSITIONS:
        raise ValueError("Choose QB, RB, WR, or TE.")

    pos_state = STATE["positions"][position]
    directory = pos_state["directory"]
    a = resolve_player(a_name, directory)
    b = resolve_player(b_name, directory)
    aid, bid = str(a["player_id"]), str(b["player_id"])

    ballots = pos_state["ballots"]
    # New positions will generally need one pair fetch on first use. Fetching also
    # gives us current expert metadata, which lets us construct position weights.
    if aid not in ballots or bid not in ballots:
        fetch_pair_and_cache(position, aid, bid)
        pos_state["ballots"] = collect_ballots(position)
        ballots = pos_state["ballots"]
        pos_state["weights"] = {}  # expert metadata may have improved

    if aid not in ballots or bid not in ballots:
        raise RuntimeError(f"FantasyPros did not return the expected {'STD' if position == 'QB' else 'PPR'} ballots for one or both players.")

    weights = ensure_weights(position)
    common = sorted(set(ballots[aid]) & set(ballots[bid]) & set(weights))
    if not common:
        # One fallback rebuild after the selected pair's expert metadata is present.
        pos_state["weights"] = {}
        weights = ensure_weights(position)
        common = sorted(set(ballots[aid]) & set(ballots[bid]) & set(weights))
    if not common:
        raise RuntimeError(
            f"No common weighted {position} experts were available. Check that the 2026/2025 accuracy CSVs remain in Downloads."
        )

    ar = [ballots[aid][eid] for eid in common]
    br = [ballots[bid][eid] for eid in common]
    ws = [weights[eid] for eid in common]

    a_avg = weighted_mean(ar, ws)
    b_avg = weighted_mean(br, ws)
    a_raw = sum(ar) / len(ar)
    b_raw = sum(br) / len(br)
    diffs = [rb - ra for ra, rb in zip(ar, br)]
    diff_std = weighted_std(diffs, ws)

    a_vote_w = sum(w for d, w in zip(diffs, ws) if d > 0) + 0.5 * sum(w for d, w in zip(diffs, ws) if d == 0)
    total_w = sum(ws)
    a_share = a_vote_w / total_w
    a_vote_raw = sum(1 for d in diffs if d > 0) + 0.5 * sum(1 for d in diffs if d == 0)
    a_share_raw = a_vote_raw / len(diffs)

    elite_order = [eid for eid in pos_state.get("elite_order", []) if eid in common]
    if not elite_order:
        build_position_weights(position)
        elite_order = [eid for eid in pos_state.get("elite_order", []) if eid in common]

    panels = [
        panel_metrics("Full consensus", common, aid, bid, ballots, weights=None),
        panel_metrics("Weighted full", common, aid, bid, ballots, weights=weights),
        panel_metrics("Elite 15", elite_order[:15], aid, bid, ballots, weights=None),
        panel_metrics("Elite 10", elite_order[:10], aid, bid, ballots, weights=None),
        panel_metrics("Elite 5", elite_order[:5], aid, bid, ballots, weights=None),
    ]

    if a_avg <= b_avg:
        winner = a
        winner_share = a_share
    else:
        winner = b
        winner_share = 1 - a_share

    gap = abs(a_avg - b_avg)
    cp = confidence_components(winner_share, gap, diff_std)

    if cp["final"] == "TOSS-UP":
        why = "Neither the direction nor the size of the expert edge is strong enough to treat this as more than a coin flip."
    elif cp["final"] == "LEAN":
        if cp["magnitude"] == "TINY" and cp["direction"] in {"MODERATE", "STRONG"}:
            why = "Most weighted experts prefer the recommendation, but the expected ranking advantage is tiny."
        else:
            why = "There is a small but real expert-consensus edge; matchup or projection context can reasonably overturn it."
    elif cp["final"] == "MODERATE":
        why = "The weighted expert pool shows a meaningful preference. A contrary start needs a substantive football reason."
    else:
        why = "The weighted expert pool is strongly aligned. This should usually control the decision absent major contextual news."

    return {
        "position": position,
        "player_a": a["player"], "team_a": a["team"],
        "player_b": b["player"], "team_b": b["team"],
        "recommendation": winner["player"],
        "confidence": cp["final"],
        "experts_used": len(common),
        "a_weighted_avg_rank": a_avg,
        "b_weighted_avg_rank": b_avg,
        "a_unweighted_avg_rank": a_raw,
        "b_unweighted_avg_rank": b_raw,
        "a_weighted_vote_share": a_share,
        "b_weighted_vote_share": 1 - a_share,
        "a_unweighted_vote_share": a_share_raw,
        "b_unweighted_vote_share": 1 - a_share_raw,
        "weighted_rank_gap": gap,
        "weighted_std_expert_margin": diff_std,
        "directional_signal": cp["direction"],
        "magnitude_signal": cp["magnitude"],
        "agreement_signal": cp["agreement"],
        "margin_stability_ratio": cp["stability_ratio"],
        "evidence_score": cp["evidence_score"],
        "panels": panels,
        "elite_experts": [
            {"expert_id": str(d.get("expert_id")), "name": d.get("name"), "accuracy_score": d.get("accuracy_score")}
            for d in pos_state.get("expert_details", [])[:15]
        ],
        "why": why,
        "last_refreshed": matchup_last_refreshed(position, aid, bid),
        "source_note": (
            f"{position} raw consensus is the unweighted average of the active {'STD' if position == 'QB' else 'PPR'} expert ballots. "
            f"Rank the Rankers uses 50% current {position} accuracy, 25% current overall accuracy, "
            f"20% prior {position} accuracy, and 5% prior overall accuracy, renormalizing when prior data is missing."
        ),
    }


def initialize():
    STATE["current_accuracy"] = read_accuracy(2026)
    STATE["prior_accuracy"] = read_accuracy(2025)

    for position in POSITIONS:
        rebuild_position_state(position)


HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Fantasy Decision Lab — Start/Sit</title>
<style>
:root{--bg:#07101f;--panel:#101b2f;--line:#233454;--text:#f4f7fb;--muted:#96a8c4;--accent:#7b7cff;--accent2:#39d0ff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0%,#13264a 0,#07101f 35%),var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh}.shell{max-width:1260px;margin:0 auto;padding:34px 20px 80px}.eyebrow{text-transform:uppercase;letter-spacing:.14em;font-size:12px;color:var(--accent2);font-weight:800}.title{font-size:42px;line-height:1;margin:8px 0 6px;font-weight:900}.sub{color:var(--muted);max-width:940px;line-height:1.55;margin:0 0 24px}.panel{background:linear-gradient(180deg,rgba(18,31,54,.96),rgba(12,22,40,.96));border:1px solid var(--line);border-radius:22px}.position-block{padding:20px;margin-bottom:16px}.position-label{font-size:12px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);font-weight:800;margin-bottom:12px}.positions{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.pos{border:1px solid #304568;background:#091426;color:#c9d6e8;border-radius:14px;padding:13px 10px;font-size:15px;font-weight:900;cursor:pointer}.pos.active{background:linear-gradient(90deg,var(--accent),var(--accent2));border-color:transparent;color:#06111f}.picker{padding:20px;display:grid;grid-template-columns:1fr 56px 1fr;gap:14px;align-items:end}.field label{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:700;margin:0 0 8px}.field input{width:100%;padding:15px 16px;border-radius:14px;border:1px solid #314466;background:#091426;color:white;font-size:16px}.vs{text-align:center;color:var(--muted);font-weight:900;padding-bottom:15px}.actions{padding:0 20px 20px;display:flex;gap:12px;align-items:center}.btn{border:0;border-radius:14px;padding:14px 20px;background:linear-gradient(90deg,var(--accent),var(--accent2));color:#06111f;font-weight:900;font-size:15px;cursor:pointer}.btn.secondary{background:#0a1629;color:#c9d6e8;border:1px solid #304568}.btn.danger{background:#26131a;color:#ffc6d2;border:1px solid #6b2d3b}.btn:disabled{opacity:.55;cursor:not-allowed}.status{color:var(--muted);font-size:13px}.refresh-row{padding:0 20px 20px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}.freshness{color:var(--muted);font-size:12px;margin-top:10px}.result{display:none;margin-top:22px}.hero{padding:28px}.hero-grid{display:grid;grid-template-columns:1.35fr .65fr;gap:24px;align-items:center}.kicker{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;font-weight:800}.rec{font-size:40px;font-weight:950;margin:4px 0 6px}.confidence{display:inline-flex;border:1px solid #385274;background:#0a1629;border-radius:999px;padding:7px 11px;font-size:12px;font-weight:900;letter-spacing:.08em}.why{color:#b8c6da;line-height:1.55;margin-top:15px}.scorebox{background:#081426;border:1px solid #233a60;border-radius:18px;padding:20px;text-align:center}.scorebox .num{font-size:44px;font-weight:950}.scorebox .label{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.09em}.section-title{margin:28px 0 10px;font-size:13px;text-transform:uppercase;letter-spacing:.11em;color:var(--muted);font-weight:900}.lens-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}.lens{padding:16px;min-height:196px}.lens h3{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:0 0 12px}.lens-winner{font-size:18px;font-weight:950;margin-bottom:12px}.lens-row{display:flex;justify-content:space-between;gap:10px;padding:7px 0;border-top:1px solid #1e304d;font-size:12px}.lens-row span:last-child{font-weight:850}.mini-bar{height:8px;background:#23324f;border-radius:99px;overflow:hidden;display:flex;margin-top:12px}.mini-a{background:linear-gradient(90deg,var(--accent),#9d7cff)}.mini-b{background:linear-gradient(90deg,#35bfdc,var(--accent2))}.mini-labels{display:flex;justify-content:space-between;color:var(--muted);font-size:10px;margin-top:5px}.lens-foot{margin-top:10px;color:#657b9d;font-size:10px;line-height:1.4}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px}.metric{padding:22px}.metric h3{margin:0 0 18px;font-size:13px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted)}.bar{height:14px;background:#23324f;border-radius:99px;overflow:hidden;display:flex}.barA{background:linear-gradient(90deg,var(--accent),#9d7cff)}.barB{background:linear-gradient(90deg,#35bfdc,var(--accent2))}.vote-labels{display:flex;justify-content:space-between;margin-top:8px;font-size:13px;color:var(--muted)}.signals{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.signal{background:#091426;border:1px solid #223654;border-radius:14px;padding:14px}.signal small{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.09em}.signal strong{display:block;margin-top:5px;font-size:15px}.foot{margin-top:18px;color:#7388a8;font-size:12px;line-height:1.5}.experiment{padding:17px;margin-top:18px;border:1px dashed #365077;background:#0a1527;border-radius:18px;color:#98abc7;font-size:12px;line-height:1.55}.error{display:none;margin-top:18px;border:1px solid #713a4c;background:#2b1420;color:#ffc8d4;border-radius:16px;padding:16px;white-space:pre-wrap}@media(max-width:1000px){.lens-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:760px){.title{font-size:34px}.positions{grid-template-columns:repeat(2,1fr)}.picker,.hero-grid,.grid,.lens-grid{grid-template-columns:1fr}.vs{padding:0}.rec{font-size:32px}.signals{grid-template-columns:1fr}}
</style></head>
<body><main class="shell">
<div class="eyebrow">Fantasy Decision Lab</div><div class="title">Start / Sit</div><p class="sub">Five lenses on the same matchup: full expert consensus, accuracy-weighted full consensus, and equal-weight panels containing only the top 15, top 10, or top 5 rankers at that position.</p>
<section class="panel position-block"><div class="position-label">Choose position</div><div class="positions"><button class="pos" data-pos="QB">QB</button><button class="pos" data-pos="RB">RB</button><button class="pos active" data-pos="WR">WR</button><button class="pos" data-pos="TE">TE</button></div></section>
<section class="panel"><div class="picker"><div class="field"><label id="labelA">WR A</label><input id="a" list="players" /></div><div class="vs">VS</div><div class="field"><label id="labelB">WR B</label><input id="b" list="players" /></div></div><div class="actions"><button id="go" class="btn">Compare players</button><span id="status" class="status"></span></div><div class="refresh-row"><button id="refreshMatchup" class="btn secondary">Refresh current matchup</button><button id="refreshPosition" class="btn secondary">Refresh selected position</button><button id="refreshAll" class="btn danger">Refresh all caches</button></div></section>
<datalist id="players"></datalist><div id="error" class="error"></div>
<section id="result" class="result"><div class="panel hero"><div class="hero-grid"><div><div id="heroKicker" class="kicker"></div><div id="rec" class="rec"></div><span id="conf" class="confidence"></span><div id="why" class="why"></div></div><div class="scorebox"><div id="edge" class="num"></div><div class="label">weighted-full rank edge</div></div></div></div>
<div class="section-title">Five consensus lenses</div><div id="lensGrid" class="lens-grid"></div>
<div class="experiment">Elite 15 / 10 / 5 are intentionally <strong>equal-weighted</strong>. The position-specific accuracy model selects who makes each panel, then every selected expert gets one vote. This isolates panel quality from weighting strength.</div>
<div class="grid"><div class="panel metric"><h3>Weighted-full expert vote</h3><div class="bar"><div id="barA" class="barA"></div><div id="barB" class="barB"></div></div><div class="vote-labels"><span id="voteA"></span><span id="voteB"></span></div><div class="foot"><span id="experts"></span> common weighted experts.</div></div><div class="panel metric"><h3>Confidence anatomy</h3><div class="signals"><div class="signal"><small>Direction</small><strong id="direction"></strong></div><div class="signal"><small>Magnitude</small><strong id="magnitude"></strong></div><div class="signal"><small>Agreement</small><strong id="agreement"></strong></div></div><div class="foot">Evidence score: <span id="evidence"></span>. The headline recommendation still uses the frozen weighted-full model; the elite panels are experimental.</div></div></div><div id="freshness" class="freshness"></div><div id="source" class="foot"></div></section>
<script>
const $=id=>document.getElementById(id);const fmt=x=>Number(x).toFixed(2);const pct=x=>(100*Number(x)).toFixed(1)+'%';let position='WR';
const placeholders={QB:['Jordan Love','Trevor Lawrence'],RB:['Rhamondre Stevenson','Braelon Allen'],WR:['Malik Nabers','George Pickens'],TE:['Tucker Kraft','Dalton Kincaid']};
async function loadPlayers(){const r=await fetch('/api/players?position='+position);const j=await r.json();if(!r.ok)throw new Error(j.error||'Could not load players');const dl=$('players');dl.innerHTML='';j.players.forEach(p=>{const o=document.createElement('option');o.value=p.player;o.label=(p.team||'')+(p.cached?' • cached':'');dl.appendChild(o)});$('status').textContent=`${j.cached_count} ${position}s cached • ${j.total_count} in directory`;}
async function selectPosition(pos){position=pos;document.querySelectorAll('.pos').forEach(b=>b.classList.toggle('active',b.dataset.pos===pos));$('labelA').textContent=pos+' A';$('labelB').textContent=pos+' B';$('a').value='';$('b').value='';$('a').placeholder=placeholders[pos][0];$('b').placeholder=placeholders[pos][1];$('result').style.display='none';$('error').style.display='none';try{await loadPlayers()}catch(e){showErr(e.message)}}
async function compare(){const a=$('a').value.trim(),b=$('b').value.trim();$('error').style.display='none';$('result').style.display='none';if(!a||!b){showErr('Choose two '+position+'s.');return}if(a===b){showErr('Choose two different players.');return}const btn=$('go');btn.disabled=true;$('status').textContent='Running five-panel comparison…';try{const r=await fetch(`/api/compare?position=${position}&a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);const j=await r.json();if(!r.ok)throw new Error(j.error||'Comparison failed');render(j);$('status').textContent='Comparison complete';await loadPlayers();}catch(e){showErr(e.message);$('status').textContent='';}finally{btn.disabled=false}}
async function refreshData(scope){const a=$('a').value.trim(),b=$('b').value.trim();if(scope==='matchup'&&(!a||!b)){showErr('Choose two players before refreshing the current matchup.');return}if(scope==='all'&&!confirm('Clear all cached QB/RB/WR/TE ballots? Fresh ballots will be fetched on demand.'))return;if(scope==='position'&&!confirm(`Clear cached ${position} ballots? Fresh ballots will be fetched on demand.`))return;$('error').style.display='none';const ids=['go','refreshMatchup','refreshPosition','refreshAll'];ids.forEach(id=>$(id).disabled=true);$('status').textContent=scope==='matchup'?'Refreshing this matchup…':scope==='position'?`Resetting ${position} cache…`:'Resetting all caches…';try{const r=await fetch('/api/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scope,position,a,b})});const j=await r.json();if(!r.ok)throw new Error(j.error||'Refresh failed');if(scope==='matchup'){const cr=await fetch(`/api/compare?position=${position}&a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);const cj=await cr.json();if(!cr.ok)throw new Error(cj.error||'Comparison failed after refresh');render(cj);$('status').textContent='Current matchup refreshed';}else{$('result').style.display='none';$('status').textContent=scope==='position'?`${position} cache cleared — next comparison will fetch fresh ballots`:'All caches cleared — next comparisons will fetch fresh ballots';}await loadPlayers();}catch(e){showErr(e.message);$('status').textContent='';}finally{ids.forEach(id=>$(id).disabled=false)}}
function showErr(s){$('error').textContent=s;$('error').style.display='block'}
function lensCard(p,j){if(!p.available)return `<div class="panel lens"><h3>${p.name}</h3><div class="lens-winner">Unavailable</div></div>`;const winner=p.winner==='A'?j.player_a:j.player_b;const av=100*Number(p.a_vote_share),bv=100-av;return `<div class="panel lens"><h3>${p.name}</h3><div class="lens-winner">${winner}</div><div class="lens-row"><span>${j.player_a}</span><span>${fmt(p.a_avg_rank)}</span></div><div class="lens-row"><span>${j.player_b}</span><span>${fmt(p.b_avg_rank)}</span></div><div class="mini-bar"><div class="mini-a" style="width:${av.toFixed(1)}%"></div><div class="mini-b" style="width:${bv.toFixed(1)}%"></div></div><div class="mini-labels"><span>${av.toFixed(1)}%</span><span>${bv.toFixed(1)}%</span></div><div class="lens-foot">${p.experts} experts • rank gap ${fmt(p.rank_gap)}${p.weighted?' • accuracy weighted':' • equal weight'}</div></div>`;}
function render(j){$('heroKicker').textContent=j.position+' weighted-full recommendation';$('rec').textContent='START '+j.recommendation.toUpperCase();$('conf').textContent=j.confidence+' CONFIDENCE';$('why').textContent=j.why;$('edge').textContent=fmt(j.weighted_rank_gap);$('lensGrid').innerHTML=(j.panels||[]).map(p=>lensCard(p,j)).join('');$('barA').style.width=pct(j.a_weighted_vote_share);$('barB').style.width=pct(j.b_weighted_vote_share);$('voteA').textContent=`${j.player_a} ${pct(j.a_weighted_vote_share)}`;$('voteB').textContent=`${pct(j.b_weighted_vote_share)} ${j.player_b}`;$('experts').textContent=j.experts_used;$('direction').textContent=j.directional_signal;$('magnitude').textContent=j.magnitude_signal;$('agreement').textContent=j.agreement_signal;$('evidence').textContent=Number(j.evidence_score).toFixed(3);$('freshness').textContent=j.last_refreshed?`Ballot data last refreshed: ${new Date(j.last_refreshed).toLocaleString()}`:'Ballot refresh time unavailable';$('source').textContent=j.source_note;$('result').style.display='block';$('result').scrollIntoView({behavior:'smooth',block:'start'});}
document.querySelectorAll('.pos').forEach(b=>b.addEventListener('click',()=>selectPosition(b.dataset.pos)));$('go').addEventListener('click',compare);$('refreshMatchup').addEventListener('click',()=>refreshData('matchup'));$('refreshPosition').addEventListener('click',()=>refreshData('position'));$('refreshAll').addEventListener('click',()=>refreshData('all'));document.addEventListener('keydown',e=>{if(e.key==='Enter'&&document.activeElement.tagName==='INPUT')compare()});selectPosition('WR');
</script></main></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_json(self, payload, status=200):
        data = json.dumps(payload, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/refresh":
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            scope = str(body.get("scope") or "").lower()
            position = str(body.get("position") or "WR").upper()
            with LOCK:
                if scope == "matchup":
                    if position not in POSITIONS:
                        raise ValueError("Choose QB, RB, WR, or TE.")
                    result = refresh_matchup(position, str(body.get("a") or ""), str(body.get("b") or ""))
                elif scope == "position":
                    if position not in POSITIONS:
                        raise ValueError("Choose QB, RB, WR, or TE.")
                    result = invalidate_position(position)
                elif scope == "all":
                    result = invalidate_all()
                else:
                    raise ValueError("Refresh scope must be matchup, position, or all.")
            self.send_json(result)
        except Exception as e:
            self.send_json({"error": str(e)}, status=400)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            data = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if parsed.path == "/api/players":
            qs = parse_qs(parsed.query)
            position = ((qs.get("position") or ["WR"])[0]).upper()
            try:
                if position not in POSITIONS:
                    raise ValueError("Choose QB, RB, WR, or TE.")
                pos_state = STATE["positions"][position]
                directory = pos_state["directory"]
                ballots = pos_state["ballots"]
                players = []
                for _, r in directory.sort_values("directory_rank", na_position="last").iterrows():
                    pid = str(r["player_id"])
                    players.append({
                        "player": r["player"], "team": r["team"], "player_id": pid,
                        "cached": pid in ballots,
                    })
                self.send_json({
                    "position": position,
                    "players": players,
                    "cached_count": sum(1 for p in players if p["cached"]),
                    "total_count": len(players),
                })
            except Exception as e:
                self.send_json({"error": str(e)}, status=400)
            return

        if parsed.path == "/api/compare":
            qs = parse_qs(parsed.query)
            position = ((qs.get("position") or ["WR"])[0]).upper()
            a = (qs.get("a") or [""])[0]
            b = (qs.get("b") or [""])[0]
            try:
                with LOCK:
                    result = compare(position, a, b)
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, status=400)
            return

        self.send_response(404)
        self.end_headers()


def main():
    print(f"Loading Fantasy Decision Lab v{APP_VERSION}…")
    initialize()
    for position in POSITIONS:
        st = STATE["positions"][position]
        print(
            f"{position}: {len(st['ballots'])} cached ballot sets; "
            f"{len(st['directory'])} players; {len(st['active_ids'])} active experts."
        )
    print(f"Start/Sit app: http://{HOST}:{PORT}")
    print("Press Ctrl+C in Terminal to stop it.")
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
