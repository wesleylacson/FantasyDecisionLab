#!/usr/bin/env python3
"""Fantasy Decision Lab — Projection Workbench MVP.

Standalone pilot for building, revising, locking, and grading weekly projections.
The workbench intentionally does not depend on FantasyPros or any single source.

Run:
    python3 projection_workbench.py
Then open:
    http://127.0.0.1:8766

Data is stored locally in:
    ~/.fantasy_decision_lab/projections.json
"""
from __future__ import annotations

import json
import math
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = 8766
APP_VERSION = "0.1.1-projection-mvp"
DATA_DIR = Path.home() / ".fantasy_decision_lab"
DATA_FILE = DATA_DIR / "projections.json"
LOCK = threading.Lock()

PILLARS = (
    "role_opportunity",
    "game_environment",
    "matchup_scheme",
    "market_expert",
)

EVIDENCE_CATEGORIES = (
    "role_usage",
    "vegas_environment",
    "matchup_data",
    "injury_context",
    "market_projection",
    "coverage_scheme",
    "expert_commentary",
)

SCORING_PROFILES = {
    "pigskin": {"label": "Pigskin Madness", "ppr": 1.0, "ppfd": 1.0, "rush_yd": 0.1, "rec_yd": 0.1, "pass_yd": 0.04, "rush_td": 6.0, "rec_td": 6.0, "pass_td": 4.0, "interception": -2.0},
    "funnel": {"label": "Funnel League", "ppr": 0.0, "ppfd": 0.5, "rush_yd": 0.1, "rec_yd": 0.1, "pass_yd": 0.04, "rush_td": 6.0, "rec_td": 6.0, "pass_td": 4.0, "interception": -2.0},
    "fami": {"label": "Fami-League", "ppr": 1.0, "ppfd": 0.0, "rush_yd": 0.1, "rec_yd": 0.1, "pass_yd": 0.04, "rush_td": 6.0, "rec_td": 6.0, "pass_td": 4.0, "interception": -2.0},
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def empty_store() -> dict:
    return {"schema_version": 2, "records": []}


def load_store() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        return empty_store()
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("records"), list):
            raise ValueError("invalid projection store")
        return data
    except Exception:
        backup = DATA_FILE.with_suffix(f".corrupt-{int(datetime.now().timestamp())}.json")
        try:
            DATA_FILE.replace(backup)
        except Exception:
            pass
        return empty_store()


