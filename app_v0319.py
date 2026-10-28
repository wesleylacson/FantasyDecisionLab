#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.19 — dynamic NFL week + week-aware player directory cache."""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

import app as legacy
import app_v03 as core
import app_v033 as picker
import app_v035 as fp035
import app_v036 as fp036
import app_v0314 as fp314
import app_v0317 as nav
import app_v0318 as prev

APP_VERSION = "0.3.19"
YEAR = 2026
DIRECTORY_TTL_SECONDS = 60 * 60

ns = prev.ns
ns["APP_VERSION"] = APP_VERSION

# Fantasy Week 1 prep starts Tuesday, Sept. 8, one day before the 2026
# Wednesday kickoff. Advancing on Tuesday matches the fantasy workflow:
# after MNF, the app should immediately point at the upcoming week's rankings.
WEEK_1_ROLLOVER = date(2026, 9, 8)


def _detected_week(today: date | None = None) -> int:
    override = str(os.environ.get("FANTASY_NFL_WEEK") or "").strip()
    if override:
        try:
            week = int(override)
        except ValueError as exc:
            raise RuntimeError("FANTASY_NFL_WEEK must be an integer from 1 to 18.") from exc
        if not 1 <= week <= 18:
            raise RuntimeError("FANTASY_NFL_WEEK must be an integer from 1 to 18.")
        return week

    today = today or datetime.now().astimezone().date()
    week = ((today - WEEK_1_ROLLOVER).days // 7) + 1
    return max(1, min(18, week))


def _sync_week() -> int:
    """Keep every inherited Start/Sit backend on the same active NFL week."""
    week = _detected_week()
    old_week = int(getattr(core, "WEEK", week))
    changed = old_week != week

    legacy.YEAR = YEAR
    legacy.WEEK = week
    core.YEAR = YEAR
    core.WEEK = week

    if changed:
        # Models/directories are week-sensitive. Clear only in-memory state;
        # disk caches remain available under their week-specific paths.
        core.STATE["position_models"].clear()
        picker.DIRECTORIES.clear()
        fp035.LEGACY_READY.clear()
        fp036.PUBLIC_DIRS.clear()
        legacy.STATE["positions"].clear()

        # A FantasyPros outage circuit breaker should not carry into a new week.
        fp314.FP_SESSION["down"] = False
        fp314.FP_SESSION["detail"] = None

    return week


def _directory_cache_path(position: str, scoring: str) -> Path:
    scoring = core.norm_scoring(scoring)
    return (
        core.BACKEND_CACHE
        / "player_directories"
        / str(YEAR)
        / f"week_{core.WEEK}"
        / scoring
        / f"{position}.json"
    )


def _load_cached_directory(path: Path):
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        df = core.pd.DataFrame(rows)
        return df if not df.empty else None
    except Exception:
        return None


def get_player_directory_v319(position: str, scoring: str | None = None, force: bool = False):
    """Return a fresh-enough, week/scoring-specific public player directory.

    The previous cache key was only ``RB.json``/``WR.json`` etc., which could
    strand newly relevant players in an older week's autocomplete list. This
    cache is scoped by year/week/scoring and refreshes hourly while preserving
    the last-known-good file if FantasyPros' public page is unavailable.
    """
    _sync_week()
    scoring = core.norm_scoring(scoring or getattr(legacy, "SCORING", "PPR"))
    if position == "QB":
        scoring = "STD"

    key = (YEAR, core.WEEK, scoring, position)
    path = _directory_cache_path(position, scoring)
    age = None
    if path.exists():
        age = max(0.0, datetime.now().timestamp() - path.stat().st_mtime)

    # In-memory data is only trusted while the backing week-specific snapshot
    # is still inside the refresh TTL. This lets a long-running app discover
    # midweek risers without requiring a restart.
    if (
        not force
        and key in picker.DIRECTORIES
        and age is not None
        and age <= DIRECTORY_TTL_SECONDS
    ):
        return picker.DIRECTORIES[key]

    cached = _load_cached_directory(path) if path.exists() else None
    if cached is not None and not force and age is not None and age <= DIRECTORY_TTL_SECONDS:
        picker.DIRECTORIES[key] = cached
        return cached

    old_scoring = getattr(legacy, "SCORING", "PPR")
    legacy.SCORING = scoring
    try:
        df, _active_ids = legacy.load_position_directory(position)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(df.to_dict("records"), indent=2), encoding="utf-8")
        os.replace(tmp, path)
        picker.DIRECTORIES[key] = df
        return df
    except Exception:
        if cached is not None:
            picker.DIRECTORIES[key] = cached
            return cached
        raise
    finally:
        legacy.SCORING = old_scoring


def players_payload_v319(position: str, scoring: str):
    _sync_week()
    if position not in core.POSITIONS:
        raise ValueError("Choose QB, RB, WR, or TE.")
    scoring = core.norm_scoring(scoring)
    directory = get_player_directory_v319(position, scoring)

    rankings_cached = False
    model = core.STATE.get("position_models", {}).get(position)
    if model:
        ids = model.get("active_ids") or []
        first = ids[:core.GROUP_SIZE]
        if first:
            rankings_cached = core.group_path(position, scoring, first).exists()

    players = []
    for _, row in directory.sort_values("directory_rank", na_position="last").iterrows():
        players.append({
            "player": row.get("player"),
            "team": row.get("team"),
            "player_id": str(row.get("player_id")),
            "cached": rankings_cached,
        })
    return {
        "position": position,
        "scoring": scoring,
        "week": core.WEEK,
        "players": players,
        "cached_count": len(players) if rankings_cached else 0,
        "total_count": len(players),
    }


# Patch the module globals used by the inherited /api/players handler.
picker.get_player_directory = get_player_directory_v319
picker.players_payload = players_payload_v319


_orig_core_resolve = core.resolve


def resolve_v319(name: str, position: str):
    """Retry one live directory refresh before declaring a player unresolved."""
    _sync_week()
    model = core.get_model(position)
    try:
        return legacy.resolve_player(name, model["directory"])
    except ValueError as first_exc:
        scoring = "STD" if position == "QB" else getattr(legacy, "SCORING", "PPR")
        try:
            refreshed = get_player_directory_v319(position, scoring, force=True)
            model["directory"] = refreshed
            return legacy.resolve_player(name, refreshed)
        except Exception:
            raise first_exc


core.resolve = resolve_v319


class Handler(prev.Handler):
    def do_GET(self):
        _sync_week()
        if self.path == "/":
            self.send_html(nav.home_html_v317().replace("v0.3.17", f"v{APP_VERSION}"))
            return
        return super().do_GET()

    def do_POST(self):
        _sync_week()
        return super().do_POST()


ns["Handler"] = Handler
_sync_week()

if __name__ == "__main__":
    ns["main"]()
