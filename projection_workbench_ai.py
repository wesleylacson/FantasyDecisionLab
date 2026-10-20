from __future__ import annotations

import threading
import webbrowser
from http.server import ThreadingHTTPServer

import projection_workbench_step1 as prior
from projection_ai import is_configured, research_projection

base = prior.base
base.APP_VERSION = "0.4.0-ai-research"


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
        "async function saveRevision(){if(!$('player').value.trim()){ $('status').textContent='Player is required.';return }",
        "async function saveRevision(){if(!$('player').value.trim()){ $('status').textContent='Player is required.';return }if(!$('appFp').value.trim()){ $('status').textContent='App projection is required.';$('appFp').focus();return }",
    )
    html = html.replace(
        'Generate a revision to run the evidence pass and build a stat line.',
        'Generate runs the full AI + web research projection when your API key is configured; otherwise the local fallback engine is used.',
    )
    return html


base.HTML = enhance_html(base.HTML)


def _user_notes(payload: dict) -> dict:
    pillars = payload.get("pillars") if isinstance(payload.get("pillars"), dict) else {}
    return {
        key: str((pillars.get(key) or {}).get("user_note") or "")
        for key in base.PILLARS
    }


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
        stats = {k: stats.get(k, 0) for k in [
            "carries", "rush_yards", "rush_tds", "rush_first_downs", "targets", "receptions", "rec_yards", "rec_tds", "rec_first_downs"
        ]}
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
            "deep_dive": str(src.get("deep_dive") or ""),
            "user_note": notes.get(key, ""),
        }
    market = pillars.get("market_expert") or {}
    disagreement = str(ai.get("app_disagreement") or "").strip()
    if disagreement:
        market["deep_dive"] = (market.get("deep_dive") or "") + " App comparison: " + disagreement
    pillars["market_expert"] = market
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
    return enriched


def enrich_projection_payload(payload: dict) -> dict:
    if payload.get("app_projected_fp") in (None, ""):
        raise ValueError("App projection is required before generating a projection.")
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


class Handler(prior.Handler):
    def do_POST(self):
        if self.path == "/api/projection":
            try:
                payload = enrich_projection_payload(self.read_json())
                with base.LOCK:
                    result = base.save_projection(payload)
                result["ai_mode"] = payload.get("ai_mode")
                if payload.get("ai_meta"):
                    result["ai_meta"] = payload["ai_meta"]
                if payload.get("projection_summary"):
                    result["projection_summary"] = payload["projection_summary"]
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, status=400)
            return
        super().do_POST()


def main():
    base.DATA_DIR.mkdir(parents=True, exist_ok=True)
    mode = "AI + live web research" if is_configured() else "local fallback (configure API key for AI research)"
    print(f"Projection Workbench {base.APP_VERSION}: http://{base.HOST}:{base.PORT}")
    print(f"Projection mode: {mode}")
    print(f"Local projection store: {base.DATA_FILE}")
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
