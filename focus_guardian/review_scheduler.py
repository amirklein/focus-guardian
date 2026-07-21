"""Scheduled daily / weekly review summaries to Slack."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from focus_guardian.focus import has_active_focus, with_resolved_focus
from focus_guardian.notify import notify_review
from focus_guardian.paths import state_dir
from focus_guardian.review import review_session


def _schedule_state_path():
    return state_dir() / "review_schedule.json"


def _load_schedule_state() -> dict:
    p = _schedule_state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_schedule_state(state: dict) -> None:
    _schedule_state_path().write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _parse_hhmm(s: str) -> tuple[int, int]:
    parts = s.strip().split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    return h, m


def _weekday_name(dt: datetime) -> str:
    return ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[dt.weekday()]


def _should_fire_daily(cfg: dict, now: datetime, state: dict) -> bool:
    sched = (cfg.get("reviewSchedule") or {}).get("daily") or {}
    if not sched.get("enabled", True):
        return False
    time_s = sched.get("time", "18:00")
    h, m = _parse_hhmm(time_s)
    if now.hour < h or (now.hour == h and now.minute < m):
        return False
    key = now.strftime("%Y-%m-%d")
    return state.get("lastDaily") != key


def _should_fire_weekly(cfg: dict, now: datetime, state: dict) -> bool:
    sched = (cfg.get("reviewSchedule") or {}).get("weekly") or {}
    if not sched.get("enabled", True):
        return False
    time_s = sched.get("time", "17:00")
    h, m = _parse_hhmm(time_s)

    day = (sched.get("day") or "end").lower()
    if day == "end":
        from focus_guardian.focus import week_schedule

        target = week_schedule(cfg)["endDay"]
    else:
        target = day[:3]

    if _weekday_name(now) != target:
        return False
    if now.hour < h or (now.hour == h and now.minute < m):
        return False
    key = now.strftime("%Y-%W")
    return state.get("lastWeekly") != key


def _run_scheduled_review(cfg: dict, kind: str) -> bool:
    if not has_active_focus(cfg):
        return False
    sched = (cfg.get("reviewSchedule") or {}).get(kind) or {}
    hours = float(sched.get("lookbackHours") or cfg.get("lookbackHours", 6))
    run_cfg = with_resolved_focus({**cfg, "lookbackHours": hours})
    review = review_session(run_cfg)
    title = "daily review" if kind == "daily" else "weekly review"
    sent = notify_review(
        cfg,
        title=title,
        narrative=review.narrative,
        summary=review.summary,
        respect_cooldown=False,
    )
    return sent


def maybe_run_scheduled_reviews(cfg: dict, now: datetime | None = None) -> list[str]:
    """Check schedule; send daily/weekly Slack summaries if due. Returns kinds fired."""
    now = now or datetime.now()
    state = _load_schedule_state()
    fired: list[str] = []

    if _should_fire_weekly(cfg, now, state):
        if _run_scheduled_review(cfg, "weekly"):
            state["lastWeekly"] = now.strftime("%Y-%W")
            fired.append("weekly")

    if _should_fire_daily(cfg, now, state):
        if _run_scheduled_review(cfg, "daily"):
            state["lastDaily"] = now.strftime("%Y-%m-%d")
            fired.append("daily")

    if fired:
        _save_schedule_state(state)
    return fired
