"""User-configurable drift rules and optional semantic layer."""

from __future__ import annotations

import json

from focus_guardian import llm
from focus_guardian.clipboard_intel import topic_score


def drift_rules(cfg: dict) -> dict:
    defaults = {
        "wisprOffTopic": True,
        "distractionStreak": True,
        "aiLoop": True,
        "polishSpiral": True,
        "topicPivot": True,
        "wisprDistractionSpike": True,
        "offTopicPhrases": [],
        "onTopicPhrases": [],
        "sentimentEnabled": True,
        "useApiForDrift": False,
    }
    return {**defaults, **cfg.get("driftRules", {})}


def rule_enabled(cfg: dict, name: str) -> bool:
    return bool(drift_rules(cfg).get(name, True))


def phrase_penalty(text: str, cfg: dict) -> float:
    """Adjust topic score from configured phrase lists (0 = neutral)."""
    rules = drift_rules(cfg)
    blob = text.lower()
    penalty = 0.0
    for p in rules.get("offTopicPhrases") or []:
        if p.lower() in blob:
            penalty += 0.2
    boost = 0.0
    for p in rules.get("onTopicPhrases") or []:
        if p.lower() in blob:
            boost += 0.15
    return min(0.5, penalty) - min(0.3, boost)


def adjusted_topic_score(text: str, cfg: dict) -> float:
    base = topic_score(text, cfg)
    adj = base - phrase_penalty(text, cfg)
    return max(0.0, min(1.0, round(adj, 3)))


def enrich_drift_with_api(
    *,
    goal: str,
    wispr_excerpt: str,
    evidence: str,
    codes: list[str],
    cfg: dict,
) -> dict | None:
    """Optional LLM pass: sentiment + whether drift is real vs false positive."""
    rules = drift_rules(cfg)
    if not rules.get("useApiForDrift") or llm.active_provider(cfg) is None:
        return None

    payload = {
        "goal": goal,
        "wispr_excerpt": wispr_excerpt,
        "evidence": evidence,
        "codes": codes,
        "off_topic_phrases": rules.get("offTopicPhrases", []),
        "on_topic_phrases": rules.get("onTopicPhrases", []),
    }
    system = """You judge work-session drift for a focus coach.
Return ONLY valid JSON:
{"should_chime": bool, "sentiment": "focused|anxious|avoidant|frustrated|neutral",
 "summary": "one sentence human explanation",
 "nudge": "one sentence next action"}
Be conservative: should_chime true only if clearly off-goal or stuck, not normal thinking aloud."""
    try:
        return llm.chat_json(system, json.dumps(payload), max_tokens=300, cfg=cfg)
    except (llm.LLMError, json.JSONDecodeError):
        return None
