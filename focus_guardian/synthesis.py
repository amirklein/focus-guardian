"""Human-readable synthesis of Familiar sessions (offline + optional API)."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from focus_guardian import llm
from focus_guardian.analyzer import Finding
from focus_guardian.clipboard_intel import recent_transcriptions
from focus_guardian.timeline import WorkBlock


@dataclass
class ReviewDossier:
    goal: str
    lookback_hours: float
    blocks: list[WorkBlock]
    utterances: list
    findings: list[Finding]
    activity_notes: list[str]


def synthesis_cfg(cfg: dict) -> dict:
    return {**cfg.get("synthesis", {}), **cfg}


def build_dossier(
    cfg: dict,
    blocks: list[WorkBlock],
    findings: list[Finding],
    hours: float,
) -> ReviewDossier:
    window = int(hours * 60)
    utterances = recent_transcriptions(cfg, window_minutes=window)
    notes: list[str] = []

    if blocks:
        total_min = sum((b.end - b.start).total_seconds() / 60 for b in blocks)
        labels = Counter(b.label for b in blocks)
        top_label = labels.most_common(1)[0][0] if labels else "work"
        notes.append(f"~{total_min:.0f} minutes across {len(blocks)} focused stretches.")
        notes.append(f"Dominant mode: {top_label}.")
        build_n = sum(1 for b in blocks if "build" in b.label.lower())
        polish_n = sum(1 for b in blocks if "polish" in b.label.lower() or "slides" in b.label.lower())
        meet_n = sum(1 for b in blocks if "meeting" in b.label.lower())
        if build_n:
            notes.append(f"Real building showed up in {build_n} block(s).")
        if polish_n and build_n == 0:
            notes.append("Heavy on slides/mockups — light on shipping code or a demo.")
        if meet_n:
            notes.append(f"{meet_n} meeting block(s) — check they fed the deliverable, not replaced it.")

    return ReviewDossier(
        goal=cfg.get("currentGoal", ""),
        lookback_hours=hours,
        blocks=blocks,
        utterances=utterances,
        findings=findings,
        activity_notes=notes,
    )


def _wispr_themes(utterances, max_themes: int = 3) -> list[str]:
    if not utterances:
        return []
    themes: list[str] = []
    for u in utterances[-5:]:
        line = " ".join(u.text.split())[:200]
        if len(line) > 40:
            themes.append(line)
    return themes[-max_themes:]


def _sentiment_notes(utterances) -> str | None:
    """Lightweight tone read from dictation (no API)."""
    if not utterances:
        return None
    blob = " ".join(u.text.lower() for u in utterances[-8:])
    frustration = ("stuck", "frustrated", "rejected", "wasted", "anxious", "overwhelmed")
    avoidance = ("maybe later", "not sure", "procrastinat", "distracted", "rabbit hole")
    momentum = ("ship", "deadline", "finish", "submit", "mvp", "demo", "lock")
    fr = sum(1 for w in frustration if w in blob)
    av = sum(1 for w in avoidance if w in blob)
    mo = sum(1 for w in momentum if w in blob)
    if fr >= 2:
        return "Your dictation carries frustration or fatigue — worth a shorter, winnable next step."
    if av >= 2 and mo == 0:
        return "Language suggests hesitation or drift — name one concrete deliverable for the next hour."
    if mo >= 2:
        return "You sound oriented toward shipping — protect the next block from research tangents."
    return None


_OFFTRACK_MOVES = {
    "polish_heavy_day": "Close the slides/mockups and open your build tool — get one working proof out, even rough.",
    "latest_block_off_goal": "Re-read the brief, write one sentence for what ships today, and do only that.",
    "known_anti_pattern": "Break the loop you fell into — set a 25-minute timer on the one deliverable that matters.",
    "meeting_plus_polish": "After meetings, spend 25 minutes on the artifact you'd actually submit, not more research.",
}


def synthesize_review_offline(dossier: ReviewDossier, cfg: dict) -> str:
    """Warm, conversational recap without an API — a few sentences, not a report."""
    goal = dossier.goal or "your focus"
    sentences: list[str] = []

    if not dossier.blocks:
        sentences.append(
            f"I didn't see sustained work blocks in the last {dossier.lookback_hours:.0f} hours — "
            "could be breaks, Familiar paused, or a quiet stretch."
        )
    else:
        first, last = dossier.blocks[0], dossier.blocks[-1]
        span = f"{first.start.strftime('%H:%M')}–{last.end.strftime('%H:%M')}"
        story = f"You were active from {span}, working toward {goal}."
        if dossier.activity_notes:
            story += " " + " ".join(dossier.activity_notes)
        sentences.append(story)

    tone = _sentiment_notes(dossier.utterances)
    if tone:
        sentences.append(tone)

    if dossier.findings:
        f = dossier.findings[0]
        sentences.append(f"One thing worth naming: {f.message.rstrip('.')} — {f.evidence}")
    else:
        sentences.append("No real drift from your focus in this window — nice and steady.")

    if dossier.findings:
        move = _OFFTRACK_MOVES.get(
            dossier.findings[0].code,
            f"For the next 90 minutes: get back to {goal}, one shippable step, then stop.",
        )
    else:
        move = f"For the next 90 minutes: stay on {goal} and keep new tabs and critique loops out of the way."
    sentences.append(move)

    return " ".join(sentences)


def synthesize_review_api(dossier: ReviewDossier, cfg: dict) -> str:
    if llm.active_provider(cfg) is None:
        raise RuntimeError("Set GEMINI_API_KEY or ANTHROPIC_API_KEY for AI synthesis, or use offline mode.")

    style = synthesis_cfg(cfg).get("style", "coaching")
    payload = {
        "goal": dossier.goal,
        "lookback_hours": dossier.lookback_hours,
        "blocks": [
            {
                "start": b.start.isoformat(timespec="minutes"),
                "end": b.end.isoformat(timespec="minutes"),
                "label": b.label,
            }
            for b in dossier.blocks[-10:]
        ],
        "wispr_excerpts": _wispr_themes(dossier.utterances, 5),
        "findings": [{"code": f.code, "message": f.message, "evidence": f.evidence} for f in dossier.findings],
        "notes": dossier.activity_notes,
    }
    system = f"""You are Focus Guardian, texting a quick session recap to someone you're coaching.
Style: {style}. Warm, direct, like a supportive colleague — not a report.
Write 3-5 short plain sentences, flowing as prose (no markdown headings, no banners, no numbered
sections). Cover, in this order: what the session looked like vs their goal; anything worth naming
about drift or friction (only if real — otherwise reassure them they're on track); what their
dictation revealed if it's telling (skip if nothing notable); and end with exactly one concrete move
for the next 90 minutes. Under 120 words total."""
    try:
        return llm.chat(system, json.dumps(payload, indent=2), max_tokens=900, cfg=cfg)
    except llm.LLMError as e:
        raise RuntimeError(str(e)) from e


def synthesize_review(dossier: ReviewDossier, cfg: dict) -> str:
    sc = synthesis_cfg(cfg)
    if sc.get("useApiForReview") and llm.active_provider(cfg):
        try:
            return synthesize_review_api(dossier, cfg)
        except RuntimeError:
            pass
    return synthesize_review_offline(dossier, cfg)
