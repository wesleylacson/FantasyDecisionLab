from __future__ import annotations

import os
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer

import projection_workbench_step1 as prior
from projection_ai import generate_deep_dive, is_configured, research_projection
from projection_qa import fixture_deep_dive, fixture_projection, replay_projection, scenarios

base = prior.base
RUN_MODE = str(os.environ.get("FANTASY_PROJECTION_MODE") or "live").strip().lower()
QA_MODE = RUN_MODE == "qa"
base.PORT = int(os.environ.get("FANTASY_PROJECTION_PORT") or base.PORT)
base.APP_VERSION = "0.5.0-cost-qa-lazy"


def enhance_html(html: str) -> str:
    html = html.replace(
        'App projection <span class="muted">· optional</span>',
        'App projection <span class="required">Required</span>',
    )
    html = html.replace(
        '<input id="appFp" type="number" step="0.01" placeholder="16.10">',
        '<input id="appFp" type="number" step="0.01" min="0" placeholder="Required benchmark">',
    )

    html = html.replace(
        '<p class="sub">Choose a player and scoring format, add any context you want considered, and let the projection fill in the rest. Every revision is preserved; one pregame version can be locked for the MAE scoreboard.</p>',
        '<p class="sub">Choose a player and scoring format, add any context you want considered, and let the projection fill in the rest. Every revision is preserved; one pregame version can be locked for the MAE scoreboard.</p>'
        + ('<div class="revision" style="margin-bottom:14px;color:#65d39a;border-color:#2f7453">QA / fixture mode · zero paid API calls</div>' if QA_MODE else '<div class="revision" style="margin-bottom:14px">Live research mode · cost-optimized</div>'),
        1,
    )

    # Draft mode asks only for inputs that matter. Metadata and projection output appear after generation.
    for label in ["Team", "Opponent", "Week", "Position"]:
        html = html.replace(
            f'<div class="field"><label>{label} <span class="muted">· autofill</span></label>',
            f'<div class="field post-only"><label>{label} <span class="muted">· autofill</span></label>',
        )

    html = html.replace('<div class="panel hero">', '<div class="panel hero post-only">', 1)
    html = html.replace('<div class="panel"><div class="section-label">Projected stat line</div>', '<div class="panel post-only"><div class="section-label">Projected stat line</div>', 1)
    html = html.replace('<div class="panel"><div class="section-label">Weather adjustment</div>', '<div class="panel post-only"><div class="section-label">Weather adjustment</div>', 1)
    html = html.replace('<div id="pillarOutputPanel" class="panel hidden">', '<div id="pillarOutputPanel" class="panel hidden post-only">', 1)
    html = html.replace('<div class="panel"><div class="section-label">Evidence coverage</div>', '<div class="panel post-only"><div class="section-label">Evidence coverage</div>', 1)
    html = html.replace('<div class="panel"><div class="section-label">Something look off?</div>', '<div class="panel post-only"><div class="section-label">Something look off?</div>', 1)
    html = html.replace('<div class="actions"><button id="saveBtn"', '<div class="actions post-only"><button id="saveBtn"', 1)

    qa_controls = ""
    if QA_MODE:
        options = "".join(f'<option value="{s["id"]}">{s["label"]}</option>' for s in scenarios())
        qa_controls = f'''<div class="field" style="min-width:220px"><label>QA scenario</label><select id="qaScenario">{options}</select></div>
<div class="field" style="min-width:150px"><label>Fake delay</label><select id="qaDelay"><option value="0">Instant</option><option value="3">3 seconds</option><option value="10">10 seconds</option><option value="20">20 seconds</option></select></div>'''

    html = html.replace(
        '</div></div>\n\n<div id="pillarOutputPanel"',
        f'''</div></div>
<div id="draftActions" class="actions draft-only" style="margin-top:12px">
  {qa_controls}
  <button id="draftGenerateBtn" class="btn primary">Generate projection</button>
  <span id="draftLoading" class="status"></span>
</div>

<div id="pillarOutputPanel"''',
        1,
    )

    html = html.replace(
        '</style>',
        '''
body.draft-mode .post-only{display:none !important}
body.result-mode .draft-only{display:none !important}
#draftGenerateBtn[disabled]{opacity:.65;cursor:wait}
#draftLoading{display:inline-flex;align-items:center;gap:8px}
#draftLoading.loading::before,.deep-loading::before{content:"";width:14px;height:14px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;display:inline-block;animation:fdlspin .8s linear infinite;margin-right:7px}
@keyframes fdlspin{to{transform:rotate(360deg)}}
</style>''',
        1,
    )

    html = html.replace(
        "async function saveRevision(){if(!$('player').value.trim()){ $('status').textContent='Player is required.';return }",
        "async function saveRevision(){if(!$('player').value.trim()){ $('status').textContent='Player is required.';return }if(!$('appFp').value.trim()){ $('status').textContent='App projection is required.';$('appFp').focus();return }",
    )
    html = html.replace(
        'Generate a revision to run the evidence pass and build a stat line.',
        'Generate runs a cost-optimized AI + web research projection in live mode. Deep dives are generated only when opened.',
    )
    html = html.replace(
        "$('researchStatus').textContent=`Automatic evidence pass: ${available} available · ${partial} partial · ${states.length-available-partial} missing. Stat line generated from recent usage, game environment, and bounded market calibration.`;",
        "const ai=rec.ai_meta||{};const mode=rec.ai_mode==='qa_fixture'?'QA fixture':rec.ai_mode==='web_research'?'AI + live web research':'local fallback';const usage=ai.usage||{};const tokenText=usage.total_tokens?` · ${usage.total_tokens} tokens`:'';const searchText=ai.web_search_calls!=null?` · ${ai.web_search_calls} web search calls`:'';$('researchStatus').textContent=`${mode}: ${available} available · ${partial} partial · ${states.length-available-partial} missing${searchText}${tokenText}.`;",
    )

    # Replace eager deep-dive rendering with lazy loading on first open.
    old_render = "function renderPillars(rec){const root=$('pillarResults');root.innerHTML='';Object.entries(pillarMeta).forEach(([key,[label,id]])=>{const p=rec.pillars?.[key]||{};const headline=p.headline||'High-level synthesis will appear here once the research pass is connected.';const deep=p.deep_dive||'No deep-dive research has been attached to this revision yet.';const note=p.user_note||'No user context added.';const d=document.createElement('div');d.className='pillar';d.innerHTML=`<h3>${label}</h3><div class=\"pillar-summary\">${headline}</div><details class=\"deep\"><summary>View deep dive</summary><div>${deep}</div></details><div class=\"context-box\"><strong>Your context</strong><br>${note}</div>`;root.appendChild(d)});$('pillarInputPanel').classList.add('hidden');$('pillarOutputPanel').classList.remove('hidden');$('editContextBtn').classList.remove('hidden')}"
    new_render = r'''function renderPillars(rec){const root=$('pillarResults');root.innerHTML='';Object.entries(pillarMeta).forEach(([key,[label,id]])=>{const p=rec.pillars?.[key]||{};const headline=p.headline||'High-level synthesis will appear here once the research pass is connected.';const note=p.user_note||'No user context added.';const d=document.createElement('div');d.className='pillar';const existing=p.deep_dive||'';d.innerHTML=`<h3>${label}</h3><div class="pillar-summary">${headline}</div><details class="deep"><summary>View deep dive</summary><div class="deep-body">${existing||'Open this section to generate the deep dive.'}</div></details><div class="context-box"><strong>Your context</strong><br>${note}</div>`;const details=d.querySelector('details');const body=d.querySelector('.deep-body');if(existing)details.dataset.loaded='1';details.addEventListener('toggle',async()=>{if(!details.open||details.dataset.loaded==='1'||details.dataset.loading==='1')return;details.dataset.loading='1';body.classList.add('deep-loading');body.textContent='Generating deep dive from the saved projection…';try{const j=await api('/api/deep-dive',{method:'POST',body:JSON.stringify({id:rec.id,pillar:key})});body.classList.remove('deep-loading');body.textContent=j.deep_dive||'No deep dive returned.';details.dataset.loaded='1';if(currentRecord?.id===rec.id){currentRecord.pillars=currentRecord.pillars||{};currentRecord.pillars[key]=currentRecord.pillars[key]||{};currentRecord.pillars[key].deep_dive=body.textContent}}catch(e){body.classList.remove('deep-loading');body.textContent='Deep dive failed: '+e.message}finally{details.dataset.loading='0'}});root.appendChild(d)});$('pillarInputPanel').classList.add('hidden');$('pillarOutputPanel').classList.remove('hidden');$('editContextBtn').classList.remove('hidden')}'''
    html = html.replace(old_render, new_render, 1)

    # QA controls are appended to the otherwise-identical payload shape.
    html = html.replace(
        "document.body.classList.add('draft-mode');",
        "const originalPayload=payload;payload=function(){const p=originalPayload();if($('qaScenario'))p.qa_scenario=$('qaScenario').value;if($('qaDelay'))p.qa_delay=parseInt($('qaDelay').value||'0',10);return p};\ndocument.body.classList.add('draft-mode');",
        1,
    )

    html = html.replace(
        'buildEvidence();loadPlayerDirectory();document.querySelectorAll',
        '''document.body.classList.add('draft-mode');
const draftBtn=$('draftGenerateBtn');
const draftLoading=$('draftLoading');
function setDraftLoading(on,msg=''){
  if(!draftBtn)return;
  draftBtn.disabled=on;
  draftBtn.textContent=on?'Researching…':'Generate projection';
  if(draftLoading){draftLoading.textContent=msg;draftLoading.classList.toggle('loading',on)}
}
if(draftBtn){draftBtn.addEventListener('click',async()=>{
  if(!$('player').value.trim()){draftLoading.textContent='Player is required.';return}
  if(!$('appFp').value.trim()){draftLoading.textContent='App projection is required.';$('appFp').focus();return}
  setDraftLoading(true,'''+("'Loading QA fixture — no paid request will be made…'" if QA_MODE else "'Searching current evidence and building the projection…'")+''');
  await saveRevision();
  if(currentRecord){
    document.body.classList.remove('draft-mode');document.body.classList.add('result-mode');
    setDraftLoading(false,'');
    window.scrollTo({top:0,behavior:'smooth'});
  }else{
    setDraftLoading(false,$('status').textContent||'Projection failed.');
  }
})}
buildEvidence();loadPlayerDirectory();document.querySelectorAll''',
        1,
    )
    return html


