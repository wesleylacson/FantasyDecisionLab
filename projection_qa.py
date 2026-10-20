from __future__ import annotations

from typing import Any

PILLARS = ("role_opportunity", "game_environment", "matchup_scheme", "market_expert")


def scenarios() -> list[dict[str, str]]:
    return [
        {"id": "normal", "label": "Normal projection"},
        {"id": "missing_evidence", "label": "Partial / missing evidence"},
        {"id": "high_projection", "label": "Extreme projection"},
        {"id": "long_headlines", "label": "Long headline stress test"},
        {"id": "error", "label": "API error"},
        {"id": "replay_last_real", "label": "Replay last real run"},
    ]


def _position(payload: dict) -> str:
    return str(payload.get("position") or "RB").upper()


def _stats(position: str, scenario: str) -> dict[str, float]:
    if position == "QB":
        return {
            "pass_yards": 248.0,
            "pass_tds": 1.65,
            "interceptions": 0.75,
            "qb_rush_yards": 31.0,
            "qb_rush_tds": 0.18,
            "carries": 0.0,
            "rush_yards": 0.0,
            "rush_tds": 0.0,
            "rush_first_downs": 0.0,
            "targets": 0.0,
            "receptions": 0.0,
            "rec_yards": 0.0,
            "rec_tds": 0.0,
            "rec_first_downs": 0.0,
        }
    if position in {"WR", "TE"}:
        base = {
            "carries": 0.4,
            "rush_yards": 2.8,
            "rush_tds": 0.02,
            "rush_first_downs": 0.15,
            "targets": 8.7,
            "receptions": 5.8,
            "rec_yards": 72.0,
            "rec_tds": 0.46,
            "rec_first_downs": 3.5,
        }
        if scenario == "high_projection":
            base.update({"targets": 13.2, "receptions": 9.4, "rec_yards": 128.0, "rec_tds": 0.82, "rec_first_downs": 5.7})
        return {**base, "pass_yards": 0.0, "pass_tds": 0.0, "interceptions": 0.0, "qb_rush_yards": 0.0, "qb_rush_tds": 0.0}
    base = {
        "carries": 14.8,
        "rush_yards": 61.0,
        "rush_tds": 0.48,
        "rush_first_downs": 3.4,
        "targets": 3.6,
        "receptions": 2.8,
        "rec_yards": 20.0,
        "rec_tds": 0.08,
        "rec_first_downs": 1.15,
    }
    if scenario == "high_projection":
        base.update({"carries": 22.0, "rush_yards": 105.0, "rush_tds": 0.95, "targets": 5.8, "receptions": 4.7, "rec_yards": 39.0, "rec_tds": 0.18})
    return {**base, "pass_yards": 0.0, "pass_tds": 0.0, "interceptions": 0.0, "qb_rush_yards": 0.0, "qb_rush_tds": 0.0}


def _headlines(scenario: str) -> dict[str, dict[str, str]]:
    if scenario == "long_headlines":
        return {
            "role_opportunity": {"headline": "The workload is stable enough to support a usable median, but recent touch volume contains competing signals from passing-down rotation, short-yardage deployment, teammate availability, and a late-game script that should not all be projected forward at full strength."},
            "game_environment": {"headline": "The game environment is broadly neutral, with enough scoring expectation to preserve touchdown equity but not enough pace or spread pressure to justify an aggressive volume ceiling without additional evidence."},
            "matchup_scheme": {"headline": "The opponent presents a mixed schematic profile: favorable tendencies in one phase are offset by stronger early-down efficiency and enough front variability that the projection should remain close to the player's stable baseline."},
            "market_expert": {"headline": "The app prior is useful and directionally credible, while the fixture intentionally preserves a small disagreement so the UI can display model-versus-market context without overwhelming the main result."},
        }
    return {
        "role_opportunity": {"headline": "Stable recent role, regressed toward the season baseline rather than extrapolating the latest game."},
        "game_environment": {"headline": "Neutral game environment with ordinary scoring and script assumptions."},
        "matchup_scheme": {"headline": "Mixed matchup; no schematic factor is strong enough to overwhelm the player's baseline role."},
        "market_expert": {"headline": "Projection stays near the app prior while preserving a modest independent disagreement."},
    }


