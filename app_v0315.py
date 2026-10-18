#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.15 — compact FantasyPros outage state."""
from __future__ import annotations

import re

import app_v0314 as prev

APP_VERSION = "0.3.15"
ns = prev.ns
ns["APP_VERSION"] = APP_VERSION

fp038 = ns["base"]
fp035 = fp038.base.base.base
orig_start_sit_html = ns["start_sit_html"]


def start_sit_html_v315():
    h = orig_start_sit_html()

    css = r'''
.fp-unavailable-card{padding:16px 18px;border:1px solid #365077;border-radius:16px;background:#0a1527;color:#dce7f7}
.fp-unavailable-title{font-size:13px;font-weight:900;text-transform:uppercase;letter-spacing:.08em;color:#ffd166;margin-bottom:6px}
.fp-unavailable-copy{font-size:12px;line-height:1.5;color:#9fb0c9}
.fp-unavailable-card .outage-link{margin-top:12px}
.fp-debug{margin-top:10px;font-size:11px;color:#8295b2}
.fp-debug summary{cursor:pointer;font-weight:800}
.fp-debug pre{white-space:pre-wrap;word-break:break-word;margin:8px 0 0;padding:10px;background:#07111f;border:1px solid #263b5b;border-radius:10px;color:#8fa3c2;max-height:180px;overflow:auto}
#error.fp-source-unavailable{display:block;background:transparent;border:0;padding:0;color:inherit}
'''
    h = h.replace('</style></head>', css + '</style></head>')

    pattern = re.compile(r"function showOutage\(j\)\{.*?\n\}\nfunction showErr\(s\)\{\$\('error'\)\.textContent=s;\$\('error'\)\.style\.display='block'\}", re.S)
    replacement = r'''function showOutage(j){
$('result').style.display='none';
const e=$('error');
const esc=s=>String(s||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
e.classList.add('fp-source-unavailable');
e.innerHTML='<div class="fp-unavailable-card"><div class="fp-unavailable-title">FantasyPros unavailable</div><div class="fp-unavailable-copy">FantasyPros is not returning live rankings right now. Vegas market data can still load and remains usable as the contextual tiebreaker.</div><a class="outage-link" target="_blank" rel="noopener noreferrer" href="'+j.fantasypros_url+'">Open this matchup directly on FantasyPros →</a>'+(j.detail?'<details class="fp-debug"><summary>Technical details</summary><pre>'+esc(j.detail)+'</pre></details>':'')+'</div>';
e.style.display='block';
}
function showErr(s){const e=$('error');e.classList.remove('fp-source-unavailable');e.textContent=s;e.style.display='block'}'''
    h, n = pattern.subn(replacement, h, count=1)
    if n != 1:
        raise RuntimeError("Could not patch FantasyPros outage renderer in v0.3.15")
    return h


ns["start_sit_html"] = start_sit_html_v315

OldHandler = ns["Handler"]


class Handler(OldHandler):
    def do_GET(self):
        if self.path == "/":
            home = fp035.compare_base.core.ui.HOME_HTML.replace("v0.2 ·", "v0.3.15 ·")
            self.send_html(home)
            return
        return super().do_GET()


ns["Handler"] = Handler

if __name__ == "__main__":
    ns["main"]()
