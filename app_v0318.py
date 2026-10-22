#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.18 — suffix-safe Vegas player matching."""
from __future__ import annotations

import re

import app_v0317 as prev

APP_VERSION = "0.3.18"
ns = prev.ns
ns["APP_VERSION"] = APP_VERSION

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _canonical_vegas_name(value: str) -> str:
    """Strip generational suffixes for Vegas matching only."""
    text = str(value or "")
    text = re.sub(r"\s*[-–—]\s*.*$", "", text)
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", text).lower()
    parts = [p for p in re.sub(r"\s+", " ", text).strip().split(" ") if p]
    while parts and parts[-1] in _SUFFIXES:
        parts.pop()
    return " ".join(parts)


# The current app chain exposes Vegas comparison through the shared namespace.
# Canonicalize only the names sent to Vegas; FantasyPros continues receiving the
# original display names through its independent comparison path.
_orig_vegas_compare = ns["vegas_compare"]


def vegas_compare_v318(position: str, scoring: str, a_name: str, b_name: str, force=False):
    return _orig_vegas_compare(
        position,
        scoring,
        _canonical_vegas_name(a_name),
        _canonical_vegas_name(b_name),
        force=force,
    )


ns["vegas_compare"] = vegas_compare_v318

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