base.HTML = enhance_html(base.HTML)


def _user_notes(payload: dict) -> dict:
    pillars = payload.get("pillars") if isinstance(payload.get("pillars"), dict) else {}
    return {key: str((pillars.get(key) or {}).get("user_note") or "") for key in base.PILLARS}


def _research_shell(payload: dict) -> dict:
    return {
        "meta": {
            "player": payload.get("player"),
            "team": payload.get("team"),
            "opponent": payload.get("opponent"),
            "week": payload.get("week"),
            "position": payload.get("position") or "RB",
        },
        "evidence": {},
        "weather": {"status": "unknown", "summary": "QA fixture — weather not fetched.", "affected_components": []},
        "sources": {},
    }


def _last_real_record() -> dict | None:
    records = base.load_store().get("records") or []
    for record in reversed(records):
        if record.get("ai_mode") == "web_research":
            return record
    return None


def _merge_ai(payload: dict, research: dict, ai: dict) -> dict:
    enriched = dict(payload)
    meta = research.get("meta") or {}
    enriched["team"] = meta.get("team") or enriched.get("team") or ""
    enriched["opponent"] = meta.get("opponent") or enriched.get("opponent") or ""
    enriched["week"] = enriched.get("week") or meta.get("week") or ""
    position = str(meta.get("position") or enriched.get("position") or "RB").upper()
    enriched["position"] = position

    stats = dict(ai.get("stats") or {})
    if position == "QB":
        stats = {
            "pass_yards": stats.get("pass_yards", 0),
            "pass_tds": stats.get("pass_tds", 0),
            "interceptions": stats.get("interceptions", 0),
            "rush_yards": stats.get("qb_rush_yards", 0),
            "rush_tds": stats.get("qb_rush_tds", 0),
        }
    else:
        stats = {k: stats.get(k, 0) for k in ["carries", "rush_yards", "rush_tds", "rush_first_downs", "targets", "receptions", "rec_yards", "rec_tds", "rec_first_downs"]}
    enriched["stats"] = stats
    enriched["floor_fp"] = ai.get("floor_fp")
    enriched["ceiling_fp"] = ai.get("ceiling_fp")
    enriched["evidence"] = ai.get("evidence") or research.get("evidence") or {}

    notes = _user_notes(payload)
    ai_pillars = ai.get("pillars") or {}
    pillars = {}
    for key in base.PILLARS:
        src = ai_pillars.get(key) or {}
        pillars[key] = {
            "headline": str(src.get("headline") or ""),
            "deep_dive": "",
            "user_note": notes.get(key, ""),
        }
    enriched["pillars"] = pillars

    weather = research.get("weather") or {}
    enriched["weather"] = {
        "status": weather.get("status") or "unknown",
        "summary": weather.get("summary") or "",
        "fp_adjustment": 0,
        "affected_components": weather.get("affected_components") or [],
    }
    enriched["ai_meta"] = ai.get("ai_meta") or {}
    enriched["projection_summary"] = ai.get("projection_summary") or ""
    enriched["app_disagreement"] = ai.get("app_disagreement") or ""
    return enriched


