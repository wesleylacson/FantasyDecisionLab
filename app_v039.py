#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.9 — dual-source FantasyPros + Vegas context."""
from __future__ import annotations

import io
import json
import re
import threading
import webbrowser
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import requests

import app_v038 as base

APP_VERSION = "0.3.9"
HOST, PORT = base.HOST, base.PORT
VEGAS_LOCK = threading.Lock()
VEGAS_CACHE = Path.home() / "Downloads" / "fantasy_decision_lab_cache" / "vegas"
VEGAS_CACHE.mkdir(parents=True, exist_ok=True)
VEGAS_TTL_SECONDS = 15 * 60
UA = base.base.base.compare_base.core.legacy.UA


def _norm(s: str) -> str:
    s = str(s or "")
    s = re.sub(r"\s*[-–—]\s*.*$", "", s)
    s = re.sub(r"[^A-Za-z0-9 ]+", "", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def _num(v):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = str(v).strip().replace("%", "").replace(",", "")
        if s in {"", "—", "-", "nan", "None"}:
            return None
        return float(s)
    except Exception:
        return None


def _flat_col(c) -> str:
    if isinstance(c, tuple):
        c = " ".join(str(x) for x in c if str(x) != "nan")
    return re.sub(r"\s+", " ", str(c)).strip()


def _pick_col(cols, *needles):
    normed = {c: _norm(c) for c in cols}
    for needle_set in needles:
        parts = [_norm(x) for x in (needle_set if isinstance(needle_set, (tuple, list)) else (needle_set,))]
        for c, n in normed.items():
            if all(p in n for p in parts):
                return c
    return None


def _source_url(position: str) -> str:
    return "https://www.firstdown.studio/rankings/qb" if position == "QB" else "https://www.firstdown.studio/rankings/flex"


def _cache_path(position: str) -> Path:
    return VEGAS_CACHE / f"{position.lower()}_week_{base.base.base.compare_base.core.WEEK}.json"


def _read_cache(position: str):
    path = _cache_path(position)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cache_age_seconds(position: str):
    path = _cache_path(position)
    if not path.exists():
        return None
    return max(0.0, datetime.now().timestamp() - path.stat().st_mtime)


def _parse_first_down(position: str) -> dict:
    url = _source_url(position)
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    html = r.text
    m = re.search(r"Updated\s*:?\s*([^<\n]+)", html, flags=re.I)
    source_updated = re.sub(r"\s+", " ", m.group(1)).strip()[:80] if m else None

    tables = pd.read_html(io.StringIO(html))
    if not tables:
        raise RuntimeError("First Down returned no readable rankings table.")

    best = None
    best_score = -1
    for t in tables:
        t = t.copy()
        t.columns = [_flat_col(c) for c in t.columns]
        cols = list(t.columns)
        player_col = _pick_col(cols, "player", "name")
        pts_col = _pick_col(cols, "pts", "points", ("fantasy", "point"), "fp")
        score = (5 if player_col else 0) + (5 if pts_col else 0) + min(len(t), 100) / 100
        if score > best_score:
            best, best_score = t, score
    if best is None:
        raise RuntimeError("Could not identify First Down rankings table.")

    cols = list(best.columns)
    player_col = _pick_col(cols, "player", "name")
    pts_col = _pick_col(cols, "pts", "points", ("fantasy", "point"), "fp")
    pos_col = _pick_col(cols, "pos", "position")
    rec_col = _pick_col(cols, "rec", "receptions")
    recyd_col = _pick_col(cols, ("rec", "yd"), ("receiv", "yd"))
    rushyd_col = _pick_col(cols, ("rush", "yd"), ("rushing", "yd"))
    rushatt_col = _pick_col(cols, ("rush", "att"), ("rushing", "att"))
    td_col = _pick_col(cols, ("td", "exp"), ("touchdown", "exp"), "td")
    passyd_col = _pick_col(cols, ("pass", "yd"))
    passtd_col = _pick_col(cols, ("pass", "td"))
    int_col = _pick_col(cols, "int")
    rushtd_col = _pick_col(cols, ("rush", "td"))

    if not player_col or not pts_col:
        raise RuntimeError(f"First Down table columns changed: {cols}")

    rows = []
    for _, row in best.iterrows():
        player = str(row.get(player_col) or "").strip()
        if not player or player.lower() == "nan":
            continue
        pos = str(row.get(pos_col) or "").upper().strip() if pos_col else ""
        if position != "QB" and pos and position not in pos:
            continue
        half = _num(row.get(pts_col))
        if half is None:
            continue
        rec = _num(row.get(rec_col)) if rec_col else None
        if position == "QB":
            std = ppr = half
        else:
            recn = rec or 0.0
            std = half - 0.5 * recn
            ppr = half + 0.5 * recn
        rows.append({
            "player": player,
            "norm": _norm(player),
            "position": position,
            "half_ppr": half,
            "std_fp": round(std, 3),
            "ppr_fp": round(ppr, 3),
            "rush_yds": _num(row.get(rushyd_col)) if rushyd_col else None,
            "rush_att": _num(row.get(rushatt_col)) if rushatt_col else None,
            "rec": rec,
            "rec_yds": _num(row.get(recyd_col)) if recyd_col else None,
            "td_exp": _num(row.get(td_col)) if td_col else None,
            "pass_yds": _num(row.get(passyd_col)) if passyd_col else None,
            "pass_td": _num(row.get(passtd_col)) if passtd_col else None,
            "int": _num(row.get(int_col)) if int_col else None,
            "rush_td_exp": _num(row.get(rushtd_col)) if rushtd_col else None,
        })
    if not rows:
        raise RuntimeError(f"First Down returned no usable {position} rows.")

    retrieved = datetime.now().astimezone().isoformat(timespec="seconds")
    payload = {"position": position, "source_url": url, "source_updated": source_updated, "retrieved_at": retrieved, "rows": rows}
    _cache_path(position).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def vegas_table(position: str, force: bool = False) -> tuple[dict, str, str | None]:
    """Return payload, state ('live'/'cached'), and optional warning."""
    cached = _read_cache(position)
    age = _cache_age_seconds(position)
    if cached and not force and age is not None and age <= VEGAS_TTL_SECONDS:
        return cached, "cached", None
    try:
        return _parse_first_down(position), "live", None
    except Exception as exc:
        if cached:
            return cached, "cached", f"Live Vegas refresh failed; kept last good snapshot: {exc}"
        raise


def _resolve_vegas(name: str, rows: list[dict]) -> dict:
    n = _norm(name)
    exact = [r for r in rows if r.get("norm") == n]
    if len(exact) == 1:
        return exact[0]
    contains = [r for r in rows if n in r.get("norm", "") or r.get("norm", "") in n]
    if len(contains) == 1:
        return contains[0]
    parts = n.split()
    if parts:
        last = parts[-1]
        initial = parts[0][0] if parts[0] else ""
        cand = []
        for r in rows:
            rp = r.get("norm", "").split()
            if rp and rp[-1] == last and (not initial or rp[0].startswith(initial)):
                cand.append(r)
        if len(cand) == 1:
            return cand[0]
    raise ValueError(f"Vegas data could not uniquely resolve {name}.")


def vegas_compare(position: str, scoring: str, a_name: str, b_name: str, force=False) -> dict:
    position = str(position or "WR").upper()
    scoring = "STD" if str(scoring or "PPR").upper() == "STD" else "PPR"
    if position == "QB":
        scoring = "STD"
    with VEGAS_LOCK:
        payload, state, warning = vegas_table(position, force=force)
    rows = payload["rows"]
    a = _resolve_vegas(a_name, rows)
    b = _resolve_vegas(b_name, rows)
    fp_key = "std_fp" if scoring == "STD" else "ppr_fp"
    ranked = sorted(rows, key=lambda x: (x.get(fp_key) is None, -(x.get(fp_key) or -999)))
    rank_map = {id(r): i + 1 for i, r in enumerate(ranked)}
    a_fp, b_fp = a.get(fp_key), b.get(fp_key)
    winner = a if a_fp >= b_fp else b
    gap = abs((a_fp or 0) - (b_fp or 0))

    def view(r):
        return {
            "player": r["player"], "fp": r.get(fp_key), "rank": rank_map.get(id(r)),
            "rush_yds": r.get("rush_yds"), "rush_att": r.get("rush_att"),
            "rec": r.get("rec"), "rec_yds": r.get("rec_yds"), "td_exp": r.get("td_exp"),
            "pass_yds": r.get("pass_yds"), "pass_td": r.get("pass_td"), "int": r.get("int"),
            "rush_td_exp": r.get("rush_td_exp"),
        }
    return {
        "available": True, "position": position, "scoring": scoring,
        "player_a": view(a), "player_b": view(b), "winner": winner["player"], "fp_gap": round(gap, 3),
        "source_updated": payload.get("source_updated"), "retrieved_at": payload.get("retrieved_at"),
        "source_state": state, "warning": warning, "source_url": payload.get("source_url"),
    }


def start_sit_html():
    h = base.start_sit_html()
    css = r'''
.vegas-card{display:none;margin-top:18px;padding:22px}.vegas-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;margin-bottom:14px}.vegas-title{font-size:13px;text-transform:uppercase;letter-spacing:.1em;font-weight:900}.vegas-meta{color:var(--muted);font-size:11px;margin-top:5px;line-height:1.45}.vegas-badge{font-size:10px;font-weight:900;text-transform:uppercase;padding:6px 9px;border:1px solid #315174;border-radius:999px;color:#63e6be}.vegas-badge.cached{color:#ffd166}.vegas-table{width:100%;border-collapse:collapse;font-size:13px}.vegas-table th,.vegas-table td{padding:9px 7px;border-bottom:1px solid #1d304c;text-align:right}.vegas-table th:first-child,.vegas-table td:first-child{text-align:left;color:var(--muted)}.vegas-table th{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}.vegas-win{color:#63e6be;font-weight:900}.vegas-lean{margin-top:14px;padding:13px;background:#091426;border:1px solid #284563;border-radius:13px}.vegas-lean b{display:block;font-size:16px}.vegas-lean span{display:block;color:var(--muted);font-size:11px;margin-top:4px}.vegas-error{display:none;margin-top:18px;padding:16px;border:1px dashed #365077;border-radius:16px;color:#9fb0c9;background:#0a1527}.refresh-summary{color:var(--muted);font-size:12px}
'''
    h = h.replace('</style></head>', css + '</style></head>')
    h = re.sub(
        r'<div class="refresh-row">.*?</div></section>',
        '<div class="refresh-row"><button id="refreshSources" class="btn secondary">↻ Refresh sources</button><span id="refreshSummary" class="refresh-summary"></span></div></section>',
        h,
        count=1,
        flags=re.S,
    )
    inject = r'''
<script>
(function(){
const result=$('result');
const vc=document.createElement('section');vc.id='vegasCard';vc.className='panel vegas-card';
vc.innerHTML='<div class="vegas-head"><div><div class="vegas-title">Vegas market</div><div id="vegasMeta" class="vegas-meta">First Down-derived contextual tiebreaker</div></div><span id="vegasBadge" class="vegas-badge">Available</span></div><div id="vegasBody"></div>';
result.parentNode.insertBefore(vc,result.nextSibling);
const ve=document.createElement('div');ve.id='vegasError';ve.className='vegas-error';result.parentNode.insertBefore(ve,vc.nextSibling);
function vv(x){return x===null||x===undefined?'—':(typeof x==='number'?Number(x).toFixed(x%1?2:0):x)}
function setVegasUnavailable(msg){vc.style.display='none';ve.style.display='block';ve.textContent='Vegas market unavailable: '+msg}
function renderVegas(j){ve.style.display='none';vc.style.display='block';const a=j.player_a,b=j.player_b;const badge=$('vegasBadge');badge.textContent=j.source_state==='live'?'Live':'Cached';badge.className='vegas-badge '+(j.source_state==='cached'?'cached':'');const src=j.source_updated?'Source updated: '+j.source_updated:'Source update time unavailable';const got=j.retrieved_at?'Retrieved: '+new Date(j.retrieved_at).toLocaleString():'';$('vegasMeta').textContent=[src,got,j.warning].filter(Boolean).join(' · ');
const rows=j.position==='QB'?[['Projected FP',a.fp,b.fp],['Position rank','QB'+a.rank,'QB'+b.rank],['Pass yards',a.pass_yds,b.pass_yds],['Pass TD',a.pass_td,b.pass_td],['INT',a.int,b.int],['Rush yards',a.rush_yds,b.rush_yds],['Rush TD exp.',a.rush_td_exp,b.rush_td_exp]]:[['Projected FP',a.fp,b.fp],['Position rank',j.position+a.rank,j.position+b.rank],['Rush yards',a.rush_yds,b.rush_yds],['Receptions',a.rec,b.rec],['Receiving yards',a.rec_yds,b.rec_yds],['TD expectation',a.td_exp,b.td_exp]];
const body=rows.map(r=>{let ca='',cb='';if(typeof r[1]==='number'&&typeof r[2]==='number'){if(r[1]>r[2])ca='vegas-win';if(r[2]>r[1])cb='vegas-win'}if(String(r[1]).startsWith(j.position)&&String(r[2]).startsWith(j.position)){if(parseInt(String(r[1]).replace(/\D/g,''))<parseInt(String(r[2]).replace(/\D/g,'')))ca='vegas-win';else cb='vegas-win'}return `<tr><td>${r[0]}</td><td class="${ca}">${vv(r[1])}</td><td class="${cb}">${vv(r[2])}</td></tr>`}).join('');
$('vegasBody').innerHTML=`<table class="vegas-table"><thead><tr><th>Market input</th><th>${a.player}</th><th>${b.player}</th></tr></thead><tbody>${body}</tbody></table><div class="vegas-lean"><b>Vegas lean: ${j.winner}</b><span>+${Number(j.fp_gap).toFixed(2)} projected ${j.scoring==='STD'?'standard':'PPR'} points</span></div>`;
}
async function loadVegas(force=false){const a=$('a').value.trim(),b=$('b').value.trim();if(!a||!b)return null;try{const r=await fetch(`/api/vegas?position=${position}&scoring=${scoring}&a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}${force?'&force=1':''}`);const j=await r.json();if(!r.ok)throw new Error(j.error||'Vegas request failed');renderVegas(j);return {ok:true,j}}catch(e){setVegasUnavailable(e.message);return {ok:false,error:e.message}}}
const oldCompare=compare;compare=async function(){const vp=loadVegas(false);await oldCompare();await vp};
async function refreshSources(){const a=$('a').value.trim(),b=$('b').value.trim();if(!a||!b){showErr('Choose two '+position+'s before refreshing sources.');return}const btn=$('refreshSources');btn.disabled=true;$('refreshSummary').textContent='Refreshing FantasyPros + Vegas…';$('error').style.display='none';const fp=(async()=>{try{const r=await fetch('/api/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scope:'matchup',position,scoring,a,b})});const j=await r.json();if(!r.ok)throw new Error(j.error||'FantasyPros refresh failed');const cr=await fetch(`/api/compare?position=${position}&scoring=${scoring}&a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);const cj=await cr.json();if(!cr.ok)throw new Error(cj.error||'Comparison failed after refresh');if(cj.redirect_only){showOutage(cj);return {ok:false,label:'FantasyPros unavailable'}}render(cj);return {ok:true,label:'FantasyPros refreshed'}}catch(e){return {ok:false,label:'FantasyPros unavailable'}}})();const vg=loadVegas(true);const [fr,vr]=await Promise.all([fp,vg]);$('refreshSummary').textContent=`${fr.label} · ${vr&&vr.ok?'Vegas refreshed':'Vegas unavailable'}`;btn.disabled=false}
$('refreshSources').addEventListener('click',refreshSources);
})();
</script>
'''
    h = h.replace('</body>', inject + '</body>')
    return h


class Handler(base.Handler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(base.base.base.compare_base.core.ui.HOME_HTML.replace("v0.2 ·", "v0.3.9 ·"))
            return
        if parsed.path == "/start-sit":
            self.send_html(start_sit_html())
            return
        if parsed.path == "/api/vegas":
            q = parse_qs(parsed.query)
            position = ((q.get("position") or ["WR"])[0]).upper()
            scoring = (q.get("scoring") or ["PPR"])[0]
            a_name = (q.get("a") or [""])[0]
            b_name = (q.get("b") or [""])[0]
            force = (q.get("force") or ["0"])[0] in {"1", "true", "yes"}
            try:
                self.send_json(vegas_compare(position, scoring, a_name, b_name, force=force))
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=503)
            return
        return super().do_GET()


def main():
    print(f"Loading Fantasy Decision Lab v{APP_VERSION}…", flush=True)
    base.base.base.compare_base.core.initialize()
    print(f"Fantasy Decision Lab: http://{HOST}:{PORT}", flush=True)
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
