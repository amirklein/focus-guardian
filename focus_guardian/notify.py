"""Slack-only notifications (drift chime + review)."""

from __future__ import annotations

from datetime import datetime

from focus_guardian.analyzer import Report
from focus_guardian.focus import resolve_active_focus, with_resolved_focus
from focus_guardian.paths import last_notify_path, log_path
from focus_guardian.snooze import is_snoozed
from focus_guardian.slack_client import (
    SlackError,
    format_drift_message,
    format_review_message,
    post_message,
)


def should_skip_cooldown(cooldown_minutes: int) -> bool:
    p = last_notify_path()
    if not p.exists():
        return False
    try:
        last = int(p.read_text(encoding="utf-8").strip())
    except ValueError:
        return False
    elapsed = datetime.now().timestamp() - last
    return elapsed < cooldown_minutes * 60


def mark_notified() -> None:
    last_notify_path().write_text(str(int(datetime.now().timestamp())), encoding="utf-8")
    with log_path().open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} slack notified\n")


def _chime_cooldown_minutes(cfg: dict) -> int:
    p = {**cfg.get("proactive", {}), **cfg}
    return int(p.get("chimeCooldownMinutes", p.get("cooldownMinutes", 25)))


def _notifications_enabled(cfg: dict) -> bool:
    n = cfg.get("notifications") or {}
    return n.get("channel", "slack") == "slack"


def _log_slack_error(err: SlackError) -> None:
    with log_path().open("a", encoding="utf-8") as f:
        f.write(f"SLACK ERROR {datetime.now().isoformat(timespec='seconds')} {err}\n")


def notify_drift_chime(assessment, nudge: str, cfg: dict) -> bool:
    from focus_guardian.drift import DriftAssessment

    if not isinstance(assessment, DriftAssessment):
        return False
    if not assessment.should_chime:
        return False
    if not _notifications_enabled(cfg):
        return False
    if is_snoozed():
        return False
    if should_skip_cooldown(_chime_cooldown_minutes(cfg)):
        return False

    cfg = with_resolved_focus(cfg)
    focus = resolve_active_focus(cfg)
    text = format_drift_message(
        cadence_label=focus.cadence_label,
        focus_text=focus.text,
        wispr_excerpt=assessment.wispr_excerpt,
        reason=assessment.reason,
        nudge=nudge,
        expires_at=focus.expires_at,
    )
    try:
        post_message(text, cfg)
        mark_notified()
        return True
    except SlackError as e:
        _log_slack_error(e)
        return False


def maybe_notify(report: Report, cfg: dict) -> bool:
    if not report.should_notify:
        return False
    if not _notifications_enabled(cfg):
        return False
    if is_snoozed():
        return False
    cooldown = int(cfg.get("cooldownMinutes", 20))
    if should_skip_cooldown(cooldown):
        return False

    cfg = with_resolved_focus(cfg)
    focus = resolve_active_focus(cfg)
    summary = report.summary
    if report.findings:
        summary = f"{summary} — {report.findings[0].evidence}"

    text = format_drift_message(
        cadence_label=focus.cadence_label,
        focus_text=focus.text or report.goal,
        wispr_excerpt="",
        reason=summary[:300],
        nudge="Run `fgr review --human` for a full recap.",
        expires_at=focus.expires_at,
    )
    try:
        post_message(text, cfg)
        mark_notified()
        return True
    except SlackError as e:
        _log_slack_error(e)
        return False


def notify_review(
    cfg: dict,
    *,
    title: str,
    narrative: str,
    summary: str,
    respect_cooldown: bool = False,
) -> bool:
    if not _notifications_enabled(cfg):
        return False
    if is_snoozed():
        return False
    if respect_cooldown and should_skip_cooldown(int(cfg.get("cooldownMinutes", 20))):
        return False

    cfg = with_resolved_focus(cfg)
    focus = resolve_active_focus(cfg)
    text = format_review_message(
        title=title,
        cadence_label=focus.cadence_label,
        focus_text=focus.text,
        narrative=narrative,
        summary=summary,
    )
    try:
        post_message(text, cfg)
        mark_notified()
        return True
    except SlackError as e:
        _log_slack_error(e)
        return False
