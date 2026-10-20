from __future__ import annotations

import json
from urllib.request import Request, urlopen

from projection_metadata import YEAR, ESPN_WEEK_URL, lookup_player, _norm_team

UA = "FantasyDecisionLab/0.2 (+local fantasy projection tool)"
STATS_URL = "https://api.sleeper.com/stats/nfl/player/{player_id}?season={year}&season_type=regular&grouping=week"
PROJECTIONS_URL = "https://api.sleeper.com/projections/nfl/player/{player_id}?season={year}&season_type=regular&grouping=week"


def _fetch_json(url: str, timeout: int = 15):
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _stat_dict(item):
    if not isinstance(item, dict):
        return {}
    if isinstance(item.get("stats"), dict):
        return item["stats"]
    return item


def _week_num(item):
    if not isinstance(item, dict):
        return 0
    try:
        return int(item.get("week") or item.get("game_week") or 0)
    except Exception:
        return 0


def _weekly_rows(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("data", "weeks", "stats", "projections"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        rows = []
        for key, value in data.items():
            if isinstance(value, dict) and str(key).isdigit():
                row = dict(value)
                row.setdefault("week", int(key))
                rows.append(row)
        return rows
    return []


def _avg(rows, key):
    vals = []
    for row in rows:
        stats = _stat_dict(row)
        try:
            value = float(stats.get(key))
            vals.append(value)
        except Exception:
            pass
    return round(sum(vals) / len(vals), 2) if vals else None


def recent_usage(player_id: str, projection_week: int) -> dict:
    try:
        data = _fetch_json(STATS_URL.format(player_id=player_id, year=YEAR), timeout=15)
        rows = [r for r in _weekly_rows(data) if 0 < _week_num(r) < projection_week]
        rows.sort(key=_week_num)
        rows = rows[-3:]
        if not rows:
            return {"status": "missing", "summary": "No recent weekly usage data returned.", "source": "Sleeper stats"}
        metrics = {
            "carries": _avg(rows, "rush_att"),
            "targets": _avg(rows, "rec_tgt"),
            "receptions": _avg(rows, "rec"),
            "rush_yards": _avg(rows, "rush_yd"),
            "rec_yards": _avg(rows, "rec_yd"),
            "snap_pct": _avg(rows, "snap_pct"),
        }
        parts = []
        for label, key in (("carries", "carries"), ("targets", "targets"), ("receptions", "receptions"), ("rush yds", "rush_yards"), ("rec yds", "rec_yards")):
            if metrics[key] is not None:
                parts.append(f"{metrics[key]} {label}")
        summary = f"Last {len(rows)} games average: " + (", ".join(parts) if parts else "weekly usage available") + "."
        return {"status": "available", "summary": summary, "metrics": metrics, "weeks": [_week_num(r) for r in rows], "source": "Sleeper stats"}
    except Exception as e:
        return {"status": "missing", "summary": "Recent usage feed unavailable.", "source": "Sleeper stats", "error": str(e)}


def market_projection(player_id: str, week: int, app_projection=None) -> dict:
    if app_projection not in (None, ""):
        try:
            value = round(float(app_projection), 2)
            return {"status": "available", "summary": f"User-supplied app projection: {value:.2f} FP.", "fp": value, "source": "User app projection"}
        except Exception:
            pass
    try:
        data = _fetch_json(PROJECTIONS_URL.format(player_id=player_id, year=YEAR), timeout=15)
        rows = _weekly_rows(data)
        row = next((r for r in rows if _week_num(r) == int(week)), None)
        if not row:
            return {"status": "missing", "summary": "No current market projection returned.", "source": "Sleeper projections"}
        stats = _stat_dict(row)
        for key in ("pts_ppr", "pts_half_ppr", "pts_std"):
            if stats.get(key) is not None:
                fp = round(float(stats[key]), 2)
                return {"status": "available", "summary": f"Sleeper {key.replace('_', ' ')} projection: {fp:.2f} FP.", "fp": fp, "source": "Sleeper projections"}
        return {"status": "partial", "summary": "Projection row is available, but no standard fantasy-point rollup was returned.", "source": "Sleeper projections"}
    except Exception as e:
        return {"status": "missing", "summary": "Market projection feed unavailable.", "source": "Sleeper projections", "error": str(e)}


def game_environment(team: str, opponent: str, week: int) -> dict:
    result = {"status": "missing", "summary": "Game environment feed unavailable.", "source": "ESPN scoreboard", "weather": {"status": "unknown", "summary": "", "affected_components": []}}
    try:
        data = _fetch_json(ESPN_WEEK_URL.format(year=YEAR, week=int(week)), timeout=15)
        for event in data.get("events") or []:
            comps = event.get("competitions") or []
            if not comps:
                continue
            comp = comps[0]
            teams = []
            for c in comp.get("competitors") or []:
                abbr = _norm_team((c.get("team") or {}).get("abbreviation"))
                if abbr:
                    teams.append(abbr)
            if _norm_team(team) not in teams:
                continue
            bits = []
            odds = comp.get("odds") or event.get("odds") or []
            if odds:
                o = odds[0] if isinstance(odds, list) else odds
                details = o.get("details") if isinstance(o, dict) else None
                over_under = o.get("overUnder") if isinstance(o, dict) else None
                if details:
                    bits.append(str(details))
                if over_under is not None:
                    bits.append(f"O/U {over_under}")
            status = "available" if bits else "partial"
            if not bits:
                bits.append(f"{team} vs {opponent or 'opponent'} is on the Week {week} schedule")
            weather = comp.get("weather") or event.get("weather") or {}
            weather_summary = ""
            if isinstance(weather, dict) and weather:
                display = weather.get("displayValue") or weather.get("conditionId") or weather.get("temperature")
                if display:
                    weather_summary = str(display)
            result = {
                "status": status,
                "summary": "; ".join(bits) + ".",
                "source": "ESPN scoreboard",
                "weather": {
                    "status": "neutral" if weather_summary else "unknown",
                    "summary": weather_summary,
                    "affected_components": [],
                },
            }
            return result
    except Exception as e:
        result["error"] = str(e)
    return result


def injury_context(meta: dict) -> dict:
    status = str(meta.get("injury_status") or "").strip()
    body = str(meta.get("injury_body_part") or "").strip()
    notes = str(meta.get("injury_notes") or "").strip()
    if status:
        detail = " · ".join(x for x in (status, body, notes) if x)
        return {"status": "available", "summary": f"Current injury designation: {detail}.", "source": "Sleeper player directory"}
    return {"status": "available", "summary": "No active injury designation in the player directory.", "source": "Sleeper player directory"}


def collect_evidence(player_name: str, week=None, app_projection=None, user_notes=None) -> dict:
    meta = lookup_player(player_name)
    if week not in (None, ""):
        try:
            meta["week"] = int(week)
        except Exception:
            pass
    usage = recent_usage(meta["player_id"], int(meta.get("week") or 0))
    env = game_environment(meta.get("team", ""), meta.get("opponent", ""), int(meta.get("week") or 0))
    injury = injury_context(meta)
    market = market_projection(meta["player_id"], int(meta.get("week") or 0), app_projection)

    evidence = {
        "role_usage": usage["status"],
        "vegas_environment": env["status"],
        "matchup_data": "partial" if meta.get("opponent") else "missing",
        "injury_context": injury["status"],
        "market_projection": market["status"],
        "coverage_scheme": "missing",
        "expert_commentary": "missing",
    }

    notes = user_notes or {}
    pillars = {
        "role_opportunity": {
            "headline": usage["summary"],
            "deep_dive": f"Source: {usage.get('source', 'unknown')}. This is an initial workload baseline; route participation, red-zone role, and teammate competition will be layered in next.",
            "user_note": str(notes.get("role_opportunity") or ""),
        },
        "game_environment": {
            "headline": env["summary"],
            "deep_dive": f"Source: {env.get('source', 'unknown')}. This first pass captures schedule/market context when available; pace and team tendency are not yet modeled.",
            "user_note": str(notes.get("game_environment") or ""),
        },
        "matchup_scheme": {
            "headline": f"Week {meta.get('week')} matchup: {meta.get('team')} vs {meta.get('opponent')}." if meta.get("opponent") else "Opponent resolved only partially; defensive matchup data is not yet attached.",
            "deep_dive": "Exact-position defensive efficiency, box/coverage tendencies, pressure, and likely primary coverage are intentionally still marked incomplete in this evidence pass.",
            "user_note": str(notes.get("matchup_scheme") or ""),
        },
        "market_expert": {
            "headline": market["summary"],
            "deep_dive": f"Source: {market.get('source', 'unknown')}. Expert commentary remains a separate missing category until a reliable ingestion path is connected.",
            "user_note": str(notes.get("market_expert") or ""),
        },
    }

    return {
        "meta": meta,
        "pillars": pillars,
        "evidence": evidence,
        "weather": env.get("weather") or {"status": "unknown", "summary": "", "affected_components": []},
        "sources": {
            "role_usage": usage,
            "game_environment": env,
            "injury_context": injury,
            "market_projection": market,
        },
    }