def enrich_projection_payload(payload: dict) -> dict:
    if payload.get("app_projected_fp") in (None, ""):
        raise ValueError("App projection is required before generating a projection.")

    if QA_MODE:
        delay = max(0, min(int(payload.get("qa_delay") or 0), 20))
        if delay:
            time.sleep(delay)
        scenario = str(payload.get("qa_scenario") or "normal")
        research = _research_shell(payload)
        if scenario == "replay_last_real":
            last = _last_real_record()
            if not last:
                raise ValueError("No prior live-research projection is available to replay yet.")
            ai = replay_projection(last)
            # Reuse the saved player's metadata too, while preserving current scoring/app inputs.
            research["meta"].update({k: last.get(k) for k in ["player", "team", "opponent", "week", "position"]})
        else:
            ai = fixture_projection(payload, scenario)
        enriched = _merge_ai(payload, research, ai)
        enriched["ai_mode"] = "qa_fixture"
        return enriched

    if not is_configured():
        enriched = prior.enrich_projection_payload(payload)
        enriched["ai_mode"] = "fallback"
        return enriched

    research = prior.collect_evidence(
        str(payload.get("player") or ""),
        week=payload.get("week"),
        app_projection=payload.get("app_projected_fp"),
        user_notes=_user_notes(payload),
    )
    ai = research_projection(payload, research)
    enriched = _merge_ai(payload, research, ai)
    enriched["ai_mode"] = "web_research"
    return enriched


