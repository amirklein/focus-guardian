"""Optional LLM coaching layer (works from any terminal / Claude Code)."""

from __future__ import annotations

import json

from focus_guardian import llm
from focus_guardian.analyzer import Report

SYSTEM = """You are Focus Guardian, a direct productivity coach.
The user pairs you with Familiar (screen activity summaries). You receive a JSON report of recent behavior patterns.
Rules:
- Under 120 words.
- Name the drift pattern concretely from the evidence.
- Give exactly ONE next action for the next 25 minutes tied to their stated goal.
- No generic advice. No bullet lists longer than 3 items.
- Tone: firm, supportive, senior colleague — not preachy."""


def format_prompt(report: Report, narrative: str | None = None) -> str:
    payload = report.to_dict()
    parts = [f"Goal: {report.goal}", ""]
    if narrative:
        parts.extend([narrative, ""])
    parts.extend(
        [
            f"Report JSON:\n{json.dumps(payload, indent=2)}",
            "",
            "What should they do right now?",
        ]
    )
    return "\n".join(parts)


def coach_with_api(report: Report, model: str | None = None, cfg: dict | None = None) -> str:
    if llm.active_provider(cfg) is None:
        raise RuntimeError(
            "Set GEMINI_API_KEY or ANTHROPIC_API_KEY for API coaching, or use: fgr coach --print"
        )
    try:
        text = llm.chat(SYSTEM, format_prompt(report), max_tokens=400, cfg=cfg, model=model)
    except llm.LLMError as e:
        raise RuntimeError(str(e)) from e
    return text or "(empty response)"


def coach_drift_nudge(assessment, cfg: dict) -> str:
    """Offline nudge for proactive drift chime."""
    from focus_guardian.drift import DriftAssessment

    if not isinstance(assessment, DriftAssessment):
        return ""
    if assessment.suggested_nudge:
        return assessment.suggested_nudge
    goal = cfg.get("currentGoal", "your goal")
    return f"Return to: {goal}. Next 25 min: one concrete deliverable."


def coach_offline(report: Report) -> str:
    """Deterministic coaching when no API key is available."""
    if not report.findings:
        return (
            f"On track (~{report.on_track_ratio:.0%} aligned). "
            f"Stay on: {report.goal}. Next 25 min: continue the primary artifact only."
        )
    f = max(report.findings, key=lambda x: {"info": 0, "warn": 1, "critical": 2}[x.severity])
    actions = {
        "distraction_streak": "Close the distraction tab. Open your primary work surface and set a 25-minute timer.",
        "context_switch_burst": "Pick ONE window. Write the next concrete deliverable in one sentence, then execute only that.",
        "ai_research_loop": "Stop chatting. Write 5 bullets: problem, recommendation, 3 trade-offs. Then build one proof.",
        "polish_without_build": "Freeze slides/mockups. Ship one working proof in your build tool first.",
        "goal_drift": "Re-read your goal aloud. Do the smallest step that directly advances it — nothing else.",
        "wispr_off_topic": "Your dictation drifted off goal. Close unrelated tabs; 25 min on the deliverable only.",
        "topic_pivot": "You pivoted topics in speech. Re-open the assignment brief and do the next concrete step.",
        "wispr_distraction_spike": "Off-topic speech on a distraction surface. Close it and open your build tool.",
    }
    action = actions.get(f.code, "Return to your stated goal for 25 minutes with one deliverable.")
    return f"{f.message} {f.evidence}\n\nNext 25 min: {action}"