def save_store(store: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(DATA_FILE)


def num(value, default=0.0) -> float:
    try:
        f = float(value)
        return f if math.isfinite(f) else default
    except Exception:
        return default


def projection_key(payload: dict) -> str:
    player = " ".join(str(payload.get("player") or "").strip().lower().split())
    position = str(payload.get("position") or "UNKNOWN").upper().strip()
    week = int(num(payload.get("week"), 0))
    scoring = str(payload.get("scoring_profile") or "").lower().strip()
    return f"{player}|{position}|{week}|{scoring}"


def calculate_points(position: str, stats: dict, profile_name: str) -> float:
    scoring = SCORING_PROFILES.get(profile_name, SCORING_PROFILES["pigskin"])
    position = position.upper()
    points = 0.0
    if position == "QB":
        points += num(stats.get("pass_yards")) * scoring["pass_yd"]
        points += num(stats.get("pass_tds")) * scoring["pass_td"]
        points += num(stats.get("interceptions")) * scoring["interception"]
        points += num(stats.get("rush_yards")) * scoring["rush_yd"]
        points += num(stats.get("rush_tds")) * scoring["rush_td"]
    else:
        points += num(stats.get("rush_yards")) * scoring["rush_yd"]
        points += num(stats.get("rush_tds")) * scoring["rush_td"]
        points += num(stats.get("receptions")) * scoring["ppr"]
        points += num(stats.get("rec_yards")) * scoring["rec_yd"]
        points += num(stats.get("rec_tds")) * scoring["rec_td"]
        points += (num(stats.get("rush_first_downs")) + num(stats.get("rec_first_downs"))) * scoring["ppfd"]
    return round(points, 2)


def confidence_from_evidence(evidence: dict) -> str:
    score = 0.0
    for key in EVIDENCE_CATEGORIES:
        state = str(evidence.get(key) or "missing")
        score += 1.0 if state == "available" else 0.5 if state == "partial" else 0.0
    ratio = score / len(EVIDENCE_CATEGORIES)
    if ratio >= 0.78:
        return "high"
    if ratio >= 0.45:
        return "medium"
    return "low"


def next_revision(records: list[dict], key: str) -> int:
    revisions = [int(r.get("revision") or 0) for r in records if r.get("projection_key") == key]
    return max(revisions, default=0) + 1


def save_projection(payload: dict) -> dict:
    # Product rule: only player and scoring are required. Everything else may be
    # auto-populated by the research layer, generated by the projection, or left optional.
    required = ["player", "scoring_profile"]
    missing = [k for k in required if not str(payload.get(k) or "").strip()]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    position = str(payload.get("position") or "RB").upper().strip()
    if position not in {"QB", "RB", "WR", "TE"}:
        position = "RB"
    scoring_profile = str(payload["scoring_profile"]).lower()
    if scoring_profile not in SCORING_PROFILES:
        raise ValueError("Unknown scoring profile.")

    store = load_store()
    key = projection_key({**payload, "position": position})
    revision = next_revision(store["records"], key)
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    our_fp = calculate_points(position, stats, scoring_profile)

    evidence_in = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    evidence = {k: str(evidence_in.get(k) or "missing") for k in EVIDENCE_CATEGORIES}
    pillars_in = payload.get("pillars") if isinstance(payload.get("pillars"), dict) else {}
    pillars = {}
    for p in PILLARS:
        src = pillars_in.get(p) if isinstance(pillars_in.get(p), dict) else {}
        pillars[p] = {
            "headline": str(src.get("headline") or ""),
            "deep_dive": str(src.get("deep_dive") or src.get("system_summary") or ""),
            "user_note": str(src.get("user_note") or ""),
        }

    weather_in = payload.get("weather") if isinstance(payload.get("weather"), dict) else {}
    weather = {
        "status": str(weather_in.get("status") or "unknown"),
        "summary": str(weather_in.get("summary") or ""),
        "fp_adjustment": round(num(weather_in.get("fp_adjustment")), 2),
        "affected_components": weather_in.get("affected_components") if isinstance(weather_in.get("affected_components"), list) else [],
    }
    feedback = payload.get("feedback") if isinstance(payload.get("feedback"), dict) else {}

    record = {
        "id": f"{int(datetime.now().timestamp() * 1000)}-{revision}",
        "projection_key": key,
        "revision": revision,
        "created_at": now_iso(),
        "locked": False,
        "locked_at": None,
        "player": str(payload["player"]).strip(),
        "team": str(payload.get("team") or "").strip(),
        "opponent": str(payload.get("opponent") or "").strip(),
        "position": position,
        "week": int(num(payload.get("week"), 0)),
        "scoring_profile": scoring_profile,
        "stats": stats,
        "our_projected_fp": our_fp,
        "app_projected_fp": None if payload.get("app_projected_fp") in (None, "") else round(num(payload.get("app_projected_fp")), 2),
        "floor_fp": None if payload.get("floor_fp") in (None, "") else round(num(payload.get("floor_fp")), 2),
        "ceiling_fp": None if payload.get("ceiling_fp") in (None, "") else round(num(payload.get("ceiling_fp")), 2),
        "confidence": confidence_from_evidence(evidence),
        "pillars": pillars,
        "weather": weather,
        "evidence": evidence,
        "feedback": {"category": str(feedback.get("category") or ""), "comment": str(feedback.get("comment") or "")},
        "actual_fp": None,
        "our_abs_error": None,
        "app_abs_error": None,
    }
    store["records"].append(record)
    save_store(store)
    return record


def find_record(store: dict, record_id: str) -> dict:
    for record in store["records"]:
        if record.get("id") == record_id:
            return record
    raise ValueError("Projection record not found.")


def lock_projection(record_id: str) -> dict:
    store = load_store()
    record = find_record(store, record_id)
    for other in store["records"]:
        if other.get("projection_key") == record.get("projection_key"):
            other["locked"] = False
            other["locked_at"] = None
    record["locked"] = True
    record["locked_at"] = now_iso()
    save_store(store)
    return record


def grade_projection(record_id: str, actual_fp) -> dict:
    store = load_store()
    record = find_record(store, record_id)
    if not record.get("locked"):
        raise ValueError("Only the locked official projection can be graded.")
    actual = round(num(actual_fp), 2)
    record["actual_fp"] = actual
    record["our_abs_error"] = round(abs(actual - num(record.get("our_projected_fp"))), 2)
    app = record.get("app_projected_fp")
    record["app_abs_error"] = None if app is None else round(abs(actual - num(app)), 2)
    record["graded_at"] = now_iso()
    save_store(store)
    return record


def list_records(position: str | None = None) -> list[dict]:
    records = load_store()["records"]
    if position and position.upper() != "ALL":
        records = [r for r in records if r.get("position") == position.upper()]
    return sorted(records, key=lambda r: (r.get("week", 0), r.get("created_at", "")), reverse=True)


def performance(position: str | None = None) -> dict:
    records = [r for r in load_store()["records"] if r.get("locked") and r.get("actual_fp") is not None]
    if position and position.upper() != "ALL":
        records = [r for r in records if r.get("position") == position.upper()]
    weeks = sorted({int(r.get("week") or 0) for r in records})
    points = []
    for week in weeks:
        through = [r for r in records if int(r.get("week") or 0) <= week]
        ours = [num(r.get("our_abs_error")) for r in through if r.get("our_abs_error") is not None]
        apps = [num(r.get("app_abs_error")) for r in through if r.get("app_abs_error") is not None]
        points.append({
            "week": week,
            "our_mae": sum(ours) / len(ours) if ours else None,
            "app_mae": sum(apps) / len(apps) if apps else None,
            "n": len(through),
        })
    all_our = [num(r.get("our_abs_error")) for r in records if r.get("our_abs_error") is not None]
    all_app = [num(r.get("app_abs_error")) for r in records if r.get("app_abs_error") is not None]
    return {
        "position": (position or "ALL").upper(),
        "sample_size": len(records),
        "our_mae": round(sum(all_our) / len(all_our), 3) if all_our else None,
        "app_mae": round(sum(all_app) / len(all_app), 3) if all_app else None,
        "points": points,
    }


HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fantasy Decision Lab — Projection Workbench</title>
<style>
:root{--bg:#07101f;--panel:#101b2f;--line:#233454;--text:#f4f7fb;--muted:#96a8c4;--accent:#7b7cff;--accent2:#39d0ff;--good:#65d39a;--warn:#ffc96b}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0%,#13264a 0,#07101f 35%),var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh}.shell{max-width:1320px;margin:0 auto;padding:30px 20px 80px}.eyebrow{text-transform:uppercase;letter-spacing:.14em;font-size:12px;color:var(--accent2);font-weight:800}.title{font-size:40px;font-weight:950;margin:6px 0}.sub{color:var(--muted);line-height:1.55;max-width:1000px;margin:0 0 22px}.tabs{display:flex;gap:10px;margin:18px 0}.tab,.btn{border:1px solid #304568;background:#091426;color:#c9d6e8;border-radius:12px;padding:11px 14px;font-weight:850;cursor:pointer}.tab.active,.btn.primary{background:linear-gradient(90deg,var(--accent),var(--accent2));border-color:transparent;color:#06111f}.panel{background:linear-gradient(180deg,rgba(18,31,54,.96),rgba(12,22,40,.96));border:1px solid var(--line);border-radius:20px;padding:20px;margin-bottom:16px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}.field label,.section-label{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em;font-weight:800;margin:0 0 7px}.field input,.field select,.field textarea{width:100%;border:1px solid #314466;background:#091426;color:#fff;border-radius:12px;padding:12px;font-size:14px}.field textarea{min-height:92px;resize:vertical}.required{color:var(--warn);font-size:10px;margin-left:6px;letter-spacing:.03em;text-transform:none}.optional-note{color:var(--muted);font-size:12px;margin:2px 0 14px}.hero{display:grid;grid-template-columns:1fr auto;gap:20px;align-items:center}.fp{font-size:48px;font-weight:950;line-height:1}.muted{color:var(--muted)}.scorecards{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}.scorecard{background:#081426;border:1px solid #233a60;border-radius:14px;padding:11px 14px;min-width:112px}.scorecard strong{display:block;font-size:20px}.scorecard small{color:var(--muted)}.pillars{display:grid;grid-template-columns:1fr 1fr;gap:14px}.pillar{border:1px solid #273b5d;background:#091426;border-radius:16px;padding:15px}.pillar h3{font-size:13px;margin:0 0 10px}.pillar-summary{font-size:14px;line-height:1.5;margin-bottom:10px}.context-box{border-top:1px solid #243856;margin-top:10px;padding-top:10px;font-size:12px;color:#9fb1ca}.context-box strong{color:#cbd8e9}.deep{margin-top:10px}.deep summary{cursor:pointer;color:#9fdfff;font-size:12px;font-weight:800}.deep div{color:#b5c3d7;line-height:1.55;margin-top:8px;font-size:13px}.weather{display:grid;grid-template-columns:170px 1fr 160px;gap:12px}.evidence{display:grid;grid-template-columns:repeat(4,1fr);gap:9px}.evidence-item{border:1px solid #2a3d5c;border-radius:12px;padding:10px}.evidence-item select{width:100%;margin-top:6px;background:#081426;color:white;border:0}.actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.btn{padding:12px 16px}.btn.good{border-color:#2f7453;color:#a8f2c9}.status{color:var(--muted);font-size:13px}.locked{color:var(--good);font-weight:900}.revision{display:inline-block;padding:5px 9px;border:1px solid #385274;border-radius:999px;color:#b8c8df;font-size:11px}.chart-wrap{height:330px;position:relative}.chart-wrap canvas{width:100%;height:100%}.perf-head{display:flex;justify-content:space-between;gap:12px;align-items:center}.perf-numbers{display:flex;gap:18px}.perf-number strong{display:block;font-size:26px}.history{max-height:330px;overflow:auto}.history-row{display:grid;grid-template-columns:1.5fr .5fr .6fr .6fr .6fr;gap:10px;padding:10px;border-top:1px solid #20314d;font-size:13px}.feedback{display:grid;grid-template-columns:220px 1fr;gap:10px}.hidden{display:none!important}@media(max-width:900px){.grid,.grid2,.pillars,.evidence{grid-template-columns:1fr 1fr}.hero,.weather{grid-template-columns:1fr}.feedback{grid-template-columns:1fr}}@media(max-width:600px){.grid,.grid2,.pillars,.evidence{grid-template-columns:1fr}.title{font-size:32px}}
</style></head>
<body><main class="shell">
<div class="eyebrow">Fantasy Decision Lab</div><div class="title">Projection Workbench</div><p class="sub">Choose a player and scoring format, add any context you want considered, and let the projection fill in the rest. Every revision is preserved; one pregame version can be locked for the MAE scoreboard.</p>
<div class="tabs"><button class="tab active" data-tab="projection">Projection</button><button class="tab" data-tab="performance">Performance</button><button class="tab" data-tab="history">History</button></div>
<section id="projectionTab">
<div class="panel grid">
<div class="field"><label>Player <span class="required">Required</span></label><input id="player" placeholder="Rhamondre Stevenson"></div>
<div class="field"><label>Scoring <span class="required">Required</span></label><select id="scoring"><option value="pigskin">Pigskin Madness</option><option value="funnel">Funnel League</option><option value="fami">Fami-League</option></select></div>
<div class="field"><label>Team <span class="muted">· autofill later</span></label><input id="team" placeholder="Optional"></div>
<div class="field"><label>Opponent <span class="muted">· autofill later</span></label><input id="opponent" placeholder="Optional"></div>
<div class="field"><label>Week <span class="muted">· autofill later</span></label><input id="week" type="number" min="1" max="18" placeholder="Optional"></div>
<div class="field"><label>Position <span class="muted">· autofill later</span></label><select id="position"><option>RB</option><option>WR</option><option>TE</option><option>QB</option></select></div>
<div class="field"><label>App projection <span class="muted">· optional</span></label><input id="appFp" type="number" step="0.01" placeholder="16.10"></div>
</div>

<div class="panel hero"><div><div class="section-label">Our projection</div><div><span id="ourFp" class="fp">0.00</span> <span class="muted">FP</span></div><div class="scorecards"><div class="scorecard"><small>Floor</small><strong id="floorDisplay">—</strong></div><div class="scorecard"><small>Median</small><strong id="medianDisplay">0.00</strong></div><div class="scorecard"><small>Ceiling</small><strong id="ceilingDisplay">—</strong></div><div class="scorecard"><small>Evidence</small><strong id="coverageDisplay">0/7</strong></div><div class="scorecard"><small>Confidence</small><strong id="confidenceDisplay">Low</strong></div></div></div><div><span id="revisionBadge" class="revision">unsaved draft</span><div id="lockState" class="muted" style="margin-top:8px">Not locked</div></div></div>

<div class="panel"><div class="section-label">Projected stat line</div><div id="skillStats" class="grid">
<div class="field"><label>Carries</label><input class="stat" id="carries" type="number" step="0.1"></div><div class="field"><label>Rush yards</label><input class="stat" id="rush_yards" type="number" step="0.1"></div><div class="field"><label>Rush TD</label><input class="stat" id="rush_tds" type="number" step="0.01"></div><div class="field"><label>Rush first downs</label><input class="stat" id="rush_first_downs" type="number" step="0.1"></div>
<div class="field"><label>Targets</label><input class="stat" id="targets" type="number" step="0.1"></div><div class="field"><label>Receptions</label><input class="stat" id="receptions" type="number" step="0.1"></div><div class="field"><label>Rec yards</label><input class="stat" id="rec_yards" type="number" step="0.1"></div><div class="field"><label>Rec TD</label><input class="stat" id="rec_tds" type="number" step="0.01"></div><div class="field"><label>Rec first downs</label><input class="stat" id="rec_first_downs" type="number" step="0.1"></div>
</div><div id="qbStats" class="grid hidden"><div class="field"><label>Pass yards</label><input class="stat" id="pass_yards" type="number" step="1"></div><div class="field"><label>Pass TD</label><input class="stat" id="pass_tds" type="number" step="0.01"></div><div class="field"><label>Interceptions</label><input class="stat" id="interceptions" type="number" step="0.01"></div><div class="field"><label>Rush yards</label><input class="stat" id="qb_rush_yards" type="number" step="0.1"></div><div class="field"><label>Rush TD</label><input class="stat" id="qb_rush_tds" type="number" step="0.01"></div></div>
<div class="grid2" style="margin-top:14px"><div class="field"><label>Floor FP</label><input id="floorFp" type="number" step="0.1"></div><div class="field"><label>Ceiling FP</label><input id="ceilingFp" type="number" step="0.1"></div></div></div>

<div class="panel"><div class="section-label">Weather adjustment</div><div class="weather"><div class="field"><label>Status</label><select id="weatherStatus"><option value="unknown">Auto / unknown</option><option value="neutral">Neutral</option><option value="watch">Watch</option><option value="meaningful">Meaningful</option></select></div><div class="field"><label>Weather context</label><input id="weatherSummary" placeholder="Autopopulates from matchup; optional note for now"></div><div class="field"><label>FP adjustment</label><input id="weatherAdjustment" type="number" step="0.1" placeholder="0.0"></div></div><p class="muted" style="margin-bottom:0">Weather remains part of game environment conceptually, but is stored separately so we can audit the exact adjustment later.</p></div>

<div id="pillarInputPanel" class="panel"><div class="section-label">Your context</div><p class="optional-note">Optional — add anything you want considered. Leave every box blank if you just want the research pass to build from scratch.</p><div class="pillars">
<div class="pillar"><h3>1. Role / Opportunity</h3><div class="field"><textarea id="role_user" placeholder="Eye test, workload change, beat reporting, red-zone role…"></textarea></div></div>
<div class="pillar"><h3>2. Game Environment</h3><div class="field"><textarea id="game_user" placeholder="Expected script, team tendency, supporting-cast change…"></textarea></div></div>
<div class="pillar"><h3>3. Matchup / Scheme</h3><div class="field"><textarea id="matchup_user" placeholder="Coverage, box tendency, pressure, alignment, position-specific matchup…"></textarea></div></div>
<div class="pillar"><h3>4. Market / Expert Context</h3><div class="field"><textarea id="market_user" placeholder="Projection you distrust, analyst point you want checked, market observation…"></textarea></div></div>
</div></div>

<div id="pillarOutputPanel" class="panel hidden"><div class="section-label">Projection pillars</div><div class="pillars" id="pillarResults"></div></div>

<div class="panel"><div class="section-label">Evidence coverage</div><p class="muted">Coverage is category-based, not a raw source count. Missing one feed should degrade confidence, not kill the projection.</p><div id="evidenceGrid" class="evidence"></div></div>
<div class="panel"><div class="section-label">Something look off?</div><div class="feedback"><div class="field"><label>Area</label><select id="feedbackCategory"><option value="">None</option><option>Volume</option><option>Efficiency</option><option>TD</option><option>Matchup</option><option>Game environment</option><option>Weather</option><option>Other</option></select></div><div class="field"><label>Feedback for the next revision</label><input id="feedbackComment" placeholder="I think 14 carries is too low because…"></div></div></div>
<div class="actions"><button id="saveBtn" class="btn primary">Generate / save revision</button><button id="editContextBtn" class="btn hidden">Edit context</button><button id="lockBtn" class="btn good" disabled>Lock this projection</button><span id="status" class="status"></span></div>
</section>

<section id="performanceTab" class="hidden"><div class="panel"><div class="perf-head"><div><div class="section-label">North star</div><h2 style="margin:0">Cumulative MAE vs App</h2></div><div class="field" style="min-width:140px"><label>Position</label><select id="perfPosition"><option>ALL</option><option>QB</option><option>RB</option><option>WR</option><option>TE</option></select></div></div><div class="perf-numbers" style="margin-top:16px"><div class="perf-number"><span class="muted">Our MAE</span><strong id="ourMae">—</strong></div><div class="perf-number"><span class="muted">App MAE</span><strong id="appMae">—</strong></div><div class="perf-number"><span class="muted">Sample</span><strong id="sampleN">0</strong></div></div><div class="chart-wrap"><canvas id="maeChart"></canvas></div><p class="muted">Only locked projections with actual results enter this chart. App MAE excludes records where no app projection was captured.</p></div></section>
<section id="historyTab" class="hidden"><div class="panel"><div class="section-label">Projection history</div><div id="history" class="history"></div></div><div class="panel"><div class="section-label">Grade a locked projection</div><div class="grid2"><div class="field"><label>Record ID</label><input id="gradeId" placeholder="Click a locked row above"></div><div class="field"><label>Actual fantasy points</label><input id="actualFp" type="number" step="0.01"></div></div><button id="gradeBtn" class="btn primary" style="margin-top:12px">Save actual</button><span id="gradeStatus" class="status"></span></div></section>
</main>
<script>
const $=id=>document.getElementById(id);let currentRecord=null;
const evidenceLabels={role_usage:'Role / usage',vegas_environment:'Vegas environment',matchup_data:'Matchup data',injury_context:'Injury context',market_projection:'Market projection',coverage_scheme:'Coverage / scheme',expert_commentary:'Expert commentary'};
const scoring={pigskin:{ppr:1,ppfd:1},funnel:{ppr:0,ppfd:.5},fami:{ppr:1,ppfd:0}};
const pillarMeta={role_opportunity:['Role / Opportunity','role_user'],game_environment:['Game Environment','game_user'],matchup_scheme:['Matchup / Scheme','matchup_user'],market_expert:['Market / Expert Context','market_user']};
function n(id){const v=parseFloat($(id)?.value);return Number.isFinite(v)?v:0}
function calc(){const pos=$('position').value,s=scoring[$('scoring').value];let fp=0;if(pos==='QB'){fp=n('pass_yards')*.04+n('pass_tds')*4-n('interceptions')*2+n('qb_rush_yards')*.1+n('qb_rush_tds')*6}else{fp=n('rush_yards')*.1+n('rush_tds')*6+n('receptions')*s.ppr+n('rec_yards')*.1+n('rec_tds')*6+(n('rush_first_downs')+n('rec_first_downs'))*s.ppfd}fp=Math.round(fp*100)/100;$('ourFp').textContent=fp.toFixed(2);$('medianDisplay').textContent=fp.toFixed(2);$('floorDisplay').textContent=$('floorFp').value?Number($('floorFp').value).toFixed(1):'—';$('ceilingDisplay').textContent=$('ceilingFp').value?Number($('ceilingFp').value).toFixed(1):'—';updateCoverage()}
function updatePosition(){const qb=$('position').value==='QB';$('qbStats').classList.toggle('hidden',!qb);$('skillStats').classList.toggle('hidden',qb);calc()}
function buildEvidence(){const grid=$('evidenceGrid');grid.innerHTML='';Object.entries(evidenceLabels).forEach(([key,label])=>{const d=document.createElement('div');d.className='evidence-item';d.innerHTML=`<div>${label}</div><select id="ev_${key}"><option value="missing">Missing</option><option value="partial">Partial</option><option value="available">Available</option></select>`;grid.appendChild(d);d.querySelector('select').addEventListener('change',updateCoverage)})}
function updateCoverage(){let available=0,total=Object.keys(evidenceLabels).length;Object.keys(evidenceLabels).forEach(k=>{if($('ev_'+k)?.value==='available')available+=1;else if($('ev_'+k)?.value==='partial')available+=.5});$('coverageDisplay').textContent=`${available}/${total}`;const ratio=available/total;$('confidenceDisplay').textContent=ratio>=.78?'High':ratio>=.45?'Medium':'Low'}
function statsPayload(){if($('position').value==='QB')return {pass_yards:n('pass_yards'),pass_tds:n('pass_tds'),interceptions:n('interceptions'),rush_yards:n('qb_rush_yards'),rush_tds:n('qb_rush_tds')};return {carries:n('carries'),rush_yards:n('rush_yards'),rush_tds:n('rush_tds'),rush_first_downs:n('rush_first_downs'),targets:n('targets'),receptions:n('receptions'),rec_yards:n('rec_yards'),rec_tds:n('rec_tds'),rec_first_downs:n('rec_first_downs')}}
function payload(){const evidence={};Object.keys(evidenceLabels).forEach(k=>evidence[k]=$('ev_'+k).value);const pillars={};Object.entries(pillarMeta).forEach(([key,[label,id]])=>pillars[key]={headline:'',deep_dive:'',user_note:$(id).value});return {player:$('player').value,team:$('team').value,opponent:$('opponent').value,week:$('week').value,position:$('position').value,scoring_profile:$('scoring').value,app_projected_fp:$('appFp').value,floor_fp:$('floorFp').value,ceiling_fp:$('ceilingFp').value,stats:statsPayload(),pillars,evidence,weather:{status:$('weatherStatus').value,summary:$('weatherSummary').value,fp_adjustment:$('weatherAdjustment').value,affected_components:[]},feedback:{category:$('feedbackCategory').value,comment:$('feedbackComment').value}}}
function renderPillars(rec){const root=$('pillarResults');root.innerHTML='';Object.entries(pillarMeta).forEach(([key,[label,id]])=>{const p=rec.pillars?.[key]||{};const headline=p.headline||'High-level synthesis will appear here once the research pass is connected.';const deep=p.deep_dive||'No deep-dive research has been attached to this revision yet.';const note=p.user_note||'No user context added.';const d=document.createElement('div');d.className='pillar';d.innerHTML=`<h3>${label}</h3><div class="pillar-summary">${headline}</div><details class="deep"><summary>View deep dive</summary><div>${deep}</div></details><div class="context-box"><strong>Your context</strong><br>${note}</div>`;root.appendChild(d)});$('pillarInputPanel').classList.add('hidden');$('pillarOutputPanel').classList.remove('hidden');$('editContextBtn').classList.remove('hidden')}
async function api(path,opts={}){const r=await fetch(path,{headers:{'Content-Type':'application/json'},...opts});const j=await r.json();if(!r.ok)throw new Error(j.error||'Request failed');return j}
async function saveRevision(){if(!$('player').value.trim()){ $('status').textContent='Player is required.';return }try{$('status').textContent='Saving…';const rec=await api('/api/projection',{method:'POST',body:JSON.stringify(payload())});currentRecord=rec;$('revisionBadge').textContent='revision '+rec.revision;$('lockState').textContent='Not locked';$('lockState').className='muted';$('lockBtn').disabled=false;$('confidenceDisplay').textContent=(rec.confidence||'low').replace(/^./,c=>c.toUpperCase());renderPillars(rec);$('status').textContent=`Saved ${rec.player} — ${rec.our_projected_fp.toFixed(2)} FP`;await loadHistory()}catch(e){$('status').textContent=e.message}}
async function lockCurrent(){if(!currentRecord)return;try{const rec=await api('/api/lock',{method:'POST',body:JSON.stringify({id:currentRecord.id})});currentRecord=rec;$('lockState').textContent='LOCKED OFFICIAL';$('lockState').className='locked';$('status').textContent='Official pregame projection locked.';await loadHistory();await loadPerformance()}catch(e){$('status').textContent=e.message}}
function editContext(){$('pillarOutputPanel').classList.add('hidden');$('pillarInputPanel').classList.remove('hidden');$('editContextBtn').classList.add('hidden')}
function switchTab(name){document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));['projection','performance','history'].forEach(t=>$(t+'Tab').classList.toggle('hidden',t!==name));if(name==='performance')loadPerformance();if(name==='history')loadHistory()}
async function loadHistory(){const j=await api('/api/records');const root=$('history');if(!j.records.length){root.innerHTML='<p class="muted">No saved projections yet.</p>';return}root.innerHTML='<div class="history-row muted"><b>Player</b><b>Week</b><b>Ours</b><b>App</b><b>Status</b></div>'+j.records.map(r=>`<div class="history-row" data-id="${r.id}" data-locked="${r.locked}"><span>${r.player} <span class="muted">v${r.revision} · ${r.position}</span></span><span>${r.week||'—'}</span><span>${Number(r.our_projected_fp).toFixed(2)}</span><span>${r.app_projected_fp==null?'—':Number(r.app_projected_fp).toFixed(2)}</span><span class="${r.locked?'locked':'muted'}">${r.locked?(r.actual_fp==null?'LOCKED':'GRADED'):'draft'}</span></div>`).join('');root.querySelectorAll('.history-row[data-id]').forEach(row=>row.addEventListener('click',()=>{if(row.dataset.locked==='true')$('gradeId').value=row.dataset.id}))}
async function grade(){try{const rec=await api('/api/grade',{method:'POST',body:JSON.stringify({id:$('gradeId').value,actual_fp:$('actualFp').value})});$('gradeStatus').textContent=`Saved. Our error ${rec.our_abs_error}; app error ${rec.app_abs_error??'—'}.`;await loadHistory()}catch(e){$('gradeStatus').textContent=e.message}}
async function loadPerformance(){try{const j=await api('/api/performance?position='+$('perfPosition').value);$('ourMae').textContent=j.our_mae==null?'—':j.our_mae.toFixed(2);$('appMae').textContent=j.app_mae==null?'—':j.app_mae.toFixed(2);$('sampleN').textContent=j.sample_size;drawChart(j.points)}catch(e){console.error(e)}}
function drawChart(points){const c=$('maeChart'),rect=c.getBoundingClientRect(),dpr=window.devicePixelRatio||1;c.width=rect.width*dpr;c.height=rect.height*dpr;const x=c.getContext('2d');x.scale(dpr,dpr);const w=rect.width,h=rect.height;x.clearRect(0,0,w,h);x.strokeStyle='#29405f';x.fillStyle='#8fa3c1';x.font='12px sans-serif';if(!points.length){x.fillText('Grade locked projections to populate the MAE chart.',20,35);return}const vals=points.flatMap(p=>[p.our_mae,p.app_mae]).filter(v=>v!=null);const max=Math.max(2,...vals)*1.15,pad={l:44,r:20,t:25,b:35};for(let i=0;i<=4;i++){const y=pad.t+(h-pad.t-pad.b)*i/4;x.beginPath();x.moveTo(pad.l,y);x.lineTo(w-pad.r,y);x.stroke();x.fillText((max*(1-i/4)).toFixed(1),5,y+4)}const xp=i=>points.length===1?(pad.l+w-pad.r)/2:pad.l+(w-pad.l-pad.r)*i/(points.length-1),yp=v=>pad.t+(h-pad.t-pad.b)*(1-v/max);function line(field,color){x.strokeStyle=color;x.lineWidth=3;x.beginPath();let started=false;points.forEach((p,i)=>{const v=p[field];if(v==null)return;const xx=xp(i),yy=yp(v);started?x.lineTo(xx,yy):x.moveTo(xx,yy);started=true});x.stroke()}line('our_mae','#7b7cff');line('app_mae','#39d0ff');points.forEach((p,i)=>{x.fillStyle='#8fa3c1';x.fillText('W'+p.week,xp(i)-8,h-10)});x.fillStyle='#7b7cff';x.fillRect(w-175,10,12,3);x.fillStyle='#dbe5f3';x.fillText('Ours',w-156,15);x.fillStyle='#39d0ff';x.fillRect(w-105,10,12,3);x.fillStyle='#dbe5f3';x.fillText('App',w-86,15)}
buildEvidence();document.querySelectorAll('.stat,#scoring,#floorFp,#ceilingFp').forEach(el=>el.addEventListener('input',calc));$('position').addEventListener('change',updatePosition);$('saveBtn').addEventListener('click',saveRevision);$('editContextBtn').addEventListener('click',editContext);$('lockBtn').addEventListener('click',lockCurrent);$('gradeBtn').addEventListener('click',grade);$('perfPosition').addEventListener('change',loadPerformance);document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>switchTab(b.dataset.tab)));window.addEventListener('resize',()=>{if(!$('performanceTab').classList.contains('hidden'))loadPerformance()});updatePosition();loadHistory();
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_json(self, obj, status=200):
        data = json.dumps(obj, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def do_POST(self):
        try:
            payload = self.read_json()
            with LOCK:
                if self.path == "/api/projection":
                    result = save_projection(payload)
                elif self.path == "/api/lock":
                    result = lock_projection(str(payload.get("id") or ""))
                elif self.path == "/api/grade":
                    result = grade_projection(str(payload.get("id") or ""), payload.get("actual_fp"))
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
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
        if parsed.path == "/api/records":
            qs = parse_qs(parsed.query)
            position = (qs.get("position") or [None])[0]
            self.send_json({"records": list_records(position)})
            return
        if parsed.path == "/api/performance":
            qs = parse_qs(parsed.query)
            position = (qs.get("position") or ["ALL"])[0]
            self.send_json(performance(position))
            return
        if parsed.path == "/api/config":
            self.send_json({"version": APP_VERSION, "scoring_profiles": SCORING_PROFILES, "evidence_categories": EVIDENCE_CATEGORIES, "pillars": PILLARS})
            return
        self.send_response(404)
        self.end_headers()


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Projection Workbench {APP_VERSION}: http://{HOST}:{PORT}")
    print(f"Local projection store: {DATA_FILE}")
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
