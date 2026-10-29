#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.20 — exact individual expert ballots for Start/Sit."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import app as legacy
import app_v03 as core
import app_v0314 as fp314
import app_v0319 as prev

APP_VERSION = "0.3.20"
ns = prev.ns
ns["APP_VERSION"] = APP_VERSION
LOCK = threading.Lock()


def _scoring_key(position: str, scoring: str) -> str:
    return "STD" if position == "QB" else core.norm_scoring(scoring)


def _expert_name(row: dict) -> str | None:
    if not isinstance(row, dict):
        return None
    return (
        row.get("name")
        or row.get("expert_name")
        or row.get("display_name")
        or row.get("full_name")
        or row.get("expert")
    )


def _extract_pair_payload(data: dict, position: str, scoring: str, aid: str, bid: str):
    """Extract exact per-expert ranks for only the selected pair."""
    key = _scoring_key(position, scoring)
    ballots = {str(aid): {}, str(bid): {}}
    names: dict[str, str] = {}

    def absorb(obj):
        if not isinstance(obj, dict):
            return

        experts = obj.get("experts")
        if isinstance(experts, dict):
            for raw_id, meta in experts.items():
                if isinstance(meta, dict):
                    eid = meta.get("expert_id") or meta.get("id") or raw_id
                    name = _expert_name(meta)
                else:
                    eid, name = raw_id, str(meta or "").strip()
                if eid is not None and name:
                    names[str(eid)] = str(name)
        elif isinstance(experts, list):
            for meta in experts:
                if not isinstance(meta, dict):
                    continue
                eid = meta.get("expert_id") or meta.get("id")
                name = _expert_name(meta)
                if eid is not None and name:
                    names[str(eid)] = str(name)

        rankings = obj.get("rankings")
        bucket = rankings.get(key) if isinstance(rankings, dict) else None
        if isinstance(bucket, dict):
            for pid in (str(aid), str(bid)):
                rows = bucket.get(pid)
                if rows is None:
                    for raw_pid, raw_rows in bucket.items():
                        if str(raw_pid) == pid:
                            rows = raw_rows
                            break
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    eid = row.get("expert_id") or row.get("id")
                    rank = row.get("rank")
                    if eid is None or rank is None:
                        continue
                    try:
                        ballots[pid][str(eid)] = float(rank)
                    except (TypeError, ValueError):
                        continue
                    name = _expert_name(row)
                    if name:
                        names[str(eid)] = str(name)

        for value in obj.values():
            if isinstance(value, dict):
                absorb(value)

    absorb(data)
    return ballots, names


def _pair_cache_path(position: str, aid: str, bid: str):
    ids = sorted([str(aid), str(bid)])
    return legacy.CACHE_ROOT / position / "compare_cache" / f"compare_{ids[0]}_{ids[1]}.json"


def _load_pair_payload(position: str, aid: str, bid: str, force: bool = False):
    """Refresh the pair transactionally, with last-known-good fallback."""
    warning = None
    cache = _pair_cache_path(position, aid, bid)
    try:
        path = legacy.fetch_pair_and_cache(position, aid, bid, force=force)
    except Exception as exc:
        if not cache.exists():
            raise
        path = cache
        warning = f"FantasyPros live ballot refresh failed; using last known-good individual ballots: {exc}"
    data = json.loads(path.read_text(encoding="utf-8"))
    return path, data, warning


def _refresh_accuracy_and_model(position: str):
    """Refresh accuracy inputs and rebuild the active weekly expert universe."""
    current = legacy.read_accuracy(2026)
    prior = legacy.read_accuracy(2025)
    core.STATE["current_accuracy"] = current
    core.STATE["prior_accuracy"] = prior
    legacy.STATE["current_accuracy"] = current
    legacy.STATE["prior_accuracy"] = prior

    core.STATE["position_models"].pop(position, None)
    legacy.STATE["positions"].pop(position, None)

    return core.build_position_model(position, force_experts=True)


