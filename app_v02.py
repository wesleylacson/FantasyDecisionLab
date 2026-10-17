#!/usr/bin/env python3
"""Fantasy Decision Lab v0.2: home navigation + PPR/Standard Start/Sit."""
from __future__ import annotations
import json, threading, webbrowser
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import app as core

APP_VERSION='0.2.0'
LOCK=threading.Lock()
POSITION_SCORING={}

def norm_scoring(x):
    x=str(x or 'PPR').upper()
    if x not in {'PPR','STD'}: raise ValueError('Choose PPR or STD scoring.')
    return x

def collect_ballots(position):
    ballots={}; key='STD' if position=='QB' else core.SCORING
    def absorb(obj):
        if not isinstance(obj,dict): return
        rankings=obj.get('rankings'); bucket=rankings.get(key) if isinstance(rankings,dict) else None
        if isinstance(bucket,dict):
            for pid,rows in bucket.items():
                dest=ballots.setdefault(str(pid),{})
                if isinstance(rows,list):
                    for row in rows:
                        if isinstance(row,dict):
                            try: dest[str(row.get('expert_id'))]=float(row.get('rank'))
                            except Exception: pass
        for value in obj.values():
            if isinstance(value,dict): absorb(value)
    for _,data in core.iter_json_payloads(position): absorb(data)
    return ballots

# The v0.1 engine already reads core.SCORING for ranking-page URLs. Replace only
# its ballot reader so RB/WR/TE can use STD as well as PPR; QB stays STD.
core.collect_ballots=collect_ballots

def ensure_scoring(position, scoring):
    scoring=norm_scoring(scoring)
    if POSITION_SCORING.get(position)==scoring and position in core.STATE['positions']:
        return
    core.SCORING=scoring
    core.rebuild_position_state(position)
    POSITION_SCORING[position]=scoring

def initialize():
    core.STATE['current_accuracy']=core.read_accuracy(2026)
    core.STATE['prior_accuracy']=core.read_accuracy(2025)
    core.SCORING='PPR'
    for p in core.POSITIONS:
        core.rebuild_position_state(p); POSITION_SCORING[p]='PPR'