def _save_projection(payload: dict) -> dict:
    result = base.save_projection(payload)
    extras = {
        "ai_mode": payload.get("ai_mode"),
        "ai_meta": payload.get("ai_meta") or {},
        "projection_summary": payload.get("projection_summary") or "",
        "app_disagreement": payload.get("app_disagreement") or "",
    }
    store = base.load_store()
    for record in reversed(store.get("records") or []):
        if record.get("id") == result.get("id"):
            record.update(extras)
            result = dict(record)
            break
    base.save_store(store)
    return result


def _find_record(record_id: str) -> tuple[dict, dict]:
    store = base.load_store()
    for record in store.get("records") or []:
        if record.get("id") == record_id:
            return store, record
    raise ValueError("Projection revision not found.")


def _save_deep_dive(record_id: str, pillar_key: str) -> dict:
    store, record = _find_record(record_id)
    pillar = ((record.get("pillars") or {}).get(pillar_key) or {})
    if pillar.get("deep_dive"):
        return {"deep_dive": pillar["deep_dive"], "cached": True, "meta": pillar.get("deep_dive_meta") or {}}

    generated = fixture_deep_dive(record, pillar_key) if QA_MODE else generate_deep_dive(record, pillar_key)
    record.setdefault("pillars", {}).setdefault(pillar_key, {})["deep_dive"] = generated["text"]
    record["pillars"][pillar_key]["deep_dive_meta"] = generated.get("meta") or {}
    base.save_store(store)
    return {"deep_dive": generated["text"], "cached": False, "meta": generated.get("meta") or {}}


class Handler(prior.Handler):
    def do_POST(self):
        if self.path == "/api/projection":
            try:
                payload = enrich_projection_payload(self.read_json())
                with base.LOCK:
                    result = _save_projection(payload)
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, status=400)
            return
        if self.path == "/api/deep-dive":
            try:
                payload = self.read_json()
                with base.LOCK:
                    result = _save_deep_dive(str(payload.get("id") or ""), str(payload.get("pillar") or ""))
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, status=400)
            return
        super().do_POST()


def main():
    base.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if QA_MODE:
        mode = "QA fixtures (zero paid API calls)"
    else:
        mode = "AI + live web research" if is_configured() else "local fallback (configure API key for AI research)"
    print(f"Projection Workbench {base.APP_VERSION}: http://{base.HOST}:{base.PORT}")
    print(f"Projection mode: {mode}")
    print(f"Local projection store: {base.DATA_FILE}")
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
