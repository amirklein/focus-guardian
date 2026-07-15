"""Human-readable synthesis of Familiar sessions (offline + optional API)."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

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


def _fg_bin_hint() -> str:
    return "~/focus-guardian/.venv/bin/fg"


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


def synthesize_review_offline(dossier: ReviewDossier, cfg: dict) -> str:
    """Rich coaching-style narrative without an API."""
    goal = dossier.goal or "(no goal set — run: fg goal \"your focus for today\")"
    lines: list[str] = []

    lines.append("═" * 60)
    lines.append("FOCUS GUARDIAN — SESSION SYNTHESIS")
    lines.append("═" * 60)
    lines.append("")

    # Headline story
    if not dossier.blocks:
        lines.append("## The story")
        lines.append(
            f"In the last {dossier.lookback_hours:.0f} hours I didn't see sustained work blocks "
            "(gaps may mean breaks, Familiar paused, or light activity)."
        )
    else:
        first, last = dossier.blocks[0], dossier.blocks[-1]
        span = f"{first.start.strftime('%H:%M')}–{last.end.strftime('%H:%M')}"
        lines.append("## The story")
        lines.append(
            f"You were active from roughly {span}. "
            + (dossier.activity_notes[0] if dossier.activity_notes else "")
        )
        for note in dossier.activity_notes[1:]:
            lines.append(note)

    lines.append("")
    lines.append(f"**Stated goal:** {goal}")
    lines.append("")

    # Chronology (shorter than raw dump)
    if dossier.blocks:
        lines.append("## How the day unfolded")
        for b in dossier.blocks[-6:]:
            apps = ", ".join(a for a, _ in b.dominant_apps[:2])
            lines.append(
                f"- **{b.start.strftime('%H:%M')}–{b.end.strftime('%H:%M')}** — {b.label}"
                + (f" ({apps})" if apps else "")
            )
            trans = [e for e in b.events if e.kind == "transcription"]
            if trans:
                excerpt = trans[-1].detail.replace("\n", " ")[:180]
                lines.append(f"  - *You said:* \"{excerpt}…\"")
        lines.append("")

    # Wispr / intent layer
    themes = _wispr_themes(dossier.utterances)
    if themes:
        lines.append("## What you were actually thinking (Wispr)")
        for i, t in enumerate(themes, 1):
            lines.append(f"{i}. \"{t}…\"")
        tone = _sentiment_notes(dossier.utterances)
        if tone:
            lines.append(f"\n*{tone}*")
        lines.append("")

    # Drift & patterns
    if dossier.findings:
        lines.append("## Where you drifted (or risked it)")
        for f in dossier.findings:
            lines.append(f"- **{f.message}** — {f.evidence}")
        lines.append("")
    else:
        lines.append("## Drift check")
        lines.append("No strong drift patterns vs your goal in this window.")
        lines.append("")

    # One clear next move
    lines.append("## One move for the next 90 minutes")
    if dossier.findings:
        code = dossier.findings[0].code
        moves = {
            "polish_heavy_day": "Close Slides/Lovable. Open your build tool and produce one working proof — even rough.",
            "latest_block_off_goal": "Re-read the assignment brief. Write one sentence: what ships today. Do only that.",
            "known_anti_pattern": "Stop the loop you fell into. Set a 25-minute timer on the primary deliverable.",
            "meeting_plus_polish": "After meetings: 25 minutes on the artifact you'd submit, not more research.",
        }
        lines.append(moves.get(code, f"Return to: {goal}. One shippable increment, then stop."))
    else:
        lines.append(f"Stay on: {goal}. Protect the next block from new tabs and critique loops.")

    lines.append("")
    lines.append("—")
    lines.append(f"*Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · {_fg_bin_hint()} review --human*")
    return "\n".join(lines)


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
    system = f"""You are Focus Guardian writing a session synthesis for a job-searching professional.
Style: {style}. Warm, direct, senior-coach tone — not a dry activity log.
Structure with markdown headings:
1. The story (2-4 sentences — arc of the session vs their goal)
2. What worked
3. Drift & friction (honest, specific)
4. What their dictation revealed (intent, emotion, avoidance if any)
5. One move for the next 90 minutes (single concrete action)
Under 400 words. No bullet lists longer than 4 items."""
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
