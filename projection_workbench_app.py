from __future__ import annotations

import json
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

import projection_ai as ai_module
import projection_workbench_ai as app
from projection_tracker import flush_outbox, migrate_historical_records, sync_record

base = app.base
PROD_DATA_FILE = base.DATA_DIR / "projections.json"

# QA must never contaminate the production history/MAE store. Replay-last-real still reads
# PROD_DATA_FILE through the patched helper below.
if app.QA_MODE:
    base.DATA_FILE = base.DATA_DIR / "projections_qa.json"


def _qa_last_real_record():
    try:
        data = json.loads(PROD_DATA_FILE.read_text(encoding="utf-8"))
        for record in reversed(data.get("records") or []):
            if record.get("ai_mode") == "web_research":
                return record
    except Exception:
        pass
    return None


if app.QA_MODE:
    app._last_real_record = _qa_last_real_record


# Historical README becomes stable prompt context. It is intentionally inserted before the
# dynamic player context so provider prompt caching can reuse the large stable prefix.
METHODOLOGY_FILE = Path(__file__).with_name("projection_methodology.md")
try:
    HISTORICAL_METHODOLOGY = METHODOLOGY_FILE.read_text(encoding="utf-8")
except Exception:
    HISTORICAL_METHODOLOGY = ""

_original_prompt = ai_module._prompt
_original_schema = ai_module._schema


def _integrated_prompt(payload: dict, research: dict, knowledge: list[dict]) -> str:
    text = _original_prompt(payload, research, knowledge)
    text = text.replace(
        "Scoring reminder: pigskin is 1 PPR + 1 point per rushing/receiving first down; funnel is 0 PPR + 0.5 PPFD; fami is 1 PPR + 0 PPFD. QB scoring is 0.04/pass yard, 4/pass TD, -2/INT, 0.1/rush yard, 6/rush TD.",
        "Scoring reminder (core modeled components): Pigskin is 1 PPR + 1 point per rushing/receiving first down, 4/pass TD and -2/INT. Funnel is 0 PPR + 0.5 PPFD for non-QBs, 4/pass TD and -2/INT. Fami is 1 PPR, +0.2 per rushing attempt, 5/pass TD and -1/INT. All use 0.04/pass yard, 0.1/rush or receiving yard and 6/rush or receiving TD. League threshold/long-TD bonuses exist in the historical scoring sheet but are not yet explicit component fields; do not force component stats merely to mimic those bonuses.",
    )
    if HISTORICAL_METHODOLOGY:
        text = text.replace(
            "INPUT CONTEXT:",
            "HISTORICAL TRACKER README / CARRY-FORWARD RULES:\n" + HISTORICAL_METHODOLOGY + "\n\nINPUT CONTEXT:",
            1,
        )
    return text


def _integrated_schema() -> dict:
    schema = _original_schema()
    stats = schema["properties"]["stats"]
    stats["properties"]["pass_attempts"] = {"type": "number"}
    stats["properties"]["qb_rush_attempts"] = {"type": "number"}
    # Structured output requires all declared fields. Position-irrelevant values remain zero.
    if "pass_attempts" not in stats["required"]:
        stats["required"].extend(["pass_attempts", "qb_rush_attempts"])
    return schema


ai_module._prompt = _integrated_prompt
ai_module._schema = _integrated_schema

# projection_workbench_ai imported research_projection from this module, and that function
# resolves _prompt/_schema from projection_ai globals at call time, so the patched methodology
# and attempt fields flow through without forking the paid research implementation.

_original_merge_ai = app._merge_ai


def _integrated_merge_ai(payload: dict, research: dict, ai: dict) -> dict:
    enriched = _original_merge_ai(payload, research, ai)
    if str(enriched.get("position") or "").upper() == "QB":
        raw = ai.get("stats") or {}
        enriched.setdefault("stats", {})["pass_attempts"] = raw.get("pass_attempts", 0)
        enriched["stats"]["qb_rush_attempts"] = raw.get("qb_rush_attempts", 0)
    return enriched


app._merge_ai = _integrated_merge_ai

# Reconcile deterministic scoring with the tracker for the core fields the workbench actually
# projects. Historical rows retain their original stored FP and are never recomputed.
base.SCORING_PROFILES["fami"]["pass_td"] = 5.0
base.SCORING_PROFILES["fami"]["interception"] = -1.0
base.SCORING_PROFILES["fami"]["rush_attempt"] = 0.2

