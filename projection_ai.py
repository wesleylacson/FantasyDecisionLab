from __future__ import annotations

import json
import os
from typing import Any

import requests

from projection_knowledge import relevant_knowledge

API_URL = "https://api.openai.com/v1/responses"
# Focused/high-volume work is the default here. Override locally with
# FANTASY_PROJECTION_MODEL if a future experiment needs a stronger model.
MODEL = os.environ.get("FANTASY_PROJECTION_MODEL", "gpt-6-luna")
DEEP_DIVE_MODEL = os.environ.get("FANTASY_DEEP_DIVE_MODEL", MODEL)


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
            "qb_rush_tds": {"type": "number"},
        },
        "required": [
            "carries", "rush_yards", "rush_tds", "rush_first_downs", "targets",
            "receptions", "rec_yards", "rec_tds", "rec_first_downs", "pass_yards",
            "pass_tds", "interceptions", "qb_rush_yards", "qb_rush_tds",
        ],
    }
    # Initial projection only pays for the concise headline. Deep-dive prose is generated
    # on demand if the user opens that pillar.
    pillar = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"headline": {"type": "string"}},
        "required": ["headline"],
    }
    evidence = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            k: {"type": "string", "enum": ["missing", "partial", "available"]}
            for k in [
                "role_usage", "vegas_environment", "matchup_data", "injury_context",
                "market_projection", "coverage_scheme", "expert_commentary",
            ]
        },
        "required": [
            "role_usage", "vegas_environment", "matchup_data", "injury_context",
            "market_projection", "coverage_scheme", "expert_commentary",
        ],
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
                "properties": {
                    k: pillar
                    for k in ["role_opportunity", "game_environment", "matchup_scheme", "market_expert"]
                },
                "required": ["role_opportunity", "game_environment", "matchup_scheme", "market_expert"],
            },
            "evidence": evidence,
            "projection_summary": {"type": "string"},
            "app_disagreement": {"type": "string"},
        },
        "required": [
            "stats", "floor_fp", "ceiling_fp", "pillars", "evidence",
            "projection_summary", "app_disagreement",
        ],
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

Produce a defensible component-stat projection for the player below. Use targeted live web search only where current information materially affects the projection: injuries/role changes, matchup/scheme, coverage/front tendencies, game environment, and relevant market context. Prefer primary reporting and strong analytical sources. Avoid redundant searches for facts already present in the structured feeds or persistent learnings.

Core methodology:
- Regress short recent samples toward season-long and stable-role baselines unless current evidence supports a durable role change.
- Separate volume, efficiency, touchdown expectation, and first-down expectation.
- Treat the app projection as a required benchmark and useful prior, not the answer. If your projection differs materially, explain the component assumptions causing the gap.
- Avoid allowing one long TD, one extreme game, or a short scoring streak to become the new baseline.
- For RBs: consider carry competition, passing-down role, goal-line role, OL/run environment, box/front tendencies, game script, and teammate injuries.
- For WR/TEs: consider target/route role, alignment, man/zone and shell tendencies, likely primary coverage, pressure/QB interaction, teammate availability, and comparable prior environments.
- Weather should change component assumptions only when materially relevant; never add a separate blunt fantasy-point adjustment.
- Use zero for position-irrelevant stat fields.
- First downs may be estimated when direct projection data is unavailable, but keep them consistent with projected volume/yards.
- The final fantasy score is calculated by application code, so make component stats internally coherent.

Scoring reminder: pigskin is 1 PPR + 1 point per rushing/receiving first down; funnel is 0 PPR + 0.5 PPFD; fami is 1 PPR + 0 PPFD. QB scoring is 0.04/pass yard, 4/pass TD, -2/INT, 0.1/rush yard, 6/rush TD.

INPUT CONTEXT:
{json.dumps(context, indent=2, default=str)}