def _panel(name: str, expert_ids, a_ballots, b_ballots, weights=None):
    common = [eid for eid in expert_ids if eid in a_ballots and eid in b_ballots]
    if not common:
        return {"name": name, "experts": 0, "available": False}

    ar = [a_ballots[eid] for eid in common]
    br = [b_ballots[eid] for eid in common]
    diffs = [b - a for a, b in zip(ar, br)]  # positive => A ranked higher

    if weights is None:
        ws = [1.0] * len(common)
        weighted = False
    else:
        ws = [float(weights.get(eid, 1.0)) for eid in common]
        weighted = True

    total = sum(ws)
    a_vote = sum(w for d, w in zip(diffs, ws) if d > 0)
    b_vote = sum(w for d, w in zip(diffs, ws) if d < 0)
    tie_vote = sum(w for d, w in zip(diffs, ws) if d == 0)
    a_vote += 0.5 * tie_vote
    b_vote += 0.5 * tie_vote
    a_share = a_vote / total if total else 0.5

    # 100% is only legal when every valid ballot actually agrees.
    eps = 1e-12
    if a_share >= 1.0 - eps and any(d <= 0 for d in diffs):
        raise RuntimeError("Ballot integrity check failed: A showed 100% despite a dissenting/tied ballot.")
    if a_share <= eps and any(d >= 0 for d in diffs):
        raise RuntimeError("Ballot integrity check failed: B showed 100% despite a dissenting/tied ballot.")

    a_avg = legacy.weighted_mean(ar, ws)
    b_avg = legacy.weighted_mean(br, ws)
    return {
        "name": name,
        "available": True,
        "experts": len(common),
        "weighted": weighted,
        "a_avg_rank": a_avg,
        "b_avg_rank": b_avg,
        "a_vote_share": a_share,
        "b_vote_share": 1.0 - a_share,
        "winner": "A" if a_share > 0.5 else "B" if a_share < 0.5 else ("A" if a_avg <= b_avg else "B"),
        "rank_gap": abs(a_avg - b_avg),
        "a_ballot_mass": a_vote,
        "b_ballot_mass": b_vote,
        "ties": sum(1 for d in diffs if d == 0),
    }


def exact_compare(position: str, scoring: str, a_name: str, b_name: str, force: bool = False):
    prev._sync_week()
    if position not in core.POSITIONS:
        raise ValueError("Choose QB, RB, WR, or TE.")
    scoring = core.norm_scoring(scoring)
    if position == "QB":
        scoring = "STD"

    model = core.get_model(position)
    a = core.resolve(a_name, position)
    b = core.resolve(b_name, position)
    aid, bid = str(a["player_id"]), str(b["player_id"])

    path, payload, warning = _load_pair_payload(position, aid, bid, force=force)
    ballots, payload_names = _extract_pair_payload(payload, position, scoring, aid, bid)
    a_ballots, b_ballots = ballots[aid], ballots[bid]
    common = sorted(set(a_ballots) & set(b_ballots))
    if not common:
        raise RuntimeError(
            "FantasyPros compare-players returned no common individual expert ballots for the selected matchup."
        )

    details = model.get("details") or []
    detail_by_id = {str(d.get("expert_id")): d for d in details}
    weights = {
        eid: float(detail_by_id.get(eid, {}).get("weight", 1.0))
        for eid in common
    }

    # Elite panels are accuracy-filtered, then equal-weighted. Experts without
    # a matched accuracy record remain in Full/Weighted Full at neutral weight.
    elite_order = [
        str(d.get("expert_id"))
        for d in details
        if d.get("accuracy_matched") and str(d.get("expert_id")) in common
    ]

    full = _panel("Full consensus", common, a_ballots, b_ballots)
    weighted = _panel("Weighted full", common, a_ballots, b_ballots, weights=weights)
    elite15 = _panel("Elite 15", elite_order[:15], a_ballots, b_ballots)
    elite10 = _panel("Elite 10", elite_order[:10], a_ballots, b_ballots)
    elite5 = _panel("Elite 5", elite_order[:5], a_ballots, b_ballots)
    panels = [full, weighted, elite15, elite10, elite5]

    winner_is_a = weighted["winner"] == "A"
    winner = a if winner_is_a else b
    winner_share = weighted["a_vote_share"] if winner_is_a else weighted["b_vote_share"]
    gap = weighted["rank_gap"]

    diffs = [b_ballots[eid] - a_ballots[eid] for eid in common]
    ws = [weights[eid] for eid in common]
    margin_std = legacy.weighted_std(diffs, ws)
    cp = legacy.confidence_components(winner_share, gap, margin_std)

    if cp["final"] == "TOSS-UP":
        why = "The individual expert ballots are close enough that this is effectively a coin flip."
    elif cp["final"] == "LEAN":
        why = "The individual expert ballots show a small edge, but matchup or projection context can reasonably overturn it."
    elif cp["final"] == "MODERATE":
        why = "The accuracy-weighted individual expert ballots show a meaningful preference. A contrary start needs a substantive football reason."
    else:
        why = "The accuracy-weighted individual expert ballots are strongly aligned. This should usually control absent major contextual news."

    def expert_view(d):
        eid = str(d.get("expert_id"))
        return {
            "expert_id": eid,
            "name": d.get("name") or payload_names.get(eid) or f"Expert {eid}",
            "accuracy_score": d.get("accuracy_score"),
            "accuracy_matched": bool(d.get("accuracy_matched")),
        }

    return {
        "position": position,
        "scoring": scoring,
        "player_a": a["player"],
        "team_a": a["team"],
        "player_b": b["player"],
        "team_b": b["team"],
        "recommendation": winner["player"],
        "confidence": cp["final"],
        "experts_used": len(common),
        "a_weighted_avg_rank": weighted["a_avg_rank"],
        "b_weighted_avg_rank": weighted["b_avg_rank"],
        "a_unweighted_avg_rank": full["a_avg_rank"],
        "b_unweighted_avg_rank": full["b_avg_rank"],
        "a_weighted_vote_share": weighted["a_vote_share"],
        "b_weighted_vote_share": weighted["b_vote_share"],
        "a_unweighted_vote_share": full["a_vote_share"],
        "b_unweighted_vote_share": full["b_vote_share"],
        "weighted_rank_gap": gap,
        "weighted_std_expert_margin": margin_std,
        "directional_signal": cp["direction"],
        "magnitude_signal": cp["magnitude"],
        "agreement_signal": cp["agreement"],
        "margin_stability_ratio": cp["stability_ratio"],
        "evidence_score": cp["evidence_score"],
        "panels": panels,
        "elite_experts": [expert_view(d) for d in details if str(d.get("expert_id")) in common][:15],
        "why": why,
        "last_refreshed": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone().isoformat(timespec="seconds"),
        "warning": warning,
        "source_note": (
            f"{position} Full Consensus is a literal head-to-head count of individual FantasyPros expert ballots: "
            "an expert ranking A higher contributes one A ballot, B higher contributes one B ballot, and an exact tie splits 0.5/0.5. "
            "Weighted Full uses the same ballots with accuracy-based voter weights. Elite 15/10/5 are equal-weighted ballots after "
            "filtering to the highest-rated position rankers."
        ),
    }


