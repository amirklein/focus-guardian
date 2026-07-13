"""Pattern detection over recent Familiar captures."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from focus_guardian.familiar import parse_capture_time, read_frontmatter, stills_root
from focus_guardian.focus import with_resolved_focus


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    evidence: str


@dataclass
class Report:
    checked_at: str
    window_minutes: int
    capture_count: int
    goal: str
    on_track_ratio: float
    activity_mix: dict[str, int]
    findings: list[Finding]
    summary: str
    should_notify: bool

    def to_dict(self) -> dict:
        d = asdict(self)
        d["findings"] = [asdict(f) for f in self.findings]
        return d


def classify_capture(app: str, title: str, cfg: dict) -> str:
    t = title.lower()
    if app in cfg.get("buildSurfaces", []):
        return "build"
    if app in cfg.get("distractionApps", []):
        return "distraction"
    for pat in cfg.get("distractionTitlePatterns", []):
        if pat.lower() in t:
            return "distraction"
    for pat in cfg.get("polishTitlePatterns", []):
        if pat.lower() in t:
            return "polish"
    if app in cfg.get("researchSurfaces", []):
        if "claude" in t or app == "Claude":
            return "ai_chat"
        if "gemini" in t or "research" in t:
            return "research"
        return "browser"
    keywords = [k.lower() for k in cfg.get("goalKeywords", [])]
    if any(k in t for k in keywords):
        return "on_track"
    if app == "unknown" or title == "unknown":
        return "other"
    return "other"


def goal_match_ratio(records: list[tuple], cfg: dict) -> float:
    if not records:
        return 0.0
    keywords = [k.lower() for k in cfg.get("goalKeywords", [])]
    if not keywords:
        return 0.0
    hits = sum(
        1
        for _, app, title in records
        if any(k in f"{app} {title}".lower() for k in keywords)
        or classify_capture(app, title, cfg) == "build"
    )
    return hits / len(records)


def longest_streak_minutes(
    records: list[tuple[datetime, str, str]], labels: set[str], cfg: dict
) -> float:
    if len(records) < 2:
        return 0.0
    best = 0.0
    start: datetime | None = None
    for ts, app, title in records:
        if classify_capture(app, title, cfg) in labels:
            if start is None:
                start = ts
        elif start is not None:
            best = max(best, (ts - start).total_seconds() / 60)
            start = None
    if start is not None:
        best = max(best, (records[-1][0] - start).total_seconds() / 60)
    return best


def count_switches(records: list[tuple]) -> int:
    switches = 0
    prev: tuple[str, str] | None = None
    for _, app, title in records:
        key = (app, title)
        if prev is not None and key != prev:
            switches += 1
        prev = key
    return switches


def load_recent_records(root: Path, window_minutes: int) -> list[tuple[datetime, str, str]]:
    now = datetime.now()
    cutoff = now - timedelta(minutes=window_minutes)
    records: list[tuple[datetime, str, str]] = []
    for session in root.iterdir():
        if not session.is_dir() or not session.name.startswith("session-"):
            continue
        for md in session.glob("*.md"):
            ts = parse_capture_time(md.stem)
            if ts is None or ts < cutoff:
                continue
            fm = read_frontmatter(md)
            app = fm.get("app", "unknown")
            title = fm.get("window_title_norm", fm.get("window_title_raw", "unknown"))
            records.append((ts, app, title))
    records.sort(key=lambda x: x[0])
    return records


def analyze(cfg: dict, root: Path | None = None) -> Report:
    cfg = with_resolved_focus(cfg)
    window = int(cfg.get("checkWindowMinutes", 15))
    root = root or stills_root(cfg)
    now = datetime.now()
    records = load_recent_records(root, window)
    goal = cfg.get("currentGoal", "(no goal set)")
    on_track = goal_match_ratio(records, cfg)
    findings: list[Finding] = []

    if len(records) < 5:
        return Report(
            checked_at=now.isoformat(timespec="seconds"),
            window_minutes=window,
            capture_count=len(records),
            goal=goal,
            on_track_ratio=on_track,
            activity_mix={},
            findings=[],
            summary="Not enough recent activity to judge focus yet.",
            should_notify=False,
        )

    mix = Counter(classify_capture(a, t, cfg) for _, a, t in records)
    switches = count_switches(records)
    th = cfg.get("thresholds", {})
    distraction_mins = longest_streak_minutes(records, {"distraction"}, cfg)
    ai_mins = longest_streak_minutes(records, {"ai_chat", "research"}, cfg)
    polish_mins = longest_streak_minutes(records, {"polish"}, cfg)
    build_mins = longest_streak_minutes(records, {"build"}, cfg)

    if distraction_mins >= th.get("distractionMinutes", 10):
        findings.append(
            Finding(
                severity="critical",
                code="distraction_streak",
                message="You have been off-task for a while.",
                evidence=(
                    f"~{distraction_mins:.0f} min on distraction surfaces "
                    "(LinkedIn, WhatsApp, personal tabs, etc.)."
                ),
            )
        )

    if switches >= th.get("contextSwitchesPerWindow", 12):
        findings.append(
            Finding(
                severity="warn",
                code="context_switch_burst",
                message="High context switching — shallow work pattern.",
                evidence=f"{switches} window changes in the last {window} minutes.",
            )
        )

    if ai_mins >= th.get("aiLoopMinutes", 18) and build_mins < 3:
        findings.append(
            Finding(
                severity="warn",
                code="ai_research_loop",
                message="You are in an AI chat / research loop without building.",
                evidence=(
                    f"~{ai_mins:.0f} min in Claude/Gemini/research; "
                    f"almost no build-surface time."
                ),
            )
        )

    if polish_mins >= th.get("slidesWithoutBuildMinutes", 25) and build_mins < 5:
        findings.append(
            Finding(
                severity="warn",
                code="polish_without_build",
                message="Polishing artifacts before the core work is done.",
                evidence=(
                    f"~{polish_mins:.0f} min on Slides/Lovable/Preview; "
                    f"only ~{build_mins:.0f} min building."
                ),
            )
        )

    if on_track < 0.25 and mix.get("distraction", 0) + mix.get("other", 0) > len(records) * 0.4:
        findings.append(
            Finding(
                severity="warn",
                code="goal_drift",
                message="Current activity does not match your stated goal.",
                evidence=f"Goal match ~{on_track:.0%}. Recent mix: {dict(mix)}.",
            )
        )

    if not findings:
        summary = f"On track. Goal alignment ~{on_track:.0%} in the last {window} minutes."
        should_notify = False
    else:
        top = max(findings, key=lambda f: {"info": 0, "warn": 1, "critical": 2}[f.severity])
        summary = top.message
        should_notify = any(f.severity in ("warn", "critical") for f in findings)

    return Report(
        checked_at=now.isoformat(timespec="seconds"),
        window_minutes=window,
        capture_count=len(records),
        goal=goal,
        on_track_ratio=on_track,
        activity_mix=dict(mix),
        findings=findings,
        summary=summary,
        should_notify=should_notify,
    )