_original_calculate_points = base.calculate_points


def _calculate_points(position: str, stats: dict, profile_name: str) -> float:
    points = _original_calculate_points(position, stats, profile_name)
    if str(profile_name).lower() == "fami" and str(position).upper() != "QB":
        points += base.num(stats.get("carries")) * 0.2
    return round(points, 2)


base.calculate_points = _calculate_points


# Final UI assembly: preserve the existing QA payload wiring, expose QB attempt assumptions,
# use the corrected Fami math client-side, and surface Sheet sync status without adding clutter.
html = base.HTML
html = html.replace(
    "document.body.classList.add('draft-mode');\nconst draftBtn=$('draftGenerateBtn');",
    """const originalPayload=payload;
payload=function(){
  const p=originalPayload();
  if($('qaScenario'))p.qa_scenario=$('qaScenario').value;
  if($('qaDelay'))p.qa_delay=parseInt($('qaDelay').value||'0',10);
  return p;
};
document.body.classList.add('draft-mode');
const draftBtn=$('draftGenerateBtn');""",
    1,
)
html = html.replace(
    '<div id="qbStats" class="grid hidden"><div class="field"><label>Pass yards</label>',
    '<div id="qbStats" class="grid hidden"><div class="field"><label>Pass attempts</label><input class="stat" id="pass_attempts" type="number" step="0.1"></div><div class="field"><label>Pass yards</label>',
    1,
)
html = html.replace(
    '<div class="field"><label>Rush yards</label><input class="stat" id="qb_rush_yards" type="number" step="0.1"></div><div class="field"><label>Rush TD</label><input class="stat" id="qb_rush_tds" type="number" step="0.01"></div></div>',
    '<div class="field"><label>Rush attempts</label><input class="stat" id="qb_rush_attempts" type="number" step="0.1"></div><div class="field"><label>Rush yards</label><input class="stat" id="qb_rush_yards" type="number" step="0.1"></div><div class="field"><label>Rush TD</label><input class="stat" id="qb_rush_tds" type="number" step="0.01"></div></div>',
    1,
)
html = html.replace(
    "const scoring={pigskin:{ppr:1,ppfd:1},funnel:{ppr:0,ppfd:.5},fami:{ppr:1,ppfd:0}};",
    "const scoring={pigskin:{ppr:1,ppfd:1,passTd:4,int:-2,rushAtt:0},funnel:{ppr:0,ppfd:.5,passTd:4,int:-2,rushAtt:0},fami:{ppr:1,ppfd:0,passTd:5,int:-1,rushAtt:.2}};",
    1,
)
html = html.replace(
    "fp=n('pass_yards')*.04+n('pass_tds')*4-n('interceptions')*2+n('qb_rush_yards')*.1+n('qb_rush_tds')*6",
    "fp=n('pass_yards')*.04+n('pass_tds')*s.passTd+n('interceptions')*s.int+n('qb_rush_yards')*.1+n('qb_rush_tds')*6",
    1,
)
html = html.replace(
    "fp=n('rush_yards')*.1+n('rush_tds')*6+n('receptions')*s.ppr+n('rec_yards')*.1+n('rec_tds')*6+(n('rush_first_downs')+n('rec_first_downs'))*s.ppfd",
    "fp=n('carries')*s.rushAtt+n('rush_yards')*.1+n('rush_tds')*6+n('receptions')*s.ppr+n('rec_yards')*.1+n('rec_tds')*6+(n('rush_first_downs')+n('rec_first_downs'))*s.ppfd",
    1,
)
html = html.replace(
    "if($('position').value==='QB')return {pass_yards:n('pass_yards'),pass_tds:n('pass_tds'),interceptions:n('interceptions'),rush_yards:n('qb_rush_yards'),rush_tds:n('qb_rush_tds')};",
    "if($('position').value==='QB')return {pass_attempts:n('pass_attempts'),pass_yards:n('pass_yards'),pass_tds:n('pass_tds'),interceptions:n('interceptions'),qb_rush_attempts:n('qb_rush_attempts'),rush_yards:n('qb_rush_yards'),rush_tds:n('qb_rush_tds')};",
    1,
)
html = html.replace(
    "setStat('pass_yards',s.pass_yards);setStat('pass_tds',s.pass_tds);setStat('interceptions',s.interceptions);\n    setStat('qb_rush_yards',s.rush_yards);setStat('qb_rush_tds',s.rush_tds);",
    "setStat('pass_attempts',s.pass_attempts);setStat('pass_yards',s.pass_yards);setStat('pass_tds',s.pass_tds);setStat('interceptions',s.interceptions);\n    setStat('qb_rush_attempts',s.qb_rush_attempts);setStat('qb_rush_yards',s.rush_yards);setStat('qb_rush_tds',s.rush_tds);",
    1,
)
# Historical source rows can legitimately have no model projection; never render null as 0.00.
html = html.replace(
    "<span>${Number(r.our_projected_fp).toFixed(2)}</span><span>${r.app_projected_fp==null?'—':Number(r.app_projected_fp).toFixed(2)}</span>",
    "<span>${r.our_projected_fp==null?'—':Number(r.our_projected_fp).toFixed(2)}</span><span>${r.app_projected_fp==null?'—':Number(r.app_projected_fp).toFixed(2)}</span>",
    1,
)
html = html.replace(
    "buildEvidence();loadPlayerDirectory();document.querySelectorAll",
    """const originalApplyResearchResult=applyResearchResult;
applyResearchResult=function(rec){
  originalApplyResearchResult(rec);
  const sync=rec.sheet_sync||{};
  if(sync.status && rec.ai_mode!=='qa_fixture'){
    const suffix=sync.row?` · Sheet row ${sync.row}`:'';
    const label=sync.status==='not_configured'?'Sheet sync pending setup':sync.status==='queued'?'Sheet sync queued':sync.status==='blocked_postgame'?'Sheet row protected (postgame)':`Sheet ${sync.status}`;
    $('researchStatus').textContent += ` · ${label}${suffix}`;
  }
};
buildEvidence();loadPlayerDirectory();document.querySelectorAll""",
    1,
)
base.HTML = html


