"""Deep review using full Familiar timeline (not just a 15-minute snapshot)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from focus_guardian.analyzer import Finding, goal_match_ratio
from focus_guardian.focus import with_resolved_focus
from focus_guardian.timeline import WorkBlock, recent_work_blocks, timeline_since


@dataclass
class SessionReview:
    checked_at: str
    profile: str
    goal: str
    lookback_hours: float
    work_blocks: list[dict]
    narrative: str
    findings: list[Finding]
    summary: str
    should_notify: bool

    def to_dict(self) -> dict:
        return {
            "checked_at": self.checked_at,
            "profile": self.profile,
            "goal": self.goal,
            "lookback_hours": self.lookback_hours,
            "work_blocks": self.work_blocks,
            "narrative": self.narrative,
            "findings": [asdict(f) for f in self.findings],
            "summary": self.summary,
            "should_notify": self.should_notify,
        }


def _narrative_from_blocks(blocks: list[WorkBlock], goal: str) -> str:
    if not blocks:
        return "No sustained work blocks detected in the lookback window."
    lines = [f"Goal: {goal}", "", "What you actually did (chronological work blocks):"]
    for i, b in enumerate(blocks[-8:], 1):
        apps = ", ".join(f"{a} ({n})" for a, n in b.dominant_apps[:2])
        lines.append(
            f"{i}. {b.start.strftime('%H:%M')}–{b.end.strftime('%H:%M')}: {b.label}"
            + (f" [{apps}]" if apps else "")
        )
        # Last screen title in block as anchor
        screens = [e for e in b.events if e.kind == "screen"]
        if screens:
            lines.append(f"   Last focus: {screens[-1].app} — {screens[-1].title[:80]}")
        clips = [e for e in b.events if e.kind in ("clipboard", "transcription")]
        if clips:
            label = "Wispr" if clips[-1].kind == "transcription" else "Clipboard"
            excerpt = clips[-1].detail.replace("\n", " ")[:240]
            lines.append(f"   {label}: {excerpt}")
    return "\n".join(lines)


def review_session(cfg: dict) -> SessionReview:
    """Analyze recent work blocks + optional snapshot rules on the latest block."""
    cfg = with_resolved_focus(cfg)
    hours = float(cfg.get("lookbackHours", 6))
    blocks = recent_work_blocks(cfg, hours)
    goal = cfg.get("currentGoal", "")
    profile = cfg.get("activeProfile", "custom")

    block_dicts = [
        {
            "start": b.start.isoformat(timespec="minutes"),
            "end": b.end.isoformat(timespec="minutes"),
            "label": b.label,
            "minutes": int((b.end - b.start).total_seconds() / 60),
            "dominant_apps": b.dominant_apps,
        }
        for b in blocks
    ]

    findings: list[Finding] = []

    # Heuristics across blocks (job-search oriented)
    if blocks:
        labels = " ".join(b.label.lower() for b in blocks)
        total_min = sum((b.end - b.start).total_seconds() / 60 for b in blocks)
        polish_blocks = sum(1 for b in blocks if "polish" in b.label.lower() or "slides" in b.label.lower())
        build_blocks = sum(1 for b in blocks if "build" in b.label.lower())
        meeting_blocks = sum(1 for b in blocks if "meeting" in b.label.lower())

        if polish_blocks >= 2 and build_blocks == 0 and total_min > 60:
            findings.append(
                Finding(
                    severity="warn",
                    code="polish_heavy_day",
                    message="Today skewed toward slides/mockups, not building or submitting.",
                    evidence=f"{polish_blocks} polish-heavy blocks, 0 build blocks over ~{total_min:.0f}m.",
                )
            )

        if meeting_blocks >= 1 and polish_blocks >= 1 and build_blocks == 0:
            findings.append(
                Finding(
                    severity="info",
                    code="meeting_plus_polish",
                    message="Mix of meetings and polish — confirm you have a shippable artifact for assignments.",
                    evidence="Meetings don't replace assignment deliverables.",
                )
            )

        # Latest block drift check using analyzer on last block window
        last = blocks[-1]
        from focus_guardian.familiar import stills_root
        from focus_guardian.analyzer import load_recent_records

        window_min = max(15, int((last.end - last.start).total_seconds() / 60) + 5)
        cfg_snap = {**cfg, "checkWindowMinutes": min(window_min, 120)}
        records = load_recent_records(stills_root(cfg), cfg_snap["checkWindowMinutes"])
        records = [r for r in records if r[0] >= last.start]
        if len(records) >= 5:
            on_track = goal_match_ratio(records, cfg)
            if on_track < 0.2:
                findings.append(
                    Finding(
                        severity="warn",
                        code="latest_block_off_goal",
                        message="Your most recent work block doesn't match your stated goal.",
                        evidence=f"Latest block: {last.label}. Goal match ~{on_track:.0%}.",
                    )
                )

    anti = cfg.get("antiPatterns") or []
    events = timeline_since(cfg, hours)
    blob = " ".join(f"{e.app} {e.title} {e.detail}".lower() for e in events[-80:])
    for pattern in anti:
        if pattern.lower() in blob:
            findings.append(
                Finding(
                    severity="warn",
                    code="known_anti_pattern",
                    message=f"Pattern detected: {pattern}",
                    evidence="Seen in recent screen/clipboard timeline.",
                )
            )

    if not findings:
        summary = f"Last {hours:.0f}h: {len(blocks)} work blocks — no strong drift vs your goal."
        should_notify = False
    else:
        top = max(findings, key=lambda f: {"info": 0, "warn": 1, "critical": 2}[f.severity])
        summary = top.message
        should_notify = any(f.severity in ("warn", "critical") for f in findings)

    from focus_guardian.synthesis import build_dossier, synthesize_review

    dossier = build_dossier(cfg, blocks, findings, hours)
    narrative = synthesize_review(dossier, cfg)

    return SessionReview(
        checked_at=datetime.now().isoformat(timespec="seconds"),
        profile=profile,
        goal=goal,
        lookback_hours=hours,
        work_blocks=block_dicts,
        narrative=narrative,
        findings=findings,
        summary=summary,
        should_notify=should_notify,
    )
