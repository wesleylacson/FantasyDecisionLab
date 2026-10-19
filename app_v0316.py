#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.16 — harden FantasyPros expert matching and fallback HTTP."""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime

import pandas as pd
import requests

import app_v0315 as prev

APP_VERSION = "0.3.16"
ns = prev.ns
ns["APP_VERSION"] = APP_VERSION

fp038 = ns["base"]
fp035 = fp038.base.base.base
core = fp035.compare_base.core
legacy = fp035.legacy


def _fp_headers(key: str) -> dict:
    return {
        "x-api-key": key,
        "User-Agent": "FantasyDecisionLab/0.3.16",
        "Accept": "application/json",
    }


# Use the same request shape that passed the standalone diagnostic. In
# particular, send an explicit Accept + User-Agent and retry transient gateway
# failures rather than treating the first CloudFront 502 as authoritative.
def api_get_v316(url: str, params: dict, attempts: int = 4) -> dict:
    key = legacy.get_api_key()
    if not key:
        raise RuntimeError(
            "FantasyPros API key is not configured. Double-click First-time Setup.command in the app folder."
        )
    delay = 1
    last_status = None
    last_body = ""
    for attempt in range(max(1, attempts)):
        try:
            r = requests.get(
                url,
                params=params,
                headers=_fp_headers(key),
                timeout=40,
            )
        except requests.RequestException as exc:
            if attempt == max(1, attempts) - 1:
                raise RuntimeError(f"FantasyPros request failed after retries: {exc}")
            time.sleep(delay)
            delay *= 2
            continue
        last_status = r.status_code
        last_body = r.text[:180]
        if r.status_code == 200:
            return r.json()
        if r.status_code in {429, 500, 502, 503, 504}:
            if attempt < max(1, attempts) - 1:
                time.sleep(delay)
                delay *= 2
                continue
            break
        raise RuntimeError(
            f"FantasyPros rankings request failed with HTTP {r.status_code}: {last_body}"
        )
    raise RuntimeError(
        f"FantasyPros rankings service is temporarily unavailable after automatic retries (HTTP {last_status})."
    )


core.api_get = api_get_v316


def _split_expert_ids(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x for x in re.split(r"[,\s:]+", str(value or "")) if x]


def _expert_name(e: dict):
    if not isinstance(e, dict):
        return None
    return (
        e.get("name")
        or e.get("expert_name")
        or e.get("display_name")
        or e.get("full_name")
        or e.get("expert")
    )


def _expert_map_from_consensus(data: dict) -> dict[str, str]:
    out: dict[str, str] = {}

    def absorb(obj):
        if not isinstance(obj, dict):
            return
        experts = obj.get("experts")
        if isinstance(experts, dict):
            for key, val in experts.items():
                if isinstance(val, dict):
                    eid = val.get("expert_id") or val.get("id") or key
                    name = _expert_name(val)
                else:
                    eid, name = key, str(val or "").strip()
                if eid is not None and name:
                    out[str(eid)] = str(name)
        elif isinstance(experts, list):
            for val in experts:
                if not isinstance(val, dict):
                    continue
                eid = val.get("expert_id") or val.get("id")
                name = _expert_name(val)
                if eid is not None and name:
                    out[str(eid)] = str(name)
        for val in obj.values():
            if isinstance(val, dict):
                absorb(val)

    absorb(data)
    return out


def _weekly_expert_snapshot(position: str):
    # The consensus endpoint is authoritative for the expert pool it will
    # actually rank. This avoids joining IDs scraped from a separate webpage
    # against API metadata from a different surface.
    params = {
        "position": position,
        "scoring": "STD" if position == "QB" else "PPR",
        "week": core.WEEK,
        "experts": "show",
    }
    data = core.api_get(core.CONSENSUS_URL, params, attempts=3)
    ids = _split_expert_ids(data.get("filters"))
    names = _expert_map_from_consensus(data)
    if not ids and names:
        ids = list(names)
    return data, ids, names


