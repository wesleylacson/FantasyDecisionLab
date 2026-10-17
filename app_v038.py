#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.8 — clean FantasyPros deeplink outage fallback."""
from __future__ import annotations

import re
import threading
import unicodedata
import webbrowser
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import app_v037 as base

APP_VERSION = "0.3.8"
HOST, PORT = base.HOST, base.PORT
LOCK = threading.Lock()


def fantasypros_slug(name: str) -> str:
    """Convert a player display name to FantasyPros' start/sit URL slug style."""
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[’']", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def fantasypros_compare_url(a_name: str, b_name: str, scoring: str) -> str:
    a = fantasypros_slug(a_name)
    b = fantasypros_slug(b_name)
    scoring = "STD" if str(scoring).upper() == "STD" else "PPR"
    return f"https://www.fantasypros.com/nfl/start/{a}-{b}.php?scoring={scoring}"


def outage_payload(position: str, scoring: str, a_name: str, b_name: str, detail: str = "") -> dict:
    return {
        "redirect_only": True,
        "position": position,
        "scoring": "STD" if position == "QB" else scoring,
        "player_a": a_name,
        "player_b": b_name,
        "fantasypros_url": fantasypros_compare_url(a_name, b_name, scoring),
        "message": "FantasyPros data is temporarily unavailable for the full Decision Lab comparison.",
        "detail": detail,
    }


def resilient_compare(position: str, scoring: str, a_name: str, b_name: str):
    """Use the real model when possible; otherwise hand off to FantasyPros itself.

    Tier 1: live grouped FantasyPros rankings backend.
    Tier 2: exact local per-expert ballot cache from earlier successful API calls.
    Tier 3: no synthetic/degraded model — return a direct FantasyPros matchup URL.
    """
    live_compare = base.base.base.compare_base.core.compare
    legacy_compare = base.base.base.legacy_cached_compare

    try:
        return live_compare(position, scoring, a_name, b_name)
    except Exception as live_exc:
        msg = str(live_exc)
        transient = any(x in msg for x in (
            "temporarily unavailable", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "after retries"
        ))
        if not transient:
            raise

        try:
            return legacy_compare(position, scoring, a_name, b_name)
        except Exception as cache_exc:
            return outage_payload(position, scoring, a_name, b_name, str(cache_exc))


def start_sit_html():
    # Start from v0.3.5's normal UI: scoring switcher, resilient autocomplete,
    # and non-destructive refresh behavior, without v0.3.6's degraded dashboard.
    h = base.base.base.start_sit_html()

    css = '''
.outage-link{display:inline-block;margin-top:14px;padding:12px 16px;border-radius:12px;background:linear-gradient(90deg,var(--accent),var(--accent2));color:#06111f!important;text-decoration:none;font-weight:900}
.outage-detail{margin-top:12px;color:#9fb0c9;font-size:11px;line-height:1.45;opacity:.75}
'''
    h = h.replace('</style></head>', css + '</style></head>')

    # Normal Compare: intercept the redirect-only payload instead of rendering
    # it through the five-lens result template.
    h = h.replace(
        "const j=await r.json();if(!r.ok)throw new Error(j.error||'Comparison failed');render(j);",
        "const j=await r.json();if(!r.ok)throw new Error(j.error||'Comparison failed');if(j.redirect_only){showOutage(j);$('status').textContent='FantasyPros unavailable';return}render(j);"
    )

    # Same handoff after a manual matchup refresh if the outage is still active.
    h = h.replace(
        "const cj=await cr.json();if(!cr.ok)throw new Error(cj.error||'Comparison failed after refresh');render(cj);",
        "const cj=await cr.json();if(!cr.ok)throw new Error(cj.error||'Comparison failed after refresh');if(cj.redirect_only){showOutage(cj);$('status').textContent='FantasyPros unavailable';return}render(cj);"
    )

    # Add a dedicated outage renderer. Keep the raw detail small for debugging,
    # while the primary action is the direct FantasyPros matchup link.
    marker = "function showErr(s){$('error').textContent=s;$('error').style.display='block'}"
    replacement = """function showOutage(j){
$('result').style.display='none';
const e=$('error');
e.innerHTML='FantasyPros data is temporarily unavailable for the full Decision Lab comparison.<br><a class=\"outage-link\" target=\"_blank\" rel=\"noopener noreferrer\" href=\"'+j.fantasypros_url+'\">Open this matchup directly on FantasyPros →</a>'+(j.detail?'<div class=\"outage-detail\">'+j.detail.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')+'</div>':'');
e.style.display='block';
}
function showErr(s){$('error').textContent=s;$('error').style.display='block'}"""
    h = h.replace(marker, replacement)
    return h


class Handler(base.Handler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(base.base.base.compare_base.core.ui.HOME_HTML.replace("v0.2 ·", "v0.3.8 ·"))
            return
        if parsed.path == "/start-sit":
            self.send_html(start_sit_html())
            return
        if parsed.path == "/api/compare":
            q = parse_qs(parsed.query)
            position = ((q.get("position") or ["WR"])[0]).upper()
            scoring = base.base.base.compare_base.core.norm_scoring((q.get("scoring") or ["PPR"])[0])
            a_name = (q.get("a") or [""])[0]
            b_name = (q.get("b") or [""])[0]
            try:
                with LOCK:
                    result = resilient_compare(position, scoring, a_name, b_name)
                self.send_json(result)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        # Preserve autocomplete, safe refresh, JSON sanitization, etc.
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
