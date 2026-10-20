from __future__ import annotations

import math
import re


def _num(value, default=0.0):
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _round_stat(value, digits=2):
    return round(max(0.0, _num(value)), digits)


def _market_calibration(base_fp: float, market_fp):
    if market_fp in (None, "") or base_fp <= 0:
        return 1.0
    try:
        target = float(market_fp)
    except Exception:
        return 1.0
    raw = target / base_fp
    # The market is an anchor, not the model. Only permit a modest efficiency/TD nudge.
    return max(0.88, min(1.12, 1.0 + (raw - 1.0) * 0.35))


def _environment_multiplier(env: dict) -> float:
    total = env.get("over_under") if isinstance(env, dict) else None
    try:
        total = float(total)
    except Exception:
        return 1.0
    # Neutral around 44. Each 6 points of game total moves scoring efficiency ~3%, capped.
    return max(0.94, min(1.06, 1.0 + (total - 44.0) * 0.005))


def _skill_projection(metrics: dict, env_mult: float) -> dict:
    carries = _num(metrics.get("carries"))
    targets = _num(metrics.get("targets"))
    receptions = _num(metrics.get("receptions"))
    rush_yards = _num(metrics.get("rush_yards"))
    rec_yards = _num(metrics.get("rec_yards"))
    rush_tds = _num(metrics.get("rush_tds"))
    rec_tds = _num(metrics.get("rec_tds"))
    rush_fd = metrics.get("rush_first_downs")
    rec_fd = metrics.get("rec_first_downs")

    # Preserve volume from recent usage; move efficiency and scoring for environment.
    stats = {
        "carries": _round_stat(carries, 1),
        "targets": _round_stat(targets, 1),
        "receptions": _round_stat(receptions, 1),
        "rush_yards": _round_stat(rush_yards * env_mult, 1),
        "rec_yards": _round_stat(rec_yards * env_mult, 1),
        "rush_tds": _round_stat(rush_tds * env_mult, 2),
        "rec_tds": _round_stat(rec_tds * env_mult, 2),
        "rush_first_downs": _round_stat(_num(rush_fd, carries * 0.24), 1),
        "rec_first_downs": _round_stat(_num(rec_fd, receptions * 0.48), 1),
    }
    return stats


def _qb_projection(metrics: dict, env_mult: float) -> dict:
    return {
        "pass_yards": _round_stat(_num(metrics.get("pass_yards")) * env_mult, 0),
        "pass_tds": _round_stat(_num(metrics.get("pass_tds")) * env_mult, 2),
        "interceptions": _round_stat(_num(metrics.get("interceptions")), 2),
        "rush_yards": _round_stat(_num(metrics.get("rush_yards")), 1),
        "rush_tds": _round_stat(_num(metrics.get("rush_tds")) * env_mult, 2),
    }


def _fp(position: str, stats: dict, scoring: dict) -> float:
    if position == "QB":
        return (
            _num(stats.get("pass_yards")) * _num(scoring.get("pass_yd"), 0.04)
            + _num(stats.get("pass_tds")) * _num(scoring.get("pass_td"), 4)
            + _num(stats.get("interceptions")) * _num(scoring.get("interception"), -2)
            + _num(stats.get("rush_yards")) * _num(scoring.get("rush_yd"), 0.1)
            + _num(stats.get("rush_tds")) * _num(scoring.get("rush_td"), 6)
        )
    return (
        _num(stats.get("rush_yards")) * _num(scoring.get("rush_yd"), 0.1)
        + _num(stats.get("rush_tds")) * _num(scoring.get("rush_td"), 6)
        + _num(stats.get("receptions")) * _num(scoring.get("ppr"))
        + _num(stats.get("rec_yards")) * _num(scoring.get("rec_yd"), 0.1)
        + _num(stats.get("rec_tds")) * _num(scoring.get("rec_td"), 6)
        + (_num(stats.get("rush_first_downs")) + _num(stats.get("rec_first_downs"))) * _num(scoring.get("ppfd"))
    )


def _apply_calibration(position: str, stats: dict, factor: float) -> dict:
    if abs(factor - 1.0) < 0.001:
        return stats
    out = dict(stats)
    if position == "QB":
        for key in ("pass_yards", "pass_tds", "rush_tds"):
            out[key] = _round_stat(_num(out.get(key)) * factor, 2 if "td" in key else 0)
    else:
        # Keep opportunity intact. Calibrate conversion/efficiency only.
        for key in ("rush_yards", "rec_yards"):
            out[key] = _round_stat(_num(out.get(key)) * factor, 1)
        for key in ("rush_tds", "rec_tds"):
            out[key] = _round_stat(_num(out.get(key)) * factor, 2)
    return out


def build_projection(research: dict, scoring: dict) -> dict:
    meta = research.get("meta") or {}
    position = str(meta.get("position") or "RB").upper()
    sources = research.get("sources") or {}
    usage = sources.get("role_usage") or {}
    env = sources.get("game_environment") or {}
    market = sources.get("market_projection") or {}
    metrics = usage.get("metrics") or {}

    env_mult = _environment_multiplier(env)
    stats = _qb_projection(metrics, env_mult) if position == "QB" else _skill_projection(metrics, env_mult)
    base_fp = _fp(position, stats, scoring)
    market_fp = market.get("fp")
    calibration = _market_calibration(base_fp, market_fp)
    stats = _apply_calibration(position, stats, calibration)
    final_fp = _fp(position, stats, scoring)

    # Keep uncertainty broad in v1; these are display bands, not probabilistic intervals yet.
    floor = round(max(0.0, final_fp * 0.68), 1)
    ceiling = round(final_fp * 1.42, 1)

    method = (
        "Recent three-game usage establishes volume and efficiency; game total applies a bounded "
        "environment multiplier; market projection applies a bounded calibration to efficiency/TD conversion."
    )
    diagnostics = {
        "environment_multiplier": round(env_mult, 3),
        "market_calibration": round(calibration, 3),
        "market_fp": market_fp,
        "baseline_fp_before_market": round(base_fp, 2),
        "final_fp": round(final_fp, 2),
    }
    return {"stats": stats, "floor_fp": floor, "ceiling_fp": ceiling, "method": method, "diagnostics": diagnostics}
