#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.13 — live compare-players fallback + robust First Down freshness."""
from __future__ import annotations

import re

import requests
from lxml import html as lxml_html

import app_v0312 as prev

APP_VERSION = "0.3.13"
ns = prev.ns
ns["APP_VERSION"] = APP_VERSION

# Reach the existing v0.3.8 / v0.3.5 stack.
fp038 = ns["base"]
fp035 = fp038.base.base.base
legacy = fp035.legacy

# ---------------------------------------------------------------------------
# FantasyPros: grouped consensus -> live compare-players -> cached ballots -> deeplink
# ---------------------------------------------------------------------------
def live_compare_players_fallback(position: str, scoring: str, a_name: str, b_name: str):
    # Prepare the legacy engine for the requested scoring and make sure its
    # directory/accuracy state is loaded.
    fp035._prepare_legacy(position, scoring)
    st = legacy.STATE["positions"][position]
    a = legacy.resolve_player(a_name, st["directory"])
    b = legacy.resolve_player(b_name, st["directory"])
    aid, bid = str(a["player_id"]), str(b["player_id"])

    # This is the original live /nfl/compare-players path already used by the
    # app before the grouped consensus backend was introduced.
    legacy.fetch_pair_and_cache(position, aid, bid, force=True)
    st["ballots"] = legacy.collect_ballots(position)
    st["weights"] = {}
    legacy.ensure_weights(position)

    result = legacy.compare(position, a_name, b_name)
    result["scoring"] = "STD" if position == "QB" else scoring
    result["warning"] = "Grouped FantasyPros consensus endpoint failed; used live compare-players ballots instead."
    result["source_note"] = (
        result.get("source_note", "")
        + " Live grouped consensus was unavailable, so the matchup was refreshed from FantasyPros compare-players and evaluated with the normal local weighting model."
    )
    return result


def resilient_compare_v313(position: str, scoring: str, a_name: str, b_name: str):
    grouped = fp035.compare_base.core.compare
    try:
        return grouped(position, scoring, a_name, b_name)
    except Exception as grouped_exc:
        # Second live path: use FantasyPros' purpose-built head-to-head endpoint.
        try:
            return live_compare_players_fallback(position, scoring, a_name, b_name)
        except Exception as compare_exc:
            # Third tier: cached ballots only.
            try:
                return fp035.legacy_cached_compare(position, scoring, a_name, b_name)
            except Exception as cache_exc:
                detail = (
                    f"Grouped FantasyPros: {grouped_exc} | "
                    f"Live compare-players: {compare_exc} | "
                    f"Local cache: {cache_exc}"
                )
                return fp038.outage_payload(position, scoring, a_name, b_name, detail)


fp038.resilient_compare = resilient_compare_v313

# ---------------------------------------------------------------------------
# First Down: extract the visible freshness stamp from parsed page text.
# ---------------------------------------------------------------------------
orig_vegas_compare = ns["vegas_compare"]


def visible_first_down_stamp(url: str):
    try:
        r = requests.get(url, headers=ns["UA"], timeout=15)
        r.raise_for_status()
        doc = lxml_html.fromstring(r.content)
        text = " ".join(doc.text_content().split())
        m = re.search(r"Updated\s*:?\s*(\d{1,2}/\d{1,2}\s+[A-Za-z]+)", text, flags=re.I)
        return m.group(1) if m else None
    except Exception:
        return None


def vegas_compare_v313(position: str, scoring: str, a_name: str, b_name: str, force=False):
    result = orig_vegas_compare(position, scoring, a_name, b_name, force=force)
    stamp = visible_first_down_stamp(result.get("source_url") or ns["_source_url"](position))
    if stamp:
        result["source_updated"] = stamp
    return result


ns["vegas_compare"] = vegas_compare_v313

# Keep the app badge current.
OldHandler = ns["Handler"]


class Handler(OldHandler):
    def do_GET(self):
        if self.path == "/":
            home = fp035.compare_base.core.ui.HOME_HTML.replace("v0.2 ·", "v0.3.13 ·")
            self.send_html(home)
            return
        return super().do_GET()


ns["Handler"] = Handler

if __name__ == "__main__":
    ns["main"]()
