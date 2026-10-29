#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.21 — ballot-native Elite panels for Start/Sit."""
from __future__ import annotations

import app_v0320 as prev20

APP_VERSION = "0.3.21"
prev20.APP_VERSION = APP_VERSION
ns = prev20.ns
ns["APP_VERSION"] = APP_VERSION

legacy = prev20.legacy
core = prev20.core


def _ballot_accuracy_details(position: str, common: list[str], payload_names: dict[str, str], model_details: list[dict]):
    """Score the actual matchup voters, not a separate weekly expert-ID universe."""
    core.ensure_accuracy_loaded()
    current = core.STATE["current_accuracy"]
    prior = core.STATE["prior_accuracy"]

    current_lookup = {r["NORM_NAME"]: r for _, r in current.iterrows()}
    prior_lookup = {r["NORM_NAME"]: r for _, r in prior.iterrows()}
    populations = {
        "cur_pos": int(core.pd.to_numeric(current[position], errors="coerce").notna().sum()),
        "cur_all": int(core.pd.to_numeric(current["RANK"], errors="coerce").notna().sum()),
        "prev_pos": int(core.pd.to_numeric(prior[position], errors="coerce").notna().sum()),
        "prev_all": int(core.pd.to_numeric(prior["RANK"], errors="coerce").notna().sum()),
    }

    model_by_id = {str(d.get("expert_id")): d for d in (model_details or [])}
    directory_names = {}
    try:
        directory_names.update(core.load_expert_names(force=False))
    except Exception:
        pass

    details = []
    for eid in common:
        fallback = model_by_id.get(eid, {})
        name = (
            payload_names.get(eid)
            or directory_names.get(eid)
            or fallback.get("name")
            or f"Expert {eid}"
        )
        normalized = legacy.norm_name(name)
        cur = current_lookup.get(normalized)
        prev = prior_lookup.get(normalized)

        values = {
            "cur_pos": cur[position] if cur is not None else None,
            "cur_all": cur["RANK"] if cur is not None else None,
            "prev_pos": prev[position] if prev is not None else None,
            "prev_all": prev["RANK"] if prev is not None else None,
        }

        numerator = 0.0
        denominator = 0.0
        for key, coefficient in legacy.FORMULA.items():
            score = legacy.percentile_score(values[key], populations[key])
            if score is not None:
                numerator += coefficient * score
                denominator += coefficient

        matched = denominator > 0
        if matched:
            accuracy_score = numerator / denominator
            weight = 0.75 + 0.65 * accuracy_score
        else:
            accuracy_score = 0.5
            weight = 1.0

        details.append({
            "expert_id": eid,
            "name": name,
            "accuracy_score": accuracy_score,
            "weight": weight,
            "accuracy_matched": matched,
            **values,
        })

    # Elite selection uses only experts whose accuracy record could actually be
    # joined. Full/Weighted Full retain every valid ballot; unmatched voters get
    # neutral weight in Weighted Full.
    details.sort(
        key=lambda d: (bool(d["accuracy_matched"]), float(d["accuracy_score"]), float(d["weight"])),
        reverse=True,
    )
    return details


def exact_compare_v321(position: str, scoring: str, a_name: str, b_name: str, force: bool = False):
    prev20.prev._sync_week()
    if position not in core.POSITIONS:
        raise ValueError("Choose QB, RB, WR, or TE.")
    scoring = core.norm_scoring(scoring)
    if position == "QB":
        scoring = "STD"

    model = core.get_model(position)
    a = core.resolve(a_name, position)
    b = core.resolve(b_name, position)
    aid, bid = str(a["player_id"]), str(b["player_id"])

    path, payload, warning = prev20._load_pair_payload(position, aid, bid, force=force)
    ballots, payload_names = prev20._extract_pair_payload(payload, position, scoring, aid, bid)
    a_ballots, b_ballots = ballots[aid], ballots[bid]
    common = sorted(set(a_ballots) & set(b_ballots))
    if not common:
        raise RuntimeError(
            "FantasyPros compare-players returned no common individual expert ballots for the selected matchup."
        )

    ballot_details = _ballot_accuracy_details(
        position,
        common,
        payload_names,
        model.get("details") or [],
    )
    detail_by_id = {d["expert_id"]: d for d in ballot_details}
    weights = {eid: float(detail_by_id[eid]["weight"]) for eid in common}
    elite_order = [d["expert_id"] for d in ballot_details if d["accuracy_matched"]]

    full = prev20._panel("Full consensus", common, a_ballots, b_ballots)
    weighted = prev20._panel("Weighted full", common, a_ballots, b_ballots, weights=weights)
    elite15 = prev20._panel("Elite 15", elite_order[:15], a_ballots, b_ballots)
    elite10 = prev20._panel("Elite 10", elite_order[:10], a_ballots, b_ballots)
    elite5 = prev20._panel("Elite 5", elite_order[:5], a_ballots, b_ballots)
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
        "accuracy_matched_experts": len(elite_order),
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
        "elite_experts": [
            {
                "expert_id": d["expert_id"],
                "name": d["name"],
                "accuracy_score": d["accuracy_score"],
                "accuracy_matched": d["accuracy_matched"],
            }
            for d in ballot_details
            if d["accuracy_matched"]
        ][:15],
        "why": why,
        "last_refreshed": prev20.datetime.fromtimestamp(
            path.stat().st_mtime, tz=prev20.timezone.utc
        ).astimezone().isoformat(timespec="seconds"),
        "warning": warning,
        "source_note": (
            f"{position} Full Consensus is a literal head-to-head count of individual FantasyPros expert ballots. "
            "Weighted Full uses the same matchup voters with accuracy-based weights computed from the local 2026/2025 accuracy files. "
            "Elite 15/10/5 are equal-weighted ballots from the highest-rated position experts among those exact matchup voters; "
            "the Elite pool no longer depends on a separate FantasyPros weekly expert-ID join."
        ),
    }


# The inherited v0.3.20 HTTP handler resolves this module global dynamically.
prev20.exact_compare = exact_compare_v321
ns["Handler"] = prev20.Handler

if __name__ == "__main__":
    ns["main"]()