Return very concise pillar headlines (1-2 sentences each), evidence coverage statuses, a short projection summary, and an explicit compact explanation of the difference versus the app projection. DO NOT generate deep-dive prose; that is a separate on-demand action. Do not simply reproduce the app projection."""


def _extract_text(response: dict) -> str:
    for item in response.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]
    raise RuntimeError("OpenAI response contained no structured output text.")


def _sources_from_response(raw: dict) -> tuple[list[dict], int]:
    web_calls = [x for x in (raw.get("output") or []) if x.get("type") == "web_search_call"]
    sources: list[dict] = []
    for call in web_calls:
        action = call.get("action") or {}
        for src in action.get("sources") or []:
            if isinstance(src, dict):
                sources.append({"title": src.get("title"), "url": src.get("url")})
    return sources, len(web_calls)


def research_projection(payload: dict, research: dict) -> dict[str, Any]:
    meta = research.get("meta") or {}
    knowledge = relevant_knowledge(
        player=str(payload.get("player") or ""),
        team=str(meta.get("team") or payload.get("team") or ""),
        opponent=str(meta.get("opponent") or payload.get("opponent") or ""),
    )
    body = {
        "model": MODEL,
        "reasoning": {"effort": "low"},
        "tools": [{"type": "web_search", "search_context_size": "low"}],
        "include": ["web_search_call.action.sources"],
        "input": _prompt(payload, research, knowledge),
        "max_output_tokens": 2600,
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
        raise RuntimeError(f"OpenAI research request failed ({r.status_code}): {r.text[:1200]}")
    raw = r.json()
    result = json.loads(_extract_text(raw))
    sources, web_call_count = _sources_from_response(raw)
    result["ai_meta"] = {
        "model": raw.get("model") or MODEL,
        "response_id": raw.get("id"),
        "usage": raw.get("usage") or {},
        "web_search_calls": web_call_count,
        "sources": sources,
        "knowledge_items": len(knowledge),
    }
    return result


def generate_deep_dive(record: dict, pillar_key: str) -> dict[str, Any]:
    labels = {
        "role_opportunity": "Role / Opportunity",
        "game_environment": "Game Environment",
        "matchup_scheme": "Matchup / Scheme",
        "market_expert": "Market / Expert Context",
    }
    if pillar_key not in labels:
        raise ValueError("Unknown projection pillar.")
    pillar = ((record.get("pillars") or {}).get(pillar_key) or {})
    prompt = f"""Expand one fantasy-football projection pillar into a useful analyst deep dive.
Do not perform a new web search. Use only the saved projection result, its source list, and the user's saved context below. Be concise: roughly 120-220 words. Explain the assumptions that matter to the component-stat projection and flag uncertainty. Do not restate the entire projection.

PILLAR: {labels[pillar_key]}
PLAYER: {record.get('player')} ({record.get('position')}, {record.get('team')} vs {record.get('opponent')})
WEEK: {record.get('week')}
APP FP: {record.get('app_projected_fp')}
OUR FP: {record.get('our_projected_fp')}
PILLAR HEADLINE: {pillar.get('headline') or ''}
USER CONTEXT: {pillar.get('user_note') or ''}
PROJECTED STATS: {json.dumps(record.get('stats') or {}, default=str)}
PROJECTION SUMMARY: {record.get('projection_summary') or ''}
SOURCES FROM ORIGINAL RUN: {json.dumps(((record.get('ai_meta') or {}).get('sources') or [])[:12], default=str)}

Return only the deep-dive prose."""
    body = {
        "model": DEEP_DIVE_MODEL,
        "reasoning": {"effort": "low"},
        "input": prompt,
        "max_output_tokens": 700,
    }
    r = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
        json=body,
        timeout=90,
    )
    if not r.ok:
        raise RuntimeError(f"Deep-dive request failed ({r.status_code}): {r.text[:800]}")
    raw = r.json()
    return {
        "text": _extract_text(raw).strip(),
        "meta": {
            "model": raw.get("model") or DEEP_DIVE_MODEL,
            "response_id": raw.get("id"),
            "usage": raw.get("usage") or {},
            "web_search_calls": 0,
        },
    }