def fixture_projection(payload: dict, scenario: str = "normal") -> dict[str, Any]:
    if scenario == "error":
        raise RuntimeError("QA fixture: simulated projection API failure.")
    position = _position(payload)
    missing = scenario == "missing_evidence"
    evidence = {
        "role_usage": "available",
        "vegas_environment": "partial" if missing else "available",
        "matchup_data": "partial" if missing else "available",
        "injury_context": "available",
        "market_projection": "available",
        "coverage_scheme": "missing" if missing else "available",
        "expert_commentary": "missing" if missing else "partial",
    }
    app = float(payload.get("app_projected_fp") or 15.0)
    return {
        "stats": _stats(position, scenario),
        "floor_fp": round(max(0.0, app * 0.58), 1),
        "ceiling_fp": round(app * (1.75 if scenario == "high_projection" else 1.55), 1),
        "pillars": _headlines(scenario),
        "evidence": evidence,
        "projection_summary": "QA fixture response. No external API or web search was used.",
        "app_disagreement": "Fixture output intentionally stays close enough to the supplied app projection to exercise comparison UI.",
        "ai_meta": {
            "model": "qa-fixture",
            "response_id": f"qa-{scenario}",
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "web_search_calls": 0,
            "sources": [],
            "knowledge_items": 0,
            "qa_scenario": scenario,
        },
    }


def replay_projection(record: dict) -> dict[str, Any]:
    position = str(record.get("position") or "RB").upper()
    saved = dict(record.get("stats") or {})
    if position == "QB":
        stats = {
            "carries": 0.0, "rush_yards": 0.0, "rush_tds": 0.0, "rush_first_downs": 0.0,
            "targets": 0.0, "receptions": 0.0, "rec_yards": 0.0, "rec_tds": 0.0, "rec_first_downs": 0.0,
            "pass_yards": saved.get("pass_yards", 0.0), "pass_tds": saved.get("pass_tds", 0.0),
            "interceptions": saved.get("interceptions", 0.0), "qb_rush_yards": saved.get("rush_yards", 0.0),
            "qb_rush_tds": saved.get("rush_tds", 0.0),
        }
    else:
        stats = {k: saved.get(k, 0.0) for k in ["carries", "rush_yards", "rush_tds", "rush_first_downs", "targets", "receptions", "rec_yards", "rec_tds", "rec_first_downs"]}
        stats.update({"pass_yards": 0.0, "pass_tds": 0.0, "interceptions": 0.0, "qb_rush_yards": 0.0, "qb_rush_tds": 0.0})
    pillars = {}
    for key in PILLARS:
        src = ((record.get("pillars") or {}).get(key) or {})
        pillars[key] = {"headline": src.get("headline") or "Replayed saved headline."}
    meta = dict(record.get("ai_meta") or {})
    meta.update({"model": "qa-replay", "web_search_calls": 0, "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, "qa_scenario": "replay_last_real"})
    return {
        "stats": stats,
        "floor_fp": record.get("floor_fp"),
        "ceiling_fp": record.get("ceiling_fp"),
        "pillars": pillars,
        "evidence": record.get("evidence") or {},
        "projection_summary": record.get("projection_summary") or "Replayed saved real projection.",
        "app_disagreement": "Replayed from a prior real projection; no paid request was made.",
        "ai_meta": meta,
    }


def fixture_deep_dive(record: dict, pillar_key: str) -> dict[str, Any]:
    label = pillar_key.replace("_", " ").title()
    return {
        "text": f"QA deep dive for {label}. This text is intentionally served from a fixture with no model or web call. It exercises the lazy-loading state, expanded layout, persistence path, and longer explanatory copy without incurring API cost. The saved headline and user context would normally anchor this explanation, while the production path uses the original projection's stored sources rather than launching another web search.",
        "meta": {"model": "qa-fixture", "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, "web_search_calls": 0},
    }