def build_position_model_v316(position: str, force_experts=False):
    core.ensure_accuracy_loaded()
    directory, _webpage_ids = legacy.load_position_directory(position)
    _snapshot, active_ids, consensus_names = _weekly_expert_snapshot(position)

    # Merge the general expert directory as a secondary name source, but let
    # the weekly consensus response win when it contains a name itself.
    names = {}
    try:
        names.update(core.load_expert_names(force=force_experts))
    except Exception:
        pass
    names.update(consensus_names)

    cur, prior = core.STATE["current_accuracy"], core.STATE["prior_accuracy"]
    cur_lookup = {r["NORM_NAME"]: r for _, r in cur.iterrows()}
    prev_lookup = {r["NORM_NAME"]: r for _, r in prior.iterrows()}
    pops = {
        "cur_pos": int(pd.to_numeric(cur[position], errors="coerce").notna().sum()),
        "cur_all": int(pd.to_numeric(cur["RANK"], errors="coerce").notna().sum()),
        "prev_pos": int(pd.to_numeric(prior[position], errors="coerce").notna().sum()),
        "prev_all": int(pd.to_numeric(prior["RANK"], errors="coerce").notna().sum()),
    }

    details = []
    matched_count = 0
    for eid in active_ids:
        name = names.get(str(eid))
        norm = legacy.norm_name(name) if name else ""
        c = cur_lookup.get(norm) if norm else None
        p = prev_lookup.get(norm) if norm else None
        matched = c is not None or p is not None
        if matched:
            matched_count += 1

        vals = {
            "cur_pos": c[position] if c is not None else None,
            "cur_all": c["RANK"] if c is not None else None,
            "prev_pos": p[position] if p is not None else None,
            "prev_all": p["RANK"] if p is not None else None,
        }
        num = den = 0.0
        for key, coef in legacy.FORMULA.items():
            score = legacy.percentile_score(vals[key], pops[key])
            if score is not None:
                num += coef * score
                den += coef

        # Missing accuracy metadata is not an outage. Keep that active expert
        # in the consensus with a neutral 1.0 weight instead of throwing away
        # the entire FantasyPros source.
        if den:
            accuracy_score = num / den
            weight = 0.75 + 0.65 * accuracy_score
        else:
            accuracy_score = 0.5
            weight = 1.0

        details.append(
            {
                "expert_id": str(eid),
                "name": name or f"Expert {eid}",
                "accuracy_score": accuracy_score,
                "weight": weight,
                "accuracy_matched": matched,
            }
        )

    if not details:
        raise RuntimeError(
            f"FantasyPros weekly consensus returned no active {position} experts."
        )

    # Known accuracy records lead the elite ordering. Unmatched experts remain
    # in the full consensus at neutral weight rather than causing a hard fail.
    details.sort(
        key=lambda x: (x["accuracy_matched"], x["accuracy_score"], x["weight"]),
        reverse=True,
    )
    model = {
        "position": position,
        "directory": directory,
        "active_ids": [d["expert_id"] for d in details],
        "details": details,
        "weights": {d["expert_id"]: d["weight"] for d in details},
        "accuracy_matched_count": matched_count,
        "refreshed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    core.STATE["position_models"][position] = model
    return model


core.build_position_model = build_position_model_v316


# Harden the legacy compare-players fallback with the same successful request
# headers and transient-error handling as the grouped rankings path.
def fetch_pair_and_cache_v316(position: str, aid: str, bid: str, force: bool = False):
    key = legacy.get_api_key()
    if not key:
        raise RuntimeError(
            "FantasyPros API key is not configured. Double-click First-time Setup.command in the app folder."
        )

    live_cache = legacy.CACHE_ROOT / position / "compare_cache"
    live_cache.mkdir(parents=True, exist_ok=True)
    ids = sorted([str(aid), str(bid)])
    cache = live_cache / f"compare_{ids[0]}_{ids[1]}.json"
    if cache.exists() and not force:
        return cache

    params = {
        "players": f"{aid}:{bid}",
        "position": position,
        "year": legacy.YEAR,
        "week": legacy.WEEK,
        "ranking_type": "weekly",
        "details": "all",
    }
    delay = 1
    last_status = None
    last_body = ""
    for attempt in range(4):
        try:
            r = requests.get(
                legacy.COMPARE_URL,
                params=params,
                headers=_fp_headers(key),
                timeout=30,
            )
        except requests.RequestException as exc:
            if attempt == 3:
                raise RuntimeError(f"FantasyPros Compare request failed after retries: {exc}")
            time.sleep(delay)
            delay *= 2
            continue
        last_status = r.status_code
        last_body = r.text[:200]
        if r.status_code == 200:
            tmp = cache.with_suffix(cache.suffix + ".tmp")
            tmp.write_text(json.dumps(r.json(), indent=2), encoding="utf-8")
            tmp.replace(cache)
            return cache
        if r.status_code in {429, 500, 502, 503, 504} and attempt < 3:
            time.sleep(delay)
            delay *= 2
            continue
        break
    raise RuntimeError(
        f"FantasyPros Compare request failed with HTTP {last_status}: {last_body}"
    )


legacy.fetch_pair_and_cache = fetch_pair_and_cache_v316

# Any model cached during import would predate these fixes; rebuild lazily.
core.STATE["position_models"].clear()

OldHandler = ns["Handler"]


class Handler(OldHandler):
    def do_GET(self):
        if self.path == "/":
            home = fp035.compare_base.core.ui.HOME_HTML.replace("v0.2 ·", "v0.3.16 ·")
            self.send_html(home)
            return
        return super().do_GET()


ns["Handler"] = Handler

if __name__ == "__main__":
    ns["main"]()
