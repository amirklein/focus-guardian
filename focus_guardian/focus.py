"""Dynamic focus stack — day / week / month with user-defined week boundaries."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_TO_WEEKDAY = {n: i for i, n in enumerate(DAY_NAMES)}  # mon=0 .. sun=6

WEEK_PRESETS: dict[str, tuple[str, str]] = {
    "mon-fri": ("mon", "fri"),
    "sun-thu": ("sun", "thu"),
    "sun-sat": ("sun", "sat"),
    "mon-sun": ("mon", "sun"),
}


NO_FOCUS_HINT = (
    "You haven't told me what to focus on yet — try: "
    "\"This week I'm focusing on X\"."
)

_PLACEHOLDER_GOAL_PREFIXES = ("set focus with:",)


@dataclass
class ResolvedFocus:
    text: str
    priorities: list[str]
    avoid: list[str]
    keywords: list[str]
    cadence: str
    cadence_label: str
    expires_at: str | None
    stack_summary: list[str] = field(default_factory=list)


def _parse_day(s: str) -> int:
    key = s.strip().lower()[:3]
    if key not in DAY_TO_WEEKDAY:
        raise ValueError(f"Unknown day: {s!r}. Use mon..sun.")
    return DAY_TO_WEEKDAY[key]


def week_schedule(cfg: dict) -> dict[str, Any]:
    ws = cfg.get("weekSchedule") or {}
    preset = (ws.get("preset") or "mon-fri").lower()
    if preset in WEEK_PRESETS:
        start_name, end_name = WEEK_PRESETS[preset]
    else:
        start_name = (ws.get("startDay") or "mon").lower()[:3]
        end_name = (ws.get("endDay") or "fri").lower()[:3]
    return {
        "preset": preset,
        "startDay": start_name,
        "endDay": end_name,
        "startWeekday": _parse_day(start_name),
        "endWeekday": _parse_day(end_name),
    }


def _end_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=23, minute=59, second=59, microsecond=0)


def _end_of_month(dt: datetime) -> datetime:
    if dt.month == 12:
        nxt = dt.replace(year=dt.year + 1, month=1, day=1)
    else:
        nxt = dt.replace(month=dt.month + 1, day=1)
    return _end_of_day(nxt - timedelta(days=1))



def _days_until_weekday(from_wd: int, to_wd: int) -> int:
    return (to_wd - from_wd) % 7


def expires_for_cadence(cadence: str, cfg: dict, now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    cadence = cadence.lower()
    if cadence == "day":
        return _end_of_day(now)
    if cadence == "month":
        return _end_of_month(now)
    if cadence == "week":
        ws = week_schedule(cfg)
        end = ws["endWeekday"]
        days = _days_until_weekday(now.weekday(), end)
        return _end_of_day(now + timedelta(days=days))
    raise ValueError(f"Unknown cadence: {cadence}. Use day, week, or month.")


def _parse_priorities(text: str) -> list[str]:
    """Extract comma/and-separated priorities from natural language."""
    t = text.strip()
    for prefix in (
        r"this week[,:]?\s*",
        r"this month[,:]?\s*",
        r"today[,:]?\s*",
        r"i(?:'m| am)\s+(?:focusing on|exploring|working on)\s+",
        r"focus(?:ing)? on\s+",
        r"explor(?:e|ing)\s+",
    ):
        t = re.sub(prefix, "", t, flags=re.I)
    t = re.sub(r"\.\s*notify me.*$", "", t, flags=re.I)
    t = re.sub(r"\.\s*alert me.*$", "", t, flags=re.I)
    parts = re.split(r"\s*,\s*|\s+and\s+", t)
    out = [p.strip(" .") for p in parts if p.strip(" .")]
    return out[:12]


def _keywords_from_text(text: str, priorities: list[str]) -> list[str]:
    stop = {
        "today",
        "this",
        "that",
        "with",
        "from",
        "your",
        "need",
        "want",
        "will",
        "have",
        "week",
        "month",
        "focus",
        "exploring",
        "strategy",
        "which",
        "looking",
    }
    words: list[str] = []
    for blob in [text, *priorities]:
        for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", blob.lower()):
            if w not in stop:
                words.append(w)
    return list(dict.fromkeys(words))[:20]


def detect_cadence(text: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit.lower()
    lower = text.lower()
    if re.search(r"\btoday\b|\bthis afternoon\b|\btonight\b", lower):
        return "day"
    if re.search(r"\bthis month\b|\bmonthly\b", lower):
        return "month"
    if re.search(r"\bthis week\b|\bweekly\b", lower):
        return "week"
    return "day"


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat(timespec="seconds")


def _parse_iso(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00").split("+")[0])
    except ValueError:
        return None


def prune_stack(stack: list[dict], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    kept: list[dict] = []
    for entry in stack:
        exp = entry.get("expiresAt")
        if exp:
            dt = _parse_iso(exp)
            if dt and dt < now:
                continue
        kept.append(entry)
    return kept


def add_focus_entry(
    cfg: dict,
    text: str,
    *,
    cadence: str | None = None,
    priorities: list[str] | None = None,
    avoid: list[str] | None = None,
    keywords: list[str] | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now()
    cadence = detect_cadence(text, cadence)
    pri = priorities if priorities is not None else _parse_priorities(text)
    if not pri and text.strip():
        pri = [text.strip()[:200]]
    merged_text = text.strip() if text.strip() else "; ".join(pri)
    kw = keywords if keywords is not None else _keywords_from_text(merged_text, pri)
    exp = expires_for_cadence(cadence, cfg, now)

    entry = {
        "id": f"{cadence}-{_iso(now).replace(':', '').replace('-', '')}",
        "cadence": cadence,
        "text": merged_text,
        "priorities": pri,
        "avoid": avoid or [],
        "keywords": kw,
        "startsAt": _iso(now),
        "expiresAt": _iso(exp),
    }

    focus = dict(cfg.get("focus") or {})
    stack = prune_stack(list(focus.get("stack") or []), now)
    stack = [e for e in stack if e.get("cadence") != cadence]
    stack.append(entry)
    focus["stack"] = stack
    out = {**cfg, "focus": focus}
    return sync_legacy_goal_fields(out)


def sync_legacy_goal_fields(cfg: dict) -> dict:
    """Mirror resolved focus into currentGoal / goalKeywords for existing drift code."""
    resolved = resolve_active_focus(cfg)
    out = {**cfg}
    out["currentGoal"] = resolved.text
    base_kw = [k.lower() for k in cfg.get("goalKeywords", []) if k]
    out["goalKeywords"] = list(dict.fromkeys([*resolved.keywords, *base_kw]))
    return out


def resolve_active_focus(cfg: dict, now: datetime | None = None) -> ResolvedFocus:
    now = now or datetime.now()
    focus = cfg.get("focus") or {}
    stack = prune_stack(list(focus.get("stack") or []), now)

    by_cadence: dict[str, dict] = {}
    for entry in stack:
        c = entry.get("cadence", "day")
        by_cadence[c] = entry

    active: dict | None = None
    cadence = "custom"
    for c in ("day", "week", "month"):
        if c in by_cadence:
            active = by_cadence[c]
            cadence = c
            break

    if not active:
        legacy = cfg.get("currentGoal", "") or "(no focus set)"
        return ResolvedFocus(
            text=legacy,
            priorities=[legacy] if legacy else [],
            avoid=list(cfg.get("focusAvoid", []) or []),
            keywords=[k.lower() for k in cfg.get("goalKeywords", [])],
            cadence="legacy",
            cadence_label="Current goal",
            expires_at=None,
            stack_summary=[],
        )

    pri = list(active.get("priorities") or [])
    text = active.get("text") or "; ".join(pri)
    avoid = list(active.get("avoid") or [])
    kw = list(active.get("keywords") or [])
    for p in pri:
        kw.extend(_keywords_from_text(p, []))
    kw = list(dict.fromkeys(kw))

    labels = {
        "day": "Today",
        "week": f"This week ({week_schedule(cfg)['preset']})",
        "month": "This month",
    }
    summary = []
    for c in ("month", "week", "day"):
        if c in by_cadence:
            e = by_cadence[c]
            summary.append(f"{labels.get(c, c)}: {e.get('text', '')[:80]}")

    return ResolvedFocus(
        text=text,
        priorities=pri,
        avoid=avoid,
        keywords=kw,
        cadence=cadence,
        cadence_label=labels.get(cadence, cadence),
        expires_at=active.get("expiresAt"),
        stack_summary=summary,
    )


def has_active_focus(cfg: dict) -> bool:
    """True once the user has set a real focus (via the stack, or a legacy
    ``currentGoal``); False if nothing has ever been set — i.e. still on the
    config template's placeholder text."""
    resolved = resolve_active_focus(cfg)
    if resolved.cadence != "legacy":
        return True
    text = (resolved.text or "").strip()
    if not text or text == "(no focus set)":
        return False
    return not text.lower().startswith(_PLACEHOLDER_GOAL_PREFIXES)