class Handler(prev.Handler):
    def do_GET(self):
        prev._sync_week()
        parsed = urlparse(self.path)

        if parsed.path == "/":
            self.send_html(prev.nav.home_html_v317().replace("v0.3.17", f"v{APP_VERSION}"))
            return

        if parsed.path == "/api/compare":
            q = parse_qs(parsed.query)
            position = ((q.get("position") or ["WR"])[0]).upper()
            scoring = core.norm_scoring((q.get("scoring") or ["PPR"])[0])
            try:
                with LOCK:
                    result = exact_compare(
                        position,
                        scoring,
                        (q.get("a") or [""])[0],
                        (q.get("b") or [""])[0],
                        force=False,
                    )
                self.send_json(result)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return

        return super().do_GET()

    def do_POST(self):
        prev._sync_week()
        parsed = urlparse(self.path)
        if parsed.path != "/api/refresh":
            return super().do_POST()

        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n).decode() or "{}")
            scope = str(body.get("scope") or "").lower()
            position = str(body.get("position") or "WR").upper()
            scoring = core.norm_scoring(body.get("scoring") or "PPR")
            if position == "QB":
                scoring = "STD"

            fp314.FP_SESSION["down"] = False
            fp314.FP_SESSION["detail"] = None

            with LOCK:
                if scope == "matchup":
                    _refresh_accuracy_and_model(position)
                    result = exact_compare(
                        position,
                        scoring,
                        str(body.get("a") or ""),
                        str(body.get("b") or ""),
                        force=True,
                    )
                    response = {
                        "scope": "matchup",
                        "position": position,
                        "scoring": scoring,
                        "refreshed_at": result.get("last_refreshed"),
                        "warning": result.get("warning"),
                    }
                elif scope == "position":
                    _refresh_accuracy_and_model(position)
                    response = {
                        "scope": "position",
                        "position": position,
                        "scoring": scoring,
                        "refreshed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                        "warning": None,
                    }
                elif scope == "all":
                    current = legacy.read_accuracy(2026)
                    prior = legacy.read_accuracy(2025)
                    core.STATE["current_accuracy"] = current
                    core.STATE["prior_accuracy"] = prior
                    legacy.STATE["current_accuracy"] = current
                    legacy.STATE["prior_accuracy"] = prior
                    core.STATE["position_models"].clear()
                    legacy.STATE["positions"].clear()
                    for p in core.POSITIONS:
                        core.build_position_model(p, force_experts=True)
                    response = {
                        "scope": "all",
                        "refreshed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                        "warning": None,
                    }
                else:
                    raise ValueError("Refresh scope must be matchup, position, or all.")

            self.send_json(response)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)


ns["Handler"] = Handler
prev._sync_week()

if __name__ == "__main__":
    ns["main"]()