def _persist_record_fields(record_id: str, fields: dict) -> dict:
    store = base.load_store()
    result = None
    for record in store.get("records") or []:
        if record.get("id") == record_id:
            record.update(fields)
            result = dict(record)
            break
    if result is None:
        raise ValueError("Projection revision not found.")
    base.save_store(store)
    return result


def _sync_and_persist(record: dict) -> dict:
    if app.QA_MODE or record.get("ai_mode") == "qa_fixture" or record.get("historical_source"):
        return record
    sync = sync_record(record)
    return _persist_record_fields(str(record.get("id") or ""), {
        "tracker_key": sync.get("tracker_key"),
        "sheet_sync": sync,
    })


class Handler(app.Handler):
    def do_POST(self):
        if self.path == "/api/projection":
            try:
                payload = app.enrich_projection_payload(self.read_json())
                with base.LOCK:
                    result = app._save_projection(payload)
                    result = _sync_and_persist(result)
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, status=400)
            return
        if self.path == "/api/lock":
            try:
                payload = self.read_json()
                with base.LOCK:
                    result = base.lock_projection(str(payload.get("id") or ""))
                    result = _sync_and_persist(result)
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, status=400)
            return
        if self.path == "/api/grade":
            try:
                payload = self.read_json()
                with base.LOCK:
                    result = base.grade_projection(str(payload.get("id") or ""), payload.get("actual_fp"))
                    result = _sync_and_persist(result)
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, status=400)
            return
        super().do_POST()


def main():
    base.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not app.QA_MODE:
        migrated = migrate_historical_records(base)
        flushed = flush_outbox()
    else:
        migrated = {"added": 0, "available": 0}
        flushed = {"sent": 0, "remaining": 0}

    if app.QA_MODE:
        mode = "QA fixtures (zero paid API calls)"
    else:
        mode = "AI + live web research" if app.is_configured() else "local fallback (configure API key for AI research)"
    print(f"Projection Workbench {base.APP_VERSION}: http://{base.HOST}:{base.PORT}")
    print(f"Projection mode: {mode}")
    print(f"Local projection store: {base.DATA_FILE}")
    if not app.QA_MODE:
        print(f"Historical tracker: {migrated['available']} rows available, {migrated['added']} newly imported")
        if flushed.get("sent") or flushed.get("remaining"):
            print(f"Sheet sync outbox: {flushed.get('sent',0)} sent, {flushed.get('remaining',0)} remaining")
    print("Deep dives are lazy-loaded on first open.")
    print("Press Ctrl+C in Terminal to stop it.")
    server = ThreadingHTTPServer((base.HOST, base.PORT), Handler)
    threading.Timer(0.8, lambda: webbrowser.open(f"http://{base.HOST}:{base.PORT}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
