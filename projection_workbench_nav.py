from __future__ import annotations

import os

import projection_workbench_app as workbench
import projection_tracker as tracker

QA_MODE = bool(workbench.app.QA_MODE)

css = r'''
.module-nav{display:flex;align-items:center;justify-content:flex-start;margin:0 0 18px}
.module-back{display:inline-flex;align-items:center;gap:7px;color:#dbe4f3;text-decoration:none;font-weight:800;font-size:14px;padding:9px 12px;border:1px solid #304568;border-radius:12px;background:#0a1629}
.module-back:hover{border-color:#526b93;background:#0d1b31}
.module-back.disabled{opacity:.42;cursor:default;pointer-events:none}
.app-stat-warning{display:none;margin-top:12px;padding:10px 12px;border:1px solid #8a662c;border-radius:12px;background:#2a2111;color:#ffd98a;font-size:12px;line-height:1.45}
.app-stat-warning.show{display:block}
.app-stat-note{color:#96a8c4;font-size:12px;margin:2px 0 14px;line-height:1.45}
'''

if QA_MODE:
    back = '<div class="module-nav"><span class="module-back disabled" aria-disabled="true">← Back to modules</span></div>'
else:
    back = '<div class="module-nav"><a class="module-back" href="http://127.0.0.1:8765/">← Back to modules</a></div>'

html = workbench.base.HTML
html = html.replace('</style></head>', css + '</style></head>', 1)
marker = '<body><main class="shell">'
if marker not in html:
    raise RuntimeError("Could not find Projection Workbench shell for module navigation.")
html = html.replace(marker, marker + back, 1)

# Add app-provider selection beside the required total benchmark.
app_fp_field = '<div class="field"><label>App projection <span class="required">Required</span></label><input id="appFp" type="number" step="0.01" min="0" placeholder="Required benchmark"></div>'
app_fp_with_source = app_fp_field + '<div class="field"><label>App source</label><select id="appSource"><option value="espn" selected>ESPN</option><option value="sleeper">Sleeper</option><option value="other">Other</option></select></div>'
if app_fp_field in html:
    html = html.replace(app_fp_field, app_fp_with_source, 1)

# Component app projections are optional. For ESPN, an all-blank stat line warns but never blocks.
app_stats_panel = r'''
<div id="appStatsPanel" class="panel">
  <div class="section-label">App projected stat line <span class="muted">· optional</span></div>
  <p class="app-stat-note">Capture the visible provider components when available. Leave unavailable values blank rather than back-solving them from the fantasy-point total.</p>
  <div id="appSkillStats" class="grid">
    <div class="field"><label>App carries</label><input class="app-stat" id="app_carries" type="number" step="0.1"></div>
    <div class="field"><label>App rush yards</label><input class="app-stat" id="app_rush_yards" type="number" step="0.1"></div>
    <div class="field"><label>App rush TD</label><input class="app-stat" id="app_rush_tds" type="number" step="0.01"></div>
    <div class="field"><label>App targets</label><input class="app-stat" id="app_targets" type="number" step="0.1"></div>
    <div class="field"><label>App receptions</label><input class="app-stat" id="app_receptions" type="number" step="0.1"></div>
    <div class="field"><label>App rec yards</label><input class="app-stat" id="app_rec_yards" type="number" step="0.1"></div>
    <div class="field"><label>App rec TD</label><input class="app-stat" id="app_rec_tds" type="number" step="0.01"></div>
  </div>
  <div id="appQbStats" class="grid hidden">
    <div class="field"><label>App pass yards</label><input class="app-stat" id="app_pass_yards" type="number" step="1"></div>
    <div class="field"><label>App pass TD</label><input class="app-stat" id="app_pass_tds" type="number" step="0.01"></div>
    <div class="field"><label>App rush attempts</label><input class="app-stat" id="app_qb_carries" type="number" step="0.1"></div>
    <div class="field"><label>App rush yards</label><input class="app-stat" id="app_qb_rush_yards" type="number" step="0.1"></div>
    <div class="field"><label>App rush TD</label><input class="app-stat" id="app_qb_rush_tds" type="number" step="0.01"></div>
  </div>
  <div id="appStatWarning" class="app-stat-warning">ESPN total is present, but no ESPN component stats are entered. You can still generate the projection; the tracker will save only the ESPN fantasy-point benchmark.</div>
</div>
'''
hero_marker = '<div class="panel hero post-only">'
if hero_marker in html:
    html = html.replace(hero_marker, app_stats_panel + '\n' + hero_marker, 1)

