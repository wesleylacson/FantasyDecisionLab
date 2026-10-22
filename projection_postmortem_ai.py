from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import requests

API_URL = "https://api.openai.com/v1/responses"
MODEL = os.environ.get("FANTASY_POSTMORTEM_MODEL", "gpt-6-luna")
REASONING_EFFORT = os.environ.get("FANTASY_POSTMORTEM_REASONING", "medium")


def api_key() -> str:
    key = str(os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OpenAI API key is not configured.")
    return key


def _schema() -> dict:
    learning_impact = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "learning_id": {"type": "string"},
            "relationship": {"type": "string", "enum": ["support", "contradict", "context", "exclusion"]},
            "rationale": {"type": "string"},
        },
        "required": ["learning_id", "relationship", "rationale"],
    }
    diagnosis = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "projection_key": {"type": "string"},
            "source": {"type": "string"},
            "player": {"type": "string"},
            "week": {"type": "integer"},
            "primary_cause": {"type": "string"},
            "secondary_cause": {"type": "string"},
            "process_verdict": {
                "type": "string",
                "enum": ["process_hit", "process_miss", "mixed", "variance_or_exclusion"],
            },
            "summary": {"type": "string"},
            "observation_keys": {"type": "array", "items": {"type": "string"}},
            "existing_learning_impacts": {"type": "array", "items": learning_impact},
        },
        "required": [
            "projection_key", "source", "player", "week", "primary_cause", "secondary_cause",
            "process_verdict", "summary", "observation_keys", "existing_learning_impacts",
        ],
    }
    candidate = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "candidate_type": {"type": "string", "enum": ["new", "refine", "merge"]},
            "scope": {"type": "string"},
            "subject": {"type": "string"},
            "statement": {"type": "string"},
            "confidence": {"type": "string", "enum": ["Low", "Medium", "Medium-High", "High"]},
            "related_learning_ids": {"type": "array", "items": {"type": "string"}},
            "evidence_keys": {"type": "array", "items": {"type": "string"}},
            "support_count": {"type": "integer"},
            "contradict_count": {"type": "integer"},
            "diagnostic_summary": {"type": "string"},
            "rationale": {"type": "string"},
            "recommendation": {"type": "string"},
        },
        "required": [
            "candidate_type", "scope", "subject", "statement", "confidence",
            "related_learning_ids", "evidence_keys", "support_count", "contradict_count",
            "diagnostic_summary", "rationale", "recommendation",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "diagnoses": {"type": "array", "items": diagnosis},
            "candidates": {"type": "array", "items": candidate},
            "no_new_learning_summary": {"type": "string"},
            "weekly_summary": {"type": "string"},
        },
        "required": ["diagnoses", "candidates", "no_new_learning_summary", "weekly_summary"],
    }


def _extract_text(response: dict) -> str:
    for item in response.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]
    raise RuntimeError("OpenAI response contained no structured output text.")


def candidate_id(candidate: dict, week: int) -> str:
    payload = "|".join(
        [
            str(week),
            str(candidate.get("candidate_type") or ""),
            str(candidate.get("scope") or ""),
            str(candidate.get("subject") or ""),
            str(candidate.get("statement") or ""),
        ]
    ).lower()
    return "C" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def build_prompt(
    *,
    week: int,
    observations: list[dict],
    learning_registry: list[dict],
    evidence_map: list[dict],
    extra_context: dict | None = None,
) -> str:
    context = {
        "week": week,
        "completed_observations": observations,
        "learning_registry": learning_registry,
        "existing_evidence_map": evidence_map,
        "extra_context": extra_context or {},
    }
    return f"""You are the postmortem diagnostic and candidate-learning engine for a fantasy-football projection system.

Your job is to explain what the projection process got right or wrong and propose reusable lessons only when the evidence warrants one. You NEVER promote or mutate active model knowledge. A human reviews every candidate.

Core rules:
- Diagnose component chains, not just fantasy-point totals. Separate opportunity, conversion, production/efficiency, scoring variance, first downs, and total fantasy output.
- A total-FP hit can still hide a materially wrong component mix.
- A target/carry/attempt hit plus a yardage miss is primarily an efficiency/production issue unless evidence shows the recorded volume itself was misleading.
- Do not learn from isolated realized TDs. Learn from repeatable goal-line/red-zone opportunity only when supported.
- Do not learn from unforeseeable DNPs or in-game injuries. Mark those as variance_or_exclusion and use them only as context.
- Prefer support/contradict/context links to EXISTING lessons over inventing a new lesson.
- A candidate can refine or merge an existing lesson when evidence changes its boundary. Explicit contradictory evidence is valuable.
- Reward yourself for saying there is no new lesson. Most player-games should not create a permanent rule.
- Avoid hindsight laundering: do not claim a lesson was known before the game unless it appears in the supplied registry/evidence. A new candidate may be proposed after the game, but label it as new/refine/merge.
- Avoid player-specific rules when a more general position/process rule is justified, and avoid global rules when evidence is only player-specific.
- Require more than a single noisy result for a High-confidence new methodology rule. A single game can justify a candidate only when the mechanism is directly observed and repeatable (for example a confirmed role or personnel change), and even then keep confidence bounded.
- Treat Workbench and Chat as separate projection sources when both exist for the same player/week. Diagnose each independently before comparing them.
- Use live web search only when it materially resolves a causal question that the structured observations cannot answer, such as role, injury, personnel, coverage, or line-play context.

Return concise structured diagnoses and only genuinely useful candidate lessons. Every candidate must cite observation/evidence keys supplied in the input. Human review is mandatory.

INPUT:
{json.dumps(context, indent=2, default=str)}"""


def generate_learning_review(
    *,
    week: int,
    observations: list[dict],
    learning_registry: list[dict],
    evidence_map: list[dict],
    extra_context: dict | None = None,
) -> dict[str, Any]:
    completed = [row for row in observations if row.get("actual") not in (None, "")]
    if not completed:
        return {
            "diagnoses": [],
            "candidates": [],
            "no_new_learning_summary": "No completed observations were supplied.",
            "weekly_summary": "No postmortem run was needed.",
            "ai_meta": {"model": MODEL, "reasoning": REASONING_EFFORT, "skipped": True},
        }

    body = {
        "model": MODEL,
        "reasoning": {"effort": REASONING_EFFORT},
        "tools": [{"type": "web_search", "search_context_size": "medium"}],
        "include": ["web_search_call.action.sources"],
        "input": build_prompt(
            week=week,
            observations=completed,
            learning_registry=learning_registry,
            evidence_map=evidence_map,
            extra_context=extra_context,
        ),
        "max_output_tokens": 6000,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "fantasy_postmortem_learning_review",
                "strict": True,
                "schema": _schema(),
            }
        },
    }
    response = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
        json=body,
        timeout=180,
    )
    if not response.ok:
        raise RuntimeError(f"OpenAI postmortem request failed ({response.status_code}): {response.text[:1200]}")

    raw = response.json()
    result = json.loads(_extract_text(raw))
    for candidate in result.get("candidates") or []:
        candidate["candidate_id"] = candidate_id(candidate, week)
        candidate["status"] = "Pending"
        candidate["human_review_required"] = True
    web_calls = [x for x in (raw.get("output") or []) if x.get("type") == "web_search_call"]
    result["ai_meta"] = {
        "model": raw.get("model") or MODEL,
        "reasoning": REASONING_EFFORT,
        "response_id": raw.get("id"),
        "usage": raw.get("usage") or {},
        "web_search_calls": len(web_calls),
    }
    return result
