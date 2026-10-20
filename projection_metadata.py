from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

YEAR = 2026
DATA_DIR = Path.home() / ".fantasy_decision_lab"
PLAYER_CACHE = DATA_DIR / "nfl_players_sleeper.json"
SCHEDULE_CACHE = DATA_DIR / "nfl_schedule_2026.json"
CACHE_SECONDS = 12 * 60 * 60
UA = "FantasyDecisionLab/0.1 (+local fantasy projection tool)"

SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
SLEEPER_STATE_URL = "https://api.sleeper.app/v1/state/nfl"
ESPN_WEEK_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={year}&seasontype=2&week={week}"

TEAM_ALIASES = {
    "WSH": "WAS",
    "JAC": "JAX",
    "LA": "LAR",
}


def _fetch_json(url: str, timeout: int = 20):
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _cache_fresh(path: Path) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < CACHE_SECONDS


def _read_cache(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(path: Path, data) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)


def player_directory(force: bool = False) -> list[dict]:
    raw = None
    if not force and _cache_fresh(PLAYER_CACHE):
        raw = _read_cache(PLAYER_CACHE)
    if raw is None:
        try:
            raw = _fetch_json(SLEEPER_PLAYERS_URL, timeout=30)
            _write_cache(PLAYER_CACHE, raw)
        except Exception:
            raw = _read_cache(PLAYER_CACHE)
            if raw is None:
                raise

    players = []
    for player_id, item in (raw or {}).items():
        if not isinstance(item, dict):
            continue
        position = str(item.get("position") or "").upper()
        if position not in {"QB", "RB", "WR", "TE"}:
            continue
        team = str(item.get("team") or "").upper().strip()
        name = str(item.get("full_name") or item.get("search_full_name") or "").strip()
        if not name or not team:
            continue
        if item.get("active") is False:
            continue
        players.append({
            "player_id": str(player_id),
            "player": name,
            "team": team,
            "position": position,
        })
    players.sort(key=lambda p: p["player"].lower())
    return players


def projection_week() -> int:
    try:
        state = _fetch_json(SLEEPER_STATE_URL, timeout=10)
        current = int(state.get("week") or 0)
        if 1 <= current <= 18:
            # Sleeper generally advances the state to the new week after Monday.
            # On Monday, project the next week; Tuesday-Sunday, use the state week.
            if datetime.now().weekday() == 0 and current < 18:
                return current + 1
            return current
    except Exception:
        pass
    # 2026 pilot fallback. Week remains editable in the UI.
    return 7


def _norm_team(value: str) -> str:
    value = str(value or "").upper().strip()
    return TEAM_ALIASES.get(value, value)


def week_schedule(week: int, force: bool = False) -> dict[str, str]:
    cache = _read_cache(SCHEDULE_CACHE) or {}
    key = str(int(week))
    cached_week = cache.get(key) if isinstance(cache, dict) else None
    cache_age_ok = _cache_fresh(SCHEDULE_CACHE)
    if cached_week and not force and cache_age_ok:
        return cached_week

    try:
        data = _fetch_json(ESPN_WEEK_URL.format(year=YEAR, week=int(week)), timeout=20)
        opponents: dict[str, str] = {}
        for event in data.get("events") or []:
            competitions = event.get("competitions") or []
            if not competitions:
                continue
            competitors = competitions[0].get("competitors") or []
            teams = []
            for competitor in competitors:
                team = competitor.get("team") or {}
                abbreviation = _norm_team(team.get("abbreviation"))
                if abbreviation:
                    teams.append(abbreviation)
            if len(teams) == 2:
                opponents[teams[0]] = teams[1]
                opponents[teams[1]] = teams[0]
        if opponents:
            if not isinstance(cache, dict):
                cache = {}
            cache[key] = opponents
            _write_cache(SCHEDULE_CACHE, cache)
            return opponents
    except Exception:
        pass

    return cached_week or {}


def lookup_player(name: str) -> dict:
    query = " ".join(str(name or "").lower().split())
    if not query:
        raise ValueError("Player is required.")
    players = player_directory()
    exact = [p for p in players if " ".join(p["player"].lower().split()) == query]
    if len(exact) == 1:
        player = exact[0]
    else:
        contains = [p for p in players if query in p["player"].lower()]
        if len(contains) != 1:
            raise ValueError(f"Could not uniquely resolve player: {name}")
        player = contains[0]

    week = projection_week()
    schedule = week_schedule(week)
    opponent = schedule.get(_norm_team(player["team"]), "")
    return {
        **player,
        "week": week,
        "opponent": opponent,
        "metadata_status": "complete" if opponent else "partial",
    }
