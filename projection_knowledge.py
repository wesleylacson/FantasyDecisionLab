from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path.home() / ".fantasy_decision_lab"
LOCAL_KNOWLEDGE = DATA_DIR / "projection_knowledge.json"
SEED_KNOWLEDGE = Path(__file__).with_name("projection_knowledge_seed.json")


def _load(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("learnings") if isinstance(data, dict) else []
        return [x for x in (rows or []) if isinstance(x, dict) and x.get("active", True)]
    except Exception:
        return []


def relevant_knowledge(player: str = "", team: str = "", opponent: str = "", limit: int = 40) -> list[dict]:
    rows = _load(SEED_KNOWLEDGE) + _load(LOCAL_KNOWLEDGE)
    player_l = str(player or "").lower()
    team_l = str(team or "").lower()
    opp_l = str(opponent or "").lower()
    scored = []
    for row in rows:
        scope = str(row.get("scope") or "global").lower()
        subject = str(row.get("subject") or "").lower()
        score = 1 if scope == "global" else 0
        if player_l and player_l in subject:
            score += 5
        if team_l and team_l in subject:
            score += 3
        if opp_l and opp_l in subject:
            score += 3
        if score:
            scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[:limit]]


def add_local_learning(learning: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing = {"schema_version": 1, "learnings": _load(LOCAL_KNOWLEDGE)}
    row = dict(learning)
    row.setdefault("active", True)
    existing["learnings"].append(row)
    tmp = LOCAL_KNOWLEDGE.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    tmp.replace(LOCAL_KNOWLEDGE)
