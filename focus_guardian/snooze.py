"""Alert snooze — pause proactive Slack notifications until a time."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from focus_guardian.paths import snooze_until_path


def _read_until() -> datetime | None:
    p = snooze_until_path()
    if not p.exists():
        return None
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    try:
        ts = float(raw)
        return datetime.fromtimestamp(ts)
    except ValueError:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None


def is_snoozed(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    until = _read_until()
    if until is None:
        return False
    if until <= now:
        clear_snooze()
        return False
    return True


def set_snooze_until(dt: datetime) -> None:
    snooze_until_path().write_text(str(int(dt.timestamp())), encoding="utf-8")


def clear_snooze() -> None:
    p = snooze_until_path()
    if p.exists():
        p.unlink()


def format_snooze_status(now: datetime | None = None) -> str:
    now = now or datetime.now()
    until = _read_until()
    if until is None or until <= now:
        return "Alerts are *on* — you'll get drift and review notifications."
    return f"Alerts snoozed until *{until.strftime('%a %H:%M')}*."


def _parse_time_today(hour: int, minute: int, now: datetime) -> datetime:
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def parse_snooze_duration(text: str, now: datetime | None = None) -> datetime | None:
    """Parse natural-language snooze. Returns None if not a snooze phrase."""
    now = now or datetime.now()
    lower = text.lower().strip()

    if re.search(r"\b(resume|unpause|turn on|enable)\s+(alerts?|notifications?)\b", lower):
        return None  # caller should clear

    if re.search(r"\b(resume|unpause|wake)\b.*\b(alerts?|notifications?)\b", lower):
        return None

    # "until 3pm", "until 3:30 pm", "until 15:00"
    m = re.search(
        r"\buntil\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
        lower,
    )
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        elif ampm is None and hour <= 23 and hour > 12:
            pass
        elif ampm is None and hour <= 12 and hour >= 1:
            # bare hour before noon-ish: assume pm if already past that hour today
            trial = _parse_time_today(hour if hour > 12 else hour + 12, minute, now)
            if trial - now < timedelta(hours=12):
                return trial
            return _parse_time_today(hour + (12 if hour < 8 else 0), minute, now)
        return _parse_time_today(hour, minute, now)

    # "2 hours", "for 30 minutes", "snooze 1h"
    m = re.search(
        r"(?:snooze|pause|mute|silence).*?(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m)\b",
        lower,
    )
    if not m:
        m = re.search(r"\b(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m)\b", lower)
    if m:
        n = int(m.group(1))
        unit = m.group(2)[0]
        if unit == "h":
            return now + timedelta(hours=n)
        return now + timedelta(minutes=n)

    if re.search(r"\bsnooze\b|\bpause alerts\b|\bmute alerts\b", lower):
        return now + timedelta(hours=1)

    return None


def is_resume_phrase(text: str) -> bool:
    lower = text.lower()
    return bool(
        re.search(r"\b(resume|unpause|turn on|enable|wake)\b.*\b(alerts?|notifications?)\b", lower)
        or re.search(r"\bresume alerts\b", lower)
    )