def with_resolved_focus(cfg: dict) -> dict:
    """Return config copy with legacy goal fields synced from focus stack."""
    pruned = deepcopy(cfg)
    focus = dict(pruned.get("focus") or {})
    focus["stack"] = prune_stack(list(focus.get("stack") or []))
    pruned["focus"] = focus
    out = sync_legacy_goal_fields(pruned)
    resolved = resolve_active_focus(out)
    if resolved.avoid:
        patterns = list(out.get("distractionTitlePatterns") or [])
        out["distractionTitlePatterns"] = list(
            dict.fromkeys([*patterns, *[a.lower() for a in resolved.avoid]])
        )
    return out


def clear_focus_cadence(cfg: dict, cadence: str) -> dict:
    focus = dict(cfg.get("focus") or {})
    stack = [e for e in focus.get("stack") or [] if e.get("cadence") != cadence.lower()]
    focus["stack"] = stack
    out = {**cfg, "focus": focus}
    return sync_legacy_goal_fields(out)


def format_focus_status(cfg: dict) -> str:
    resolved = resolve_active_focus(cfg)
    ws = week_schedule(cfg)
    lines = [
        "Active focus",
        "─" * 40,
        f"{resolved.cadence_label}: {resolved.text}",
    ]
    if resolved.priorities:
        lines.append(f"Priorities: {', '.join(resolved.priorities)}")
    if resolved.avoid:
        lines.append(f"Avoid: {', '.join(resolved.avoid)}")
    if resolved.expires_at:
        lines.append(f"Expires: {resolved.expires_at}")
    lines.append(f"Week schedule: {ws['preset']} ({ws['startDay']} → {ws['endDay']})")
    stack = (cfg.get("focus") or {}).get("stack") or []
    if len(stack) > 1:
        lines.append("")
        lines.append("Full stack:")
        for e in stack:
            lines.append(f"  • [{e.get('cadence')}] {e.get('text', '')[:70]}")
    return "\n".join(lines)


