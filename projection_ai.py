from __future__ import annotations

import json
import os
from typing import Any

import requests

from projection_knowledge import relevant_knowledge

API_URL = "https://api.openai.com/v1/responses"
MODEL = os.environ.get("FANTASY_PROJECTION_MODEL", "gpt-5.5")


def api_key() -> str:
    key = str(os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OpenAI API key is not configured. Run Configure OpenAI API Key.command once.")
    return key


def is_configured() -> bool:
    return bool(str(os.environ.get("OPENAI_API_KEY") or "").strip())


def _schema() -> dict:
    stats = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "carries": {"type": "number"},
            "rush_yards": {"type": "number"},
            "rush_tds": {"type": "number"},
            "rush_first_downs": {"type": "number"},
            "targets": {"type": "number"},
            "receptions": {"type": "number"},
            "rec_yards": {"type": "number"},
            "rec_tds": {"type": "number"},
            "rec_first_downs": {"type": "number"},
            "pass_yards": {"type": "number"},
            "pass_tds": {"type": "number"},
            "interceptions": {"type": "number"},
            "qb_rush_yards": {"type": "number"},
            "qb_rush_tds": {"type": "number"}
        },
        "required": ["carries", "rush_yards", "rush_tds", "rush_first_downs", "targets", "receptions", "rec_yards", "rec_tds", "rec_first_downs", "pass_yards", "pass_tds", "interceptions", "qb_rush_yards", "qb_rush_tds"]
    }
    pillar = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"headline": {"type": "string"}, "deep_dive": {"type": "string"}},
        "required": ["headline", "deep_dive"]
    }
    evidence = {
        "type": "object",
        "additionalProperties": False,
        "properties": {k: {"type": "string", "enum": ["missing", "partial", "available"]} for k in [
            "role_usage", "vegas_environment", "matchup_data", "injury_context", "market_projection", "coverage_scheme", "expert_commentary"
        ]},
        "required": ["role_usage", "vegas_environment", "matchup_data", "injury_context", "market_projection", "coverage_scheme", "expert_commentary"]
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "stats": stats,
            "floor_fp": {"type": "number"},
            "ceiling_fp": {"type": "number"},
            "pillars": {
                "type": "object",
                "additionalProperties": False,
                "properties": {k: pillar for k in ["role_opportunity", "game_environment", "matchup_scheme", "market_expert"]},
                "required": ["role_opportunity", "game_environment", "matchup_scheme", "market_expert"]
            },
            "evidence": evidence,
            "projection_summary": {"type": "string"},
            "app_disagreement": {"type": "string"}
        },
        "required": ["stats", "floor_fp", "ceiling_fp", "pillars", "evidence", "projection_summary", "app_disagreement"]
    }


def _prompt(payload: dict, research: dict, knowledge: list[dict]) -> str:
    scoring = payload.get("scoring_profile")
    app_fp = payload.get("app_projected_fp")
    meta = research.get("meta") or {}
    source_summaries = research.get("sources") or {}
    user_notes = {
        key: str(((payload.get("pillars") or {}).get(key) or {}).get("user_note") or "")
        for key in ["role_opportunity", "game_environment", "matchup_scheme", "market_expert"]
    }
    context = {
        "player": payload.get("player"),
        "position": meta.get("position") or payload.get("position"),
        "team": meta.get("team") or payload.get("team"),
        "opponent": meta.get("opponent") or payload.get("opponent"),
        "week": payload.get("week") or meta.get("week"),
        "scoring_profile": scoring,
        "app_projection_fp": app_fp,
        "structured_feed_evidence": source_summaries,
        "user_context": user_notes,
        "persistent_learnings": knowledge,
    }
    return f"""You are the research and projection-assumption engine for a fantasy football projection system.

Produce a defensible component-stat projection for the player below. Use live web search for current injuries, role changes, matchup/scheme, coverage/front tendencies, game environment, and relevant expert/market context. Prefer primary reporting and strong analytical sources. Monday-specific expert columns may not exist yet; do not penalize the rest of the research for that.

Core methodology:
- Regress short recent samples toward season-long and stable-role baselines unless current evidence supports a durable role change.
- Separate volume, efficiency, touchdown expectation, and first-down expectation.
- Treat the app projection as a required benchmark and useful prior, not the answer. If your projection differs materially, explain the component assumptions causing the gap.
- Avoid allowing one long TD, one extreme game, or a short scoring streak to become the new baseline.
- For RBs: explicitly consider carry competition, passing-down role, goal-line role, OL/run environment, box/front tendencies, game script, and injuries to teammates.
- For WR/TEs: explicitly consider target/route role, alignment, man/zone and shell tendencies, likely primary coverage, pressure/QB interaction, teammate availability, and comparable prior environments.
- Weather should change component assumptions only when it is meaningfully relevant; never add a separate blunt fantasy-point adjustment.
- Use zero for position-irrelevant stat fields.
- First downs may be estimated when direct projection data is unavailable, but keep them consistent with the projected volume/yards.
- The final fantasy score will be calculated by application code, so make the component stats internally coherent.

Scoring reminder: pigskin is 1 PPR + 1 point per rushing/receiving first down; funnel is 0 PPR + 0.5 PPFD; fami is 1 PPR + 0 PPFD. QB scoring is 0.04/pass yard, 4/pass TD, -2/INT, 0.1/rush yard, 6/rush TD.

INPUT CONTEXT:
{json.dumps(context, indent=2, default=str)}

Return concise pillar headlines, useful but compact deep dives, evidence coverage statuses, a projection summary, and an explicit explanation of the difference versus the app projection. Do not simply reproduce the app projection."""


def _extract_text(response: dict) -> str:
    for item in response.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]
    raise RuntimeError("OpenAI response contained no structured output text.")


def research_projection(payload: dict, research: dict) -> dict[str, Any]:
    meta = research.get("meta") or {}
    knowledge = relevant_knowledge(
        player=str(payload.get("player") or ""),
        team=str(meta.get("team") or payload.get("team") or ""),
        opponent=str(meta.get("opponent") or payload.get("opponent") or ""),
    )
    body = {
        "model": MODEL,
        "reasoning": {"effort": "medium"},
        "tools": [{"type": "web_search", "search_context_size": "medium"}],
        "include": ["web_search_call.action.sources"],
        "input": _prompt(payload, research, knowledge),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "fantasy_projection",
                "strict": True,
                "schema": _schema(),
            }
        },
    }
    r = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
        json=body,
        timeout=150,
    )
    if not r.ok:
        detail = r.text[:1200]
        raise RuntimeError(f"OpenAI research request failed ({r.status_code}): {detail}")
    raw = r.json()
    result = json.loads(_extract_text(raw))
    web_calls = [x for x in (raw.get("output") or []) if x.get("type") == "web_search_call"]
    sources = []
    for call in web_calls:
        action = call.get("action") or {}
        for src in action.get("sources") or []:
            if isinstance(src, dict):
                sources.append({"title": src.get("title"), "url": src.get("url")})
    result["ai_meta"] = {
        "model": raw.get("model") or MODEL,
        "response_id": raw.get("id"),
        "usage": raw.get("usage") or {},
        "web_search_calls": len(web_calls),
        "sources": sources,
        "knowledge_items": len(knowledge),
    }
    return result
