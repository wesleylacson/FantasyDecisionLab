#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.18 — suffix-safe Vegas player matching."""
from __future__ import annotations

import re

import app_v0317 as prev
import app_v039 as vegas

APP_VERSION = "0.3.18"
ns = prev.ns
ns["APP_VERSION"] = APP_VERSION

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _canonical_name(value: str) -> str:
    """Normalize provider display names without making matching generally fuzzier."""
    text = str(value or "")
    text = re.sub(r"\s*[-–—]\s*.*$", "", text)
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", text).lower()
    parts = [p for p in re.sub(r"\s+", " ", text).strip().split(" ") if p]
    while parts and parts[-1] in _SUFFIXES:
        parts.pop()
    return " ".join(parts)


def _resolve_vegas_v318(name: str, rows: list[dict]) -> dict:
    """Resolve Vegas names after stripping Jr/Sr/II/III/IV/V on both sides.

    Recompute row names from the provider's player field so old cached snapshots
    created before v0.3.18 still benefit from the fix immediately.
    """
    n = _canonical_name(name)
    prepared = [(r, _canonical_name(r.get("player") or r.get("norm") or "")) for r in rows]

    exact = [r for r, rn in prepared if rn == n]
    if len(exact) == 1:
        return exact[0]

    contains = [r for r, rn in prepared if n and (n in rn or rn in n)]
    if len(contains) == 1:
        return contains[0]

    parts = n.split()
    if parts:
        last = parts[-1]
        initial = parts[0][0] if parts[0] else ""
        cand = []
        for r, rn in prepared:
            rp = rn.split()
            if rp and rp[-1] == last and (not initial or rp[0].startswith(initial)):
                cand.append(r)
        if len(cand) == 1:
            return cand[0]

    raise ValueError(f"Vegas data could not uniquely resolve {name}.")


# Patch the Vegas module used by the inherited comparison handler. Keep the
# rest of the matching behavior unchanged; only generational suffixes are canonicalized.
vegas._norm = _canonical_name
vegas._resolve_vegas = _resolve_vegas_v318

OldHandler = ns["Handler"]


class Handler(OldHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_html(prev.home_html_v317().replace("v0.3.17", "v0.3.18"))
            return
        return super().do_GET()


ns["Handler"] = Handler

if __name__ == "__main__":
    ns["main"]()