def write_focus_markdown(cfg: dict) -> Path:
    """Persist the current focus stack as a small markdown file — a dynamic,
    always-current source of truth other tools (or you) can open directly."""
    from focus_guardian.paths import focus_markdown_path

    lines = ["# Focus Guardian — current focus", ""]

    if not has_active_focus(cfg):
        lines.append("_No focus set yet — tell the bot what you're working on, e.g._")
        lines.append("_\"This week I'm focusing on X\"_")
    else:
        resolved = resolve_active_focus(cfg)
        lines.append(f"**{resolved.cadence_label}:** {resolved.text}")
        if resolved.priorities:
            lines.append("")
            lines.append("Priorities:")
            for p in resolved.priorities:
                lines.append(f"- {p}")
        if resolved.avoid:
            lines.append("")
            lines.append(f"Avoid: {', '.join(resolved.avoid)}")
        if resolved.expires_at:
            lines.append("")
            lines.append(f"_Expires: {resolved.expires_at}_")

    ws = week_schedule(cfg)
    lines.append("")
    lines.append(f"Week schedule: {ws['preset']} ({ws['startDay']} → {ws['endDay']})")

    stack = (cfg.get("focus") or {}).get("stack") or []
    if len(stack) > 1:
        lines.append("")
        lines.append("## Full stack")
        for e in stack:
            lines.append(f"- **[{e.get('cadence')}]** {e.get('text', '')}")

    lines.append("")
    lines.append(f"_Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_")

    path = focus_markdown_path()
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
