#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.14 — fast FantasyPros outage handling + First Down stamp diagnostics."""
from __future__ import annotations

import html as html_lib
import json
import os
import re

import requests

import app_v0313 as prev

APP_VERSION = "0.3.14"
ns = prev.ns
ns["APP_VERSION"] = APP_VERSION

fp038 = ns["base"]
fp035 = fp038.base.base.base
fp032 = fp035.compare_base
core = fp032.core
legacy = fp035.legacy

# ---------------------------------------------------------------------------
# FantasyPros: one quick live attempt per path, then mark FP down for session.
# Refresh Sources clears this flag and retries both live paths.
# ---------------------------------------------------------------------------
FP_SESSION = {"down": False, "detail": None}


def fetch_group_without_weekly_type(position, scoring, expert_ids, force=False):
    path = core.group_path(position, scoring, expert_ids)
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))
    params = {
        "position": position,
        "scoring": "STD" if position == "QB" else scoring,
        "week": core.WEEK,
        "filters": ":".join(expert_ids),
        "experts": "show",
    }
    # One attempt only. A 5x retry loop made every comparison stall during a
    # confirmed upstream 502 condition.
    data = core.api_get(core.CONSENSUS_URL, params, attempts=1)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return data


core.fetch_group = fetch_group_without_weekly_type


def _cached_or_outage(position, scoring, a_name, b_name, detail):
    try:
        return fp035.legacy_cached_compare(position, scoring, a_name, b_name)
    except Exception as cache_exc:
        return fp038.outage_payload(
            position, scoring, a_name, b_name,
            f"{detail} | Local cache: {cache_exc}"
        )


def resilient_compare_v314(position: str, scoring: str, a_name: str, b_name: str):
    if FP_SESSION["down"]:
        return _cached_or_outage(
            position, scoring, a_name, b_name,
            "FantasyPros live endpoints are marked unavailable for this app session after HTTP 502. Hit Refresh sources to retry. "
            + str(FP_SESSION.get("detail") or "")
        )

    grouped_exc = None
    try:
        return fp035.compare_base.core.compare(position, scoring, a_name, b_name)
    except Exception as exc:
        grouped_exc = exc

    compare_exc = None
    try:
        return prev.live_compare_players_fallback(position, scoring, a_name, b_name)
    except Exception as exc:
        compare_exc = exc

    detail = f"Grouped FantasyPros: {grouped_exc} | Live compare-players: {compare_exc}"
    if "HTTP 502" in detail:
        FP_SESSION["down"] = True
        FP_SESSION["detail"] = detail
    return _cached_or_outage(position, scoring, a_name, b_name, detail)


fp038.resilient_compare = resilient_compare_v314

# ---------------------------------------------------------------------------
# First Down: search both rendered text and raw/escaped payload for update date.
# If absent, return useful diagnostics instead of a bare "unavailable".
# ---------------------------------------------------------------------------
orig_vegas_compare = ns["vegas_compare"]
DAYS = r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
DATE_RE = re.compile(rf"(\d{{1,2}}/\d{{1,2}}\s+{DAYS})", re.I)


def first_down_stamp_and_diag(url: str):
    try:
        headers = dict(ns["UA"] or {})
        headers.setdefault("Accept-Language", "en-US,en;q=0.9")
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        raw = r.text
        variants = [raw, html_lib.unescape(raw)]
        escaped = html_lib.unescape(raw)
        for old, new in ((r"\u002F", "/"), (r"\/", "/"), (r"\u003A", ":"), (r"\u0020", " "), (r"\n", " ")):
            escaped = escaped.replace(old, new)
        variants.append(escaped)
        for text in variants:
            m = re.search(rf"Updated[^0-9]{{0,100}}(\d{{1,2}}/\d{{1,2}}\s+{DAYS})", text, re.I)
            if m:
                return m.group(1), None
        # Last resort: the visible page has only one date/day stamp in normal use.
        for text in variants:
            m = DATE_RE.search(text)
            if m:
                return m.group(1), None
        return None, f"HTTP {r.status_code}; {len(r.content):,} bytes; update date absent from raw response"
    except Exception as exc:
        return None, f"freshness request failed: {exc}"


def vegas_compare_v314(position: str, scoring: str, a_name: str, b_name: str, force=False):
    result = orig_vegas_compare(position, scoring, a_name, b_name, force=force)
    stamp, diag = first_down_stamp_and_diag(result.get("source_url") or ns["_source_url"](position))
    if stamp:
        result["source_updated"] = stamp
    elif not result.get("source_updated"):
        result["source_updated"] = "Unavailable"
        result["warning"] = " · ".join(x for x in [result.get("warning"), "First Down stamp diagnostic: " + diag] if x)
    return result


ns["vegas_compare"] = vegas_compare_v314

# Refresh Sources explicitly retries FantasyPros even after a session 502.
OldHandler = ns["Handler"]


class Handler(OldHandler):
    def do_POST(self):
        if self.path.split("?", 1)[0] == "/api/refresh":
            FP_SESSION["down"] = False
            FP_SESSION["detail"] = None
        return super().do_POST()

    def do_GET(self):
        if self.path == "/":
            home = fp035.compare_base.core.ui.HOME_HTML.replace("v0.2 ·", "v0.3.14 ·")
            self.send_html(home)
            return
        return super().do_GET()


ns["Handler"] = Handler

if __name__ == "__main__":
    ns["main"]()
