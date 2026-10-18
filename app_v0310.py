#!/usr/bin/env python3
"""Fantasy Decision Lab v0.3.10 — hotfix v0.3.9 import-chain references."""
from __future__ import annotations

from pathlib import Path

SOURCE = Path(__file__).with_name("app_v039.py")
code = SOURCE.read_text(encoding="utf-8")
code = code.replace(
    "base.base.base.compare_base.core",
    "base.base.base.base.compare_base.core",
)
code = code.replace('APP_VERSION = "0.3.9"', 'APP_VERSION = "0.3.10"')
code = code.replace('"v0.3.9 ·"', '"v0.3.10 ·"')

ns = {
    "__name__": "app_v039_hotfixed",
    "__file__": str(SOURCE),
    "__package__": None,
}
exec(compile(code, str(SOURCE), "exec"), ns)

if __name__ == "__main__":
    ns["main"]()
