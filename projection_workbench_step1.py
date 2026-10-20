from __future__ import annotations

import json
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import projection_workbench as base
from projection_metadata import lookup_player, player_directory, projection_week

base.APP_VERSION = "0.1.2-projection-autofill"


def enhance_html(html: str) -> str:
    html = html.replace(
        '<input id="player" placeholder="Rhamondre Stevenson">',
        '<input id="player" list="playerOptions" autocomplete="off" placeholder="Start typing a player…"><datalist id="playerOptions"></datalist><div id="playerLookupStatus" class="muted" style="font-size:11px;margin-top:6px">Loading player directory…</div>',
    )
    html = html.replace('Team <span class="muted">· autofill later</span>', 'Team <span class="muted">· autofill</span>')
    html = html.replace('Opponent <span class="muted">· autofill later</span>', 'Opponent <span class="muted">· autofill</span>')
    html = html.replace('Week <span class="muted">· autofill later</span>', 'Week <span class="muted">· autofill</span>')
    html = html.replace('Position <span class="muted">· autofill later</span>', 'Position <span class="muted">· autofill</span>')

    injected = r'''
let playerDirectory=[];
let playerByName=new Map();
function normPlayerName(v){return String(v||'').trim().toLowerCase().replace(/\s+/g,' ')}
async function loadPlayerDirectory(){
  const status=$('playerLookupStatus');
  try{
    const j=await api('/api/player-directory');
    playerDirectory=j.players||[];
    playerByName=new Map(playerDirectory.map(p=>[normPlayerName(p.player),p]));
    const dl=$('playerOptions');
    dl.innerHTML='';
    playerDirectory.forEach(p=>{const o=document.createElement('option');o.value=p.player;o.label=`${p.position} · ${p.team}`;dl.appendChild(o)});
    status.textContent=`${playerDirectory.length} active QB/RB/WR/TE players available`;
  }catch(e){
    status.textContent='Player lookup unavailable — you can still enter metadata manually.';
  }
}
async function resolveSelectedPlayer(){
  const raw=$('player').value.trim();
  if(!raw)return;
  const local=playerByName.get(normPlayerName(raw));
  if(!local)return;
  const status=$('playerLookupStatus');
  status.textContent='Resolving matchup…';
  try{
    const j=await api('/api/player-meta?name='+encodeURIComponent(raw));
    $('player').value=j.player||raw;
    $('team').value=j.team||'';
    $('position').value=j.position||$('position').value;
    $('week').value=j.week||'';
    $('opponent').value=j.opponent||'';
    updatePosition();
    status.textContent=j.opponent
      ? `${j.position} · ${j.team} vs ${j.opponent} · Week ${j.week}`
      : `${j.position} · ${j.team} · Week ${j.week}; opponent schedule unavailable`;
  }catch(e){
    $('team').value=local.team||'';
    $('position').value=local.position||$('position').value;
    updatePosition();
    status.textContent=`${local.position} · ${local.team}; schedule lookup unavailable`;
  }
}
$('player').addEventListener('change',resolveSelectedPlayer);
$('player').addEventListener('blur',resolveSelectedPlayer);
'''
    html = html.replace('buildEvidence();document.querySelectorAll', injected + '\nbuildEvidence();loadPlayerDirectory();document.querySelectorAll')
    return html


base.HTML = enhance_html(base.HTML)


class Handler(base.Handler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/player-directory":
            try:
                players = player_directory()
                self.send_json({
                    "players": players,
                    "count": len(players),
                    "projection_week": projection_week(),
                    "source": "Sleeper player directory",
                })
            except Exception as e:
                self.send_json({"error": str(e)}, status=503)
            return
        if parsed.path == "/api/player-meta":
            qs = parse_qs(parsed.query)
            name = (qs.get("name") or [""])[0]
            try:
                self.send_json(lookup_player(name))
            except Exception as e:
                self.send_json({"error": str(e)}, status=400)
            return
        super().do_GET()


def main():
    base.DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Projection Workbench {base.APP_VERSION}: http://{base.HOST}:{base.PORT}")
    print(f"Local projection store: {base.DATA_FILE}")
    print("Player metadata: Sleeper directory + independent schedule lookup")
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