HOME_HTML=r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fantasy Decision Lab</title><style>
:root{--bg:#090d18;--line:#27324a;--text:#f5f7fb;--muted:#9aa6bd;--cyan:#39d0ff;--green:#55d6a4}*{box-sizing:border-box}body{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;background:radial-gradient(circle at 12% 0%,#172341 0,#090d18 35%,#070a12 100%);color:var(--text);min-height:100vh}.shell{max-width:1180px;margin:auto;padding:28px 18px 60px}.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:26px}.brand{font-weight:850}.brand span{color:var(--cyan)}.badge{font-size:12px;color:#cbd5e1;border:1px solid var(--line);padding:7px 10px;border-radius:999px;background:#0c1322}h1{font-size:clamp(30px,5vw,52px);margin:0 0 8px;letter-spacing:-1.5px}.sub{color:var(--muted);font-size:17px;line-height:1.5;max-width:760px}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin-top:30px}.module{display:block;text-decoration:none;text-align:left;padding:24px;border-radius:20px;border:1px solid var(--line);background:linear-gradient(180deg,rgba(22,32,51,.96),rgba(13,20,35,.96));color:var(--text);min-height:165px;transition:.2s}.live:hover{transform:translateY(-2px);border-color:#445274}.dead{opacity:.55}.icon{font-size:28px;margin-bottom:26px}.module h3{margin:0 0 7px;font-size:22px}.module p{margin:0;color:var(--muted);line-height:1.4}.dot{display:inline-block;width:8px;height:8px;background:var(--green);border-radius:50%;margin-right:7px}@media(max-width:760px){.grid{grid-template-columns:1fr}}</style></head><body><div class="shell"><div class="topbar"><div class="brand">FANTASY <span>DECISION LAB</span></div><div class="badge">v0.2 · Week 6</div></div><h1>Your decisions, not another fantasy app.</h1><div class="sub">Four focused workflows. Start/Sit is live; the other modules are parked until we build them properly.</div><div class="grid"><a class="module live" href="/start-sit"><div class="icon">⚖️</div><h3><span class="dot"></span>Start / Sit</h3><p>Compare full consensus, accuracy-weighted consensus, and elite-ranker panels in PPR or standard scoring.</p></a><div class="module dead"><div class="icon">🧲</div><h3>Waiver Wire Decision</h3><p>Pickup vs drop, immediate value, ROS value, roster fit, and scarcity.</p></div><div class="module dead"><div class="icon">📈</div><h3>Weekly Projection</h3><p>Our projection workflow, matchup layers, and app-comparison tracker.</p></div><div class="module dead"><div class="icon">🔁</div><h3>Trade Analyzer / Recommender</h3><p>Value, fit, replacement cost, opponent leverage, and recommendations.</p></div></div></div></body></html>'''

def start_sit_html():
    h=core.HTML
    css='.topnav{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:18px}.backlink{color:#dbe4f3;text-decoration:none;font-weight:800;font-size:14px}.scoring-wrap{display:flex;gap:8px;align-items:center}.scoring-label{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);font-weight:800;margin-right:3px}.score-toggle{border:1px solid #304568;background:#091426;color:#c9d6e8;border-radius:999px;padding:9px 13px;font-size:12px;font-weight:900;cursor:pointer}.score-toggle.active{background:linear-gradient(90deg,var(--accent),var(--accent2));border-color:transparent;color:#06111f}'
    h=h.replace('</style></head>',css+'</style></head>')
    h=h.replace('<body><main class="shell">','<body><main class="shell"><div class="topnav"><a class="backlink" href="/">← Back to modules</a><div class="scoring-wrap"><span class="scoring-label">Scoring</span><button class="score-toggle" data-scoring="STD">Standard</button><button class="score-toggle active" data-scoring="PPR">PPR</button></div></div>')
    h=h.replace("let position='WR';","let position='WR';let scoring='PPR';")
    h=h.replace("fetch('/api/players?position='+position)","fetch('/api/players?position='+position+'&scoring='+scoring)")
    h=h.replace("async function selectPosition(pos){position=pos;","async function selectScoring(sc){scoring=sc;document.querySelectorAll('.score-toggle').forEach(b=>b.classList.toggle('active',b.dataset.scoring===sc));$('result').style.display='none';$('error').style.display='none';try{await loadPlayers()}catch(e){showErr(e.message)}}\nasync function selectPosition(pos){position=pos;")
    h=h.replace('?position=${position}&a=','?position=${position}&scoring=${scoring}&a=')
    h=h.replace('JSON.stringify({scope,position,a,b})','JSON.stringify({scope,position,scoring,a,b})')
    h=h.replace("$('heroKicker').textContent=j.position+' weighted-full recommendation';","$('heroKicker').textContent=j.position+' • '+(j.scoring==='STD'?'Standard':'PPR')+' • weighted-full recommendation';")
    h=h.replace("document.querySelectorAll('.pos').forEach(b=>b.addEventListener('click',()=>selectPosition(b.dataset.pos)));","document.querySelectorAll('.pos').forEach(b=>b.addEventListener('click',()=>selectPosition(b.dataset.pos)));document.querySelectorAll('.score-toggle').forEach(b=>b.addEventListener('click',()=>selectScoring(b.dataset.scoring)));")
    return h

class Handler(core.Handler):
    def send_html(self,h):
        data=h.encode('utf-8'); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        parsed=urlparse(self.path)
        if parsed.path!='/api/refresh': return super().do_POST()
        try:
            n=int(self.headers.get('Content-Length','0')); body=json.loads(self.rfile.read(n).decode() or '{}')
            scope=str(body.get('scope') or '').lower(); p=str(body.get('position') or 'WR').upper(); s=norm_scoring(body.get('scoring'))
            with LOCK:
                ensure_scoring(p,s); core.SCORING=s
                if scope=='matchup': result=core.refresh_matchup(p,str(body.get('a') or ''),str(body.get('b') or ''))
                elif scope=='position': result=core.invalidate_position(p); POSITION_SCORING[p]=s
                elif scope=='all': result=core.invalidate_all(); POSITION_SCORING.update({x:s for x in core.POSITIONS})
                else: raise ValueError('Refresh scope must be matchup, position, or all.')
            result['scoring']=s; self.send_json(result)
        except Exception as e: self.send_json({'error':str(e)},status=400)
    def do_GET(self):
        parsed=urlparse(self.path)
        if parsed.path=='/': self.send_html(HOME_HTML); return
        if parsed.path=='/start-sit': self.send_html(start_sit_html()); return
        if parsed.path in {'/api/players','/api/compare'}:
            q=parse_qs(parsed.query); p=((q.get('position') or ['WR'])[0]).upper(); s=norm_scoring((q.get('scoring') or ['PPR'])[0])
            try:
                with LOCK:
                    ensure_scoring(p,s); core.SCORING=s
                    if parsed.path=='/api/players':
                        st=core.STATE['positions'][p]; d,b=st['directory'],st['ballots']; players=[]
                        for _,r in d.sort_values('directory_rank',na_position='last').iterrows():
                            pid=str(r['player_id']); players.append({'player':r['player'],'team':r['team'],'player_id':pid,'cached':pid in b})
                        self.send_json({'position':p,'scoring':s,'players':players,'cached_count':sum(x['cached'] for x in players),'total_count':len(players)})
                    else:
                        result=core.compare(p,(q.get('a') or [''])[0],(q.get('b') or [''])[0]); result['scoring']=s; self.send_json(result)
            except Exception as e: self.send_json({'error':str(e)},status=400)
            return
        super().do_GET()

def main():
    print(f'Loading Fantasy Decision Lab v{APP_VERSION}…'); initialize(); print(f'Fantasy Decision Lab: http://{core.HOST}:{core.PORT}')
    server=ThreadingHTTPServer((core.HOST,core.PORT),Handler); threading.Timer(.8,lambda:webbrowser.open(f'http://{core.HOST}:{core.PORT}')).start()
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nStopped.')
    finally: server.server_close()

if __name__=='__main__': main()