# Final payload/UI wrapper. This intentionally sits after the existing QA and research wrappers.
js_patch = r'''
const fdlPayloadBeforeAppStats=payload;
function optionalAppNumber(id){const el=$(id);if(!el||el.value==='')return null;const v=parseFloat(el.value);return Number.isFinite(v)?v:null}
function appStatsPayload(){
  if($('position').value==='QB')return {
    carries:optionalAppNumber('app_qb_carries'),pass_yards:optionalAppNumber('app_pass_yards'),
    rush_yards:optionalAppNumber('app_qb_rush_yards'),pass_tds:optionalAppNumber('app_pass_tds'),
    rush_tds:optionalAppNumber('app_qb_rush_tds'),receptions:null,targets:null,rec_yards:null,rec_tds:null
  };
  return {
    carries:optionalAppNumber('app_carries'),receptions:optionalAppNumber('app_receptions'),targets:optionalAppNumber('app_targets'),
    pass_yards:null,rush_yards:optionalAppNumber('app_rush_yards'),rec_yards:optionalAppNumber('app_rec_yards'),pass_tds:null,
    rush_tds:optionalAppNumber('app_rush_tds'),rec_tds:optionalAppNumber('app_rec_tds')
  };
}
payload=function(){const p=fdlPayloadBeforeAppStats();p.app_source=$('appSource')?.value||'espn';p.app_stats=appStatsPayload();return p};
function updateAppStatsUi(){
  const qb=$('position').value==='QB';
  $('appQbStats')?.classList.toggle('hidden',!qb);$('appSkillStats')?.classList.toggle('hidden',qb);
  const stats=appStatsPayload();const hasAny=Object.values(stats).some(v=>v!==null);
  const shouldWarn=($('appSource')?.value==='espn'&&!hasAny&&Boolean($('appFp')?.value));
  $('appStatWarning')?.classList.toggle('show',shouldWarn);
}
document.querySelectorAll('.app-stat').forEach(el=>el.addEventListener('input',updateAppStatsUi));
$('appFp')?.addEventListener('input',updateAppStatsUi);$('appSource')?.addEventListener('change',updateAppStatsUi);$('position')?.addEventListener('change',updateAppStatsUi);
const fdlApplyResearchResultForCost=applyResearchResult;
applyResearchResult=function(rec){fdlApplyResearchResultForCost(rec);if(rec.cost_estimate_usd!=null){$('researchStatus').textContent += ` · est. API cost $${Number(rec.cost_estimate_usd).toFixed(4)}`;}updateAppStatsUi();};
updateAppStatsUi();
'''
js_marker = 'buildEvidence();loadPlayerDirectory();document.querySelectorAll'
if js_marker in html:
    html = html.replace(js_marker, js_patch + '\n' + js_marker, 1)

workbench.base.HTML = html

# Preserve app component values on each local revision. The tracker remains one canonical row,
# but the local projection store keeps every revision for audit/history.
_original_save_projection = workbench.app._save_projection


def _estimate_projection_cost(record: dict) -> tuple[float | None, dict]:
    if record.get("ai_mode") != "web_research":
        return (0.0 if record.get("ai_mode") == "qa_fixture" else None), {}
    meta = record.get("ai_meta") if isinstance(record.get("ai_meta"), dict) else {}
    usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
    try:
        input_tokens = float(usage.get("input_tokens") or 0)
        output_tokens = float(usage.get("output_tokens") or 0)
        details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
        cached_tokens = float(details.get("cached_tokens") or 0)
        uncached_tokens = max(0.0, input_tokens - cached_tokens)
        web_calls = float(meta.get("web_search_calls") or 0)
        # GPT-6 Luna standard short-context pricing as of 2026-10-22:
        # $0.10/M uncached input, $0.01/M cached input, $0.50/M output, $10/1k web searches.
        token_cost = (uncached_tokens * 0.10 + cached_tokens * 0.01 + output_tokens * 0.50) / 1_000_000
        web_cost = web_calls * 0.01
        total = token_cost + web_cost
        return round(total, 6), {
            "model": meta.get("model"),
            "input_tokens": int(input_tokens),
            "cached_input_tokens": int(cached_tokens),
            "output_tokens": int(output_tokens),
            "web_search_calls": int(web_calls),
            "token_cost_usd": round(token_cost, 6),
            "web_search_cost_usd": round(web_cost, 6),
        }
    except Exception:
        return None, {}


def _save_projection_with_app_stats(payload: dict) -> dict:
    result = _original_save_projection(payload)
    extras = {
        "app_source": str(payload.get("app_source") or "espn").lower(),
        "app_stats": payload.get("app_stats") if isinstance(payload.get("app_stats"), dict) else {},
    }
    cost, breakdown = _estimate_projection_cost(result)
    if cost is not None:
        extras["cost_estimate_usd"] = cost
        extras["cost_breakdown"] = breakdown
    store = workbench.base.load_store()
    for record in reversed(store.get("records") or []):
        if record.get("id") == result.get("id"):
            record.update(extras)
            result = dict(record)
            break
    workbench.base.save_store(store)
    return result


workbench.app._save_projection = _save_projection_with_app_stats

# Extend the existing Sheet payload with the provider component projection fields. The deployed
# Apps Script bridge writes these into the existing ESPN Proj * columns when app_source=espn.
_original_sheet_payload = tracker.sheet_payload


def _sheet_payload_with_app_stats(record: dict) -> dict:
    payload = _original_sheet_payload(record)
    out = payload.get("record") or {}
    app_stats = record.get("app_stats") if isinstance(record.get("app_stats"), dict) else {}
    out["app_source"] = str(record.get("app_source") or "espn").lower()
    for key in ["carries", "receptions", "targets", "pass_yards", "rush_yards", "rec_yards", "pass_tds", "rush_tds", "rec_tds"]:
        out[f"app_{key}"] = app_stats.get(key)
    return payload


tracker.sheet_payload = _sheet_payload_with_app_stats

# When the main Fantasy Decision Lab starts the workbench on demand, the browser is already
# navigating to it. Suppress the standalone launcher's second automatic browser tab.
if os.environ.get("FANTASY_PROJECTION_NO_BROWSER") == "1":
    workbench.webbrowser.open = lambda *_args, **_kwargs: True


def main():
    workbench.main()


if __name__ == "__main__":
    main()
