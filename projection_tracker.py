from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

DATA_DIR = Path.home() / ".fantasy_decision_lab"
HISTORY_SEED = Path(__file__).with_name("projection_history_seed.csv")
SYNC_CONFIG = DATA_DIR / "projection_sheet_sync.json"
SYNC_OUTBOX = DATA_DIR / "projection_sheet_sync_outbox.jsonl"
SEASON = 2026


def _num(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def scoring_profile(league: str) -> str:
    text = str(league or "").lower()
    if "pigskin" in text:
        return "pigskin"
    if "fami" in text:
        return "fami"
    if "funnel" in text:
        return "funnel"
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def league_label(profile: str) -> str:
    return {
        "pigskin": "Pigskin Madness",
        "fami": "Fami-league",
        "funnel": "Funnelball",
    }.get(str(profile or "").lower(), str(profile or ""))


def normalize_player(name: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", str(name or "").lower())
    suffixes = {"jr", "sr", "ii", "iii", "iv", "v"}
    return " ".join(x for x in text.split() if x not in suffixes)


def tracker_key(record: dict, season: int = SEASON) -> str:
    return f"{season}|w{int(record.get('week') or 0)}|{str(record.get('scoring_profile') or '').lower()}|{normalize_player(record.get('player') or '')}"


def _historical_record(row: dict, base) -> dict:
    profile = scoring_profile(row.get("league") or "")
    position = str(row.get("position") or "RB").upper()
    week = int(float(row.get("week") or 0))
    player = str(row.get("player") or "").strip()
    stats: dict[str, Any] = {}
    if position == "QB":
        for src, dest in [
            ("pass_attempts", "pass_attempts"),
            ("pass_yards", "pass_yards"),
            ("pass_tds", "pass_tds"),
            ("interceptions", "interceptions"),
            ("rush_attempts", "qb_rush_attempts"),
            ("rush_yards", "rush_yards"),
            ("rush_tds", "rush_tds"),
        ]:
            value = _num(row.get(src))
            if value is not None:
                stats[dest] = value
    else:
        for src, dest in [
            ("rush_attempts", "carries"),
            ("rush_yards", "rush_yards"),
            ("rush_tds", "rush_tds"),
            ("targets", "targets"),
            ("receptions", "receptions"),
            ("rec_yards", "rec_yards"),
            ("rec_tds", "rec_tds"),
        ]:
            value = _num(row.get(src))
            if value is not None:
                stats[dest] = value
        fd = _num(row.get("first_downs"))
        if fd is not None:
            # Historical tracker stored a combined FD projection. Keep it intact instead of
            # inventing a rush/receiving split that did not exist in the source workbook.
            stats["first_downs"] = fd

    projected = _num(row.get("projected_fp"))
    app_fp = _num(row.get("app_fp"))
    actual = _num(row.get("actual_fp"))
    created = str(row.get("date") or "") + "T12:00:00-05:00"
    source_row = 2 + _historical_row_index(row)
    rec = {
        "id": f"legacy-sheet-{source_row}",
        "historical_source": "Fantasy Projection Tracker",
        "historical_sheet_row": source_row,
        "projection_key": base.projection_key({
            "player": player,
            "position": position,
            "week": week,
            "scoring_profile": profile,
        }),
        "revision": 1,
        "created_at": created,
        "locked": True,
        "locked_at": created,
        "player": player,
        "team": "",
        "opponent": str(row.get("opponent") or ""),
        "position": position,
        "week": week,
        "scoring_profile": profile,
        "stats": stats,
        # Historical totals are source-of-truth values; never recalculate them with the
        # current engine because league rules/model assumptions have evolved.
        "our_projected_fp": projected,
        "app_projected_fp": app_fp,
        "floor_fp": None,
        "ceiling_fp": None,
        "confidence": "historical",
        "pillars": {p: {"headline": "", "deep_dive": "", "user_note": ""} for p in base.PILLARS},
        "weather": {"status": "historical", "summary": "", "fp_adjustment": 0, "affected_components": []},
        "evidence": {k: "missing" for k in base.EVIDENCE_CATEGORIES},
        "feedback": {"category": "", "comment": ""},
        "actual_fp": actual,
        "our_abs_error": _num(row.get("our_abs_error")),
        "app_abs_error": _num(row.get("app_abs_error")),
        "accuracy_excluded": str(row.get("accuracy_excluded") or "").lower() == "true",
        "tracker_key": f"{SEASON}|w{week}|{profile}|{normalize_player(player)}",
        "sheet_sync": {"status": "historical", "row": source_row},
    }
    return rec


_HISTORY_ROW_COUNTER = -1

def _historical_row_index(row: dict) -> int:
    # DictReader does not retain a row number. migrate_historical_records sets this hidden
    # helper before each conversion; keeping it out of the CSV prevents schema pollution.
    return int(row.get("__seed_index") or 0)


def migrate_historical_records(base) -> dict:
    """Merge the legacy tracker once into the local revision store without duplicates."""
    if not HISTORY_SEED.exists():
        return {"added": 0, "available": 0}
    with HISTORY_SEED.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    store = base.load_store()
    records = store.get("records") or []
    existing_ids = {str(r.get("id")) for r in records}
    existing_tracker = {str(r.get("tracker_key")) for r in records if r.get("tracker_key")}
    added = 0
    for i, row in enumerate(rows):
        row["__seed_index"] = i
        rec = _historical_record(row, base)
        if rec["id"] in existing_ids or rec["tracker_key"] in existing_tracker:
            continue
        records.append(rec)
        existing_ids.add(rec["id"])
        existing_tracker.add(rec["tracker_key"])
        added += 1
    if added:
        store["records"] = records
        store["schema_version"] = max(int(store.get("schema_version") or 0), 3)
        base.save_store(store)
    return {"added": added, "available": len(rows)}


def _load_sync_config() -> dict:
    try:
        data = json.loads(SYNC_CONFIG.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def sheet_sync_configured() -> bool:
    cfg = _load_sync_config()
    return bool(str(cfg.get("url") or "").strip() and str(cfg.get("token") or "").strip())


def _first_downs(stats: dict) -> float | None:
    combined = _num(stats.get("first_downs"))
    if combined is not None:
        return combined
    rush = _num(stats.get("rush_first_downs")) or 0.0
    rec = _num(stats.get("rec_first_downs")) or 0.0
    total = rush + rec
    return total if total else None


def sheet_payload(record: dict) -> dict:
    stats = record.get("stats") if isinstance(record.get("stats"), dict) else {}
    position = str(record.get("position") or "").upper()
    return {
        "action": "upsert_projection",
        "tracker_key": tracker_key(record),
        "record": {
            "id": record.get("id"),
            "created_at": record.get("created_at"),
            "week": int(record.get("week") or 0),
            "revision": int(record.get("revision") or 0),
            "locked": bool(record.get("locked")),
            "league": league_label(record.get("scoring_profile")),
            "player": record.get("player"),
            "position": position,
            "opponent": record.get("opponent"),
            "pass_attempts": _num(stats.get("pass_attempts")) if position == "QB" else None,
            "pass_yards": _num(stats.get("pass_yards")) if position == "QB" else None,
            "pass_tds": _num(stats.get("pass_tds")) if position == "QB" else None,
            "interceptions": _num(stats.get("interceptions")) if position == "QB" else None,
            "rush_attempts": _num(stats.get("qb_rush_attempts")) if position == "QB" else _num(stats.get("carries")),
            "rush_yards": _num(stats.get("rush_yards")),
            "rush_tds": _num(stats.get("rush_tds")),
            "targets": None if position == "QB" else _num(stats.get("targets")),
            "receptions": None if position == "QB" else _num(stats.get("receptions")),
            "rec_yards": None if position == "QB" else _num(stats.get("rec_yards")),
            "rec_tds": None if position == "QB" else _num(stats.get("rec_tds")),
            "first_downs": None if position == "QB" else _first_downs(stats),
            "projected_fp": _num(record.get("our_projected_fp")),
            "app_fp": _num(record.get("app_projected_fp")),
            "actual_fp": _num(record.get("actual_fp")),
            "projection_summary": str(record.get("projection_summary") or ""),
        },
    }


def _queue(payload: dict, reason: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    entry = {"queued_at": datetime.now().astimezone().isoformat(timespec="seconds"), "reason": reason, "payload": payload}
    with SYNC_OUTBOX.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def sync_record(record: dict, queue_on_failure: bool = True) -> dict:
    """Upsert one canonical player/week row. Local revision history remains untouched."""
    payload = sheet_payload(record)
    cfg = _load_sync_config()
    url = str(cfg.get("url") or "").strip()
    token = str(cfg.get("token") or "").strip()
    if not url or not token:
        if queue_on_failure:
            _queue(payload, "sheet sync not configured")
        return {"status": "not_configured", "tracker_key": payload["tracker_key"]}
    body = dict(payload)
    body["token"] = token
    try:
        response = requests.post(url, json=body, timeout=20)
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(str(result.get("error") or "sheet bridge rejected request"))
        return {
            "status": str(result.get("status") or "synced"),
            "row": result.get("row"),
            "tracker_key": payload["tracker_key"],
        }
    except Exception as e:
        if queue_on_failure:
            _queue(payload, str(e))
        return {"status": "queued", "error": str(e), "tracker_key": payload["tracker_key"]}


def flush_outbox() -> dict:
    if not sheet_sync_configured() or not SYNC_OUTBOX.exists():
        return {"sent": 0, "remaining": 0}
    lines = [line for line in SYNC_OUTBOX.read_text(encoding="utf-8").splitlines() if line.strip()]
    remaining = []
    sent = 0
    for line in lines:
        try:
            entry = json.loads(line)
            payload = entry.get("payload") or {}
            record = payload.get("record") or {}
            # Reconstruct just enough of a workbench record for sheet_payload/sync_record.
            synthetic = {
                "id": record.get("id"), "created_at": record.get("created_at"), "week": record.get("week"),
                "revision": record.get("revision"), "locked": record.get("locked"), "player": record.get("player"),
                "position": record.get("position"), "opponent": record.get("opponent"),
                "scoring_profile": scoring_profile(record.get("league")),
                "our_projected_fp": record.get("projected_fp"), "app_projected_fp": record.get("app_fp"),
                "actual_fp": record.get("actual_fp"), "projection_summary": record.get("projection_summary"),
                "stats": {
                    "pass_attempts": record.get("pass_attempts"), "pass_yards": record.get("pass_yards"),
                    "pass_tds": record.get("pass_tds"), "interceptions": record.get("interceptions"),
                    "qb_rush_attempts": record.get("rush_attempts") if str(record.get("position")).upper() == "QB" else None,
                    "carries": record.get("rush_attempts") if str(record.get("position")).upper() != "QB" else None,
                    "rush_yards": record.get("rush_yards"), "rush_tds": record.get("rush_tds"),
                    "targets": record.get("targets"), "receptions": record.get("receptions"),
                    "rec_yards": record.get("rec_yards"), "rec_tds": record.get("rec_tds"),
                    "first_downs": record.get("first_downs"),
                },
            }
            result = sync_record(synthetic, queue_on_failure=False)
            if result.get("status") in {"inserted", "updated", "synced", "blocked_postgame"}:
                sent += 1
            else:
                remaining.append(line)
        except Exception:
            remaining.append(line)
    if remaining:
        SYNC_OUTBOX.write_text("\n".join(remaining) + "\n", encoding="utf-8")
    else:
        try:
            SYNC_OUTBOX.unlink()
        except FileNotFoundError:
            pass
    return {"sent": sent, "remaining": len(remaining)}
