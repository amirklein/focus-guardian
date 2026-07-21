"""Shared live context for Slack pings and Cursor/Claude synthesis."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from focus_guardian.clipboard_intel import proactive_cfg, recent_transcriptions
from focus_guardian.drift import DriftAssessment, evaluate_drift
from focus_guardian.focus import has_active_focus, resolve_active_focus, with_resolved_focus
from focus_guardian.paths import live_context_json_path, live_context_md_path
from focus_guardian.timeline import TimelineEvent, recent_work_blocks, timeline_since


@dataclass
class CoachContext:
    updated_at: str
    focus_text: str
    focus_cadence: str
    focus_cadence_label: str
    focus_priorities: list[str]
    focus_expires_at: str | None
    has_focus: bool
    status: str  # on_track | drifting | no_focus
    headline: str
    recent_story: list[str]
    wispr_excerpts: list[str]
    dominant_apps: list[str]
    drift_reason: str
    drift_evidence: str
    should_chime: bool
    pending_alert: bool
    last_alert_at: str | None
    last_alert_reason: str | None
    work_blocks_6h: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _recent_window_minutes(cfg: dict) -> int:
    p = proactive_cfg(cfg)
    return int(p.get("evaluationWindowMinutes", 30))


def _story_from_events(events: list[TimelineEvent], window_min: int) -> tuple[list[str], list[str], list[str]]:
    """Build human-readable story lines, wispr excerpts, dominant apps."""
    if not events:
        return [], [], []

    since = datetime.now() - timedelta(minutes=window_min)
    recent = [e for e in events if e.ts >= since]
    if not recent:
        recent = events[-20:]

    story: list[str] = []
    wispr: list[str] = []
    apps = Counter(e.app for e in recent if e.kind == "screen")

    screens = [e for e in recent if e.kind == "screen"]
    if screens:
        last = screens[-1]
        mins = max(1, int((datetime.now() - screens[0].ts).total_seconds() / 60))
        story.append(f"Most recently on {last.app} — {last.title[:120]} (~{mins} min in window).")

    for e in recent:
        if e.kind == "transcription" and e.detail.strip():
            excerpt = " ".join(e.detail.split())[:240]
            if excerpt and excerpt not in wispr:
                wispr.append(excerpt)

    for app, count in apps.most_common(4):
        if app not in ("unknown", "clipboard", "wispr"):
            story.append(f"{app} ({count} captures)")

    dominant = [a for a, _ in apps.most_common(3) if a not in ("unknown", "clipboard", "wispr")]
    return story, wispr[:5], dominant


def _headline(
    *,
    status: str,
    focus_text: str,
    cadence_label: str,
    drift: DriftAssessment | None,
    dominant_apps: list[str],
    has_focus: bool,
) -> str:
    if not has_focus:
        return "No focus set yet — tell me what you're working on."
    if status == "on_track":
        return f"On track with {cadence_label.lower()}: {focus_text[:100]}."
    app_hint = dominant_apps[0] if dominant_apps else "other tabs"
    evidence = (drift.evidence if drift else "")[:120]
    if evidence:
        return f"Drifting — {evidence}"
    return f"You've been on {app_hint} while your focus is {focus_text[:80]}."


def build_coach_context(
    cfg: dict,
    *,
    drift: DriftAssessment | None = None,
    pending_alert: bool = False,
    last_alert_at: str | None = None,
    last_alert_reason: str | None = None,
) -> CoachContext:
    cfg = with_resolved_focus(cfg)
    resolved = resolve_active_focus(cfg)
    has_focus = has_active_focus(cfg)
    window_min = _recent_window_minutes(cfg)

    if drift is None:
        drift = evaluate_drift(cfg)

    events = timeline_since(cfg, hours=window_min / 60.0)
    story, wispr, dominant = _story_from_events(events, window_min)

    utterances = recent_transcriptions(cfg, window_minutes=window_min)
    for u in utterances[-3:]:
        excerpt = " ".join(u.text.split())[:240]
        if excerpt and excerpt not in wispr:
            wispr.append(excerpt)

    if not has_focus:
        status = "no_focus"
    elif drift.should_chime or drift.codes:
        status = "drifting"
    else:
        status = "on_track"

    blocks = recent_work_blocks(cfg, hours=6.0)
    block_dicts = [
        {
            "start": b.start.isoformat(timespec="minutes"),
            "end": b.end.isoformat(timespec="minutes"),
            "label": b.label,
            "minutes": int((b.end - b.start).total_seconds() / 60),
            "dominant_apps": [a for a, _ in b.dominant_apps[:2]],
        }
        for b in blocks[-8:]
    ]

    headline = _headline(
        status=status,
        focus_text=resolved.text,
        cadence_label=resolved.cadence_label,
        drift=drift,
        dominant_apps=dominant,
        has_focus=has_focus,
    )

    return CoachContext(
        updated_at=datetime.now().isoformat(timespec="seconds"),
        focus_text=resolved.text,
        focus_cadence=resolved.cadence,
        focus_cadence_label=resolved.cadence_label,
        focus_priorities=list(resolved.priorities),
        focus_expires_at=resolved.expires_at,
        has_focus=has_focus,
        status=status,
        headline=headline,
        recent_story=story,
        wispr_excerpts=wispr[:5],
        dominant_apps=dominant,
        drift_reason=drift.reason,
        drift_evidence=drift.evidence,
        should_chime=drift.should_chime,
        pending_alert=pending_alert,
        last_alert_at=last_alert_at,
        last_alert_reason=last_alert_reason,
        work_blocks_6h=block_dicts,
    )


def _write_live_context_md(ctx: CoachContext) -> None:
    lines = [
        "# Focus Guardian — live context",
        "",
        f"_Updated: {ctx.updated_at}_",
        "",
        f"**{ctx.headline}**",
        "",
        f"**Focus ({ctx.focus_cadence_label}):** {ctx.focus_text}",
    ]
    if ctx.focus_priorities:
        lines.append(f"Priorities: {', '.join(ctx.focus_priorities)}")
    lines.append(f"Status: {ctx.status}")
    if ctx.pending_alert:
        lines.append("")
        lines.append(f"**Pending Slack alert** — {ctx.last_alert_reason or ctx.drift_reason}")
        if ctx.last_alert_at:
            lines.append(f"Alert at: {ctx.last_alert_at}")

    if ctx.recent_story:
        lines.extend(["", "## What Familiar saw recently"])
        for s in ctx.recent_story:
            lines.append(f"- {s}")

    if ctx.wispr_excerpts:
        lines.extend(["", "## Dictation / clipboard"])
        for w in ctx.wispr_excerpts:
            lines.append(f"- \"{w[:200]}\"")

    if ctx.work_blocks_6h:
        lines.extend(["", "## Work blocks (last 6h)"])
        for b in ctx.work_blocks_6h:
            lines.append(f"- {b['start']}–{b['end']}: {b['label']}")

    lines.extend([
        "",
        "_For full coaching, ask in Cursor or Claude: \"catch me up\"_",
    ])
    live_context_md_path().write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_live_context() -> dict[str, Any] | None:
    p = live_context_json_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def refresh_live_context(
    cfg: dict,
    *,
    drift: DriftAssessment | None = None,
    chime_sent: bool = False,
) -> CoachContext:
    """Build and persist live context. Call on every guardian evaluation."""
    prev = load_live_context() or {}
    pending = bool(prev.get("pending_alert"))
    last_at = prev.get("last_alert_at")
    last_reason = prev.get("last_alert_reason")

    if chime_sent and drift and drift.should_chime:
        pending = True
        last_at = datetime.now().isoformat(timespec="seconds")
        last_reason = drift.reason

    ctx = build_coach_context(
        cfg,
        drift=drift,
        pending_alert=pending,
        last_alert_at=last_at,
        last_alert_reason=last_reason,
    )

    live_context_json_path().write_text(
        json.dumps(ctx.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    _write_live_context_md(ctx)
    return ctx


def clear_pending_alert() -> None:
    """Clear pending_alert after user engages in Cursor/Claude."""
    data = load_live_context()
    if not data:
        return
    data["pending_alert"] = False
    live_context_json_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    fields = CoachContext.__dataclass_fields__
    kwargs = {k: data[k] for k in fields if k in data}
    ctx = CoachContext(**kwargs)
    _write_live_context_md(ctx)


def format_context_for_host(ctx: CoachContext | dict[str, Any]) -> str:
    """Rich dossier string for MCP / host model synthesis."""
    if isinstance(ctx, CoachContext):
        d = ctx.to_dict()
    else:
        d = ctx

    parts = [
        f"Headline: {d.get('headline', '')}",
        f"Status: {d.get('status', 'unknown')}",
        f"Focus ({d.get('focus_cadence_label', '')}): {d.get('focus_text', '')}",
    ]
    if d.get("focus_priorities"):
        parts.append(f"Priorities: {', '.join(d['focus_priorities'])}")
    if d.get("recent_story"):
        parts.append("\nWhat Familiar saw recently:")
        for line in d["recent_story"]:
            parts.append(f"  - {line}")
    if d.get("wispr_excerpts"):
        parts.append("\nDictation / clipboard:")
        for w in d["wispr_excerpts"]:
            parts.append(f'  - "{w[:200]}"')
    if d.get("drift_evidence"):
        parts.append(f"\nDrift signal: {d['drift_evidence']}")
    if d.get("pending_alert"):
        parts.append(f"\nSlack alert pending since {d.get('last_alert_at', '?')}: {d.get('last_alert_reason', '')}")
    if d.get("work_blocks_6h"):
        parts.append("\nWork blocks (last 6h):")
        for b in d["work_blocks_6h"]:
            parts.append(f"  - {b.get('start')}–{b.get('end')}: {b.get('label')}")
    return "\n".join(parts)
