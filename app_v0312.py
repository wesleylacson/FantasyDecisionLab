#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.12 — Vegas UI fixes + explicit weekly FantasyPros requests."""
from __future__ import annotations

import json
import os
import re

import requests

import app_v0310 as hot

APP_VERSION = "0.3.12"
ns = hot.ns
ns["APP_VERSION"] = APP_VERSION

# --- FantasyPros: explicitly request weekly rankings -----------------------
# Current FantasyPros docs expose `type=weekly`; relying on week alone can
# fall back to draft semantics. Keep the existing transactional cache behavior
# while making the ranking type explicit.
fp038 = ns["base"]
fp035 = fp038.base.base.base
fp032 = fp035.compare_base
core = fp032.core


def weekly_fetch_group(position, scoring, expert_ids, force=False):
    path = core.group_path(position, scoring, expert_ids)
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))

    if force and fp032.REFRESH_STATE["outage"] and path.exists():
        fp032.REFRESH_STATE["used_stale"] = True
        return json.loads(path.read_text(encoding="utf-8"))

    params = {
        "position": position,
        "scoring": "STD" if position == "QB" else scoring,
        "week": core.WEEK,
        "type": "weekly",
        "filters": ":".join(expert_ids),
        "experts": "show",
    }
    try:
        data = core.api_get(core.CONSENSUS_URL, params)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return data
    except Exception as exc:
        if force and path.exists():
            fp032.REFRESH_STATE["outage"] = str(exc)
            fp032.REFRESH_STATE["used_stale"] = True
            return json.loads(path.read_text(encoding="utf-8"))
        raise


core.fetch_group = weekly_fetch_group

# Preserve both live and cache failures in the fallback diagnostic instead of
# reporting only the cache miss, which previously made a request bug look like
# a generic FantasyPros outage.
def diagnostic_resilient_compare(position: str, scoring: str, a_name: str, b_name: str):
    live_compare = fp035.compare_base.core.compare
    legacy_compare = fp035.legacy_cached_compare
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
            detail = f"Live FantasyPros: {live_exc} | Local cache: {cache_exc}"
            return fp038.outage_payload(position, scoring, a_name, b_name, detail)


fp038.resilient_compare = diagnostic_resilient_compare

# --- Vegas: fix source freshness, display names, and normal Compare click ---
orig_vegas_compare = ns["vegas_compare"]
orig_start_sit_html = ns["start_sit_html"]


def _clean_source_date(source_url: str, current):
    if current and re.fullmatch(r"\d{1,2}/\d{1,2}\s+[A-Za-z]+", str(current).strip()):
        return str(current).strip()
    try:
        r = requests.get(source_url, headers=ns["UA"], timeout=15)
        r.raise_for_status()
        # Deliberately strict so meta-description copy like "updated throughout
        # the week" cannot be mistaken for the page's visible refresh stamp.
        m = re.search(r"Updated\s*:\s*(\d{1,2}/\d{1,2}\s+[A-Za-z]+)", r.text, flags=re.I)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def vegas_compare_fixed(position: str, scoring: str, a_name: str, b_name: str, force=False):
    result = orig_vegas_compare(position, scoring, a_name, b_name, force=force)
    # pandas.read_html flattens hidden short/full-name/matchup elements into a
    # single cell on First Down. The selected app names are canonical and clean.
    result["player_a"]["player"] = a_name
    result["player_b"]["player"] = b_name
    if result.get("winner") == result["player_a"].get("player"):
        result["winner"] = a_name
    elif result.get("winner") == result["player_b"].get("player"):
        result["winner"] = b_name
    else:
        # The original winner string can be the flattened First Down cell.
        result["winner"] = a_name if result["player_a"]["fp"] >= result["player_b"]["fp"] else b_name
    result["source_updated"] = _clean_source_date(result.get("source_url") or ns["_source_url"](position), result.get("source_updated"))
    return result


ns["vegas_compare"] = vegas_compare_fixed


def start_sit_html_fixed():
    h = orig_start_sit_html()
    # The original page registered the Compare button before v0.3.9 replaced
    # the `compare` function variable, so normal clicks still invoked the old
    # FantasyPros-only callback. Add an independent Vegas listener.
    anchor = "$('refreshSources').addEventListener('click',refreshSources);"
    replacement = anchor + "$('go').addEventListener('click',()=>loadVegas(false));"
    if replacement not in h:
        h = h.replace(anchor, replacement)
    return h


ns["start_sit_html"] = start_sit_html_fixed

# Keep root badge current without disturbing inherited routing.
OldHandler = ns["Handler"]


class Handler(OldHandler):
    def do_GET(self):
        if self.path == "/":
            home = fp035.compare_base.core.ui.HOME_HTML.replace("v0.2 ·", "v0.3.12 ·")
            self.send_html(home)
            return
        return super().do_GET()


ns["Handler"] = Handler

if __name__ == "__main__":
    ns["main"]()
