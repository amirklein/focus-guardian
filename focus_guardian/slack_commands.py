"""Slack DM intent detection and handlers."""

from __future__ import annotations

import json
import re
from typing import Any

from focus_guardian.drift import evaluate_drift
from focus_guardian.focus import (
    NO_FOCUS_HINT,
    WEEK_PRESETS,
    add_focus_entry,
    clear_focus_cadence,
    format_focus_status,
    has_active_focus,
    resolve_active_focus,
    with_resolved_focus,
)
from focus_guardian.llm import parse_intent
from focus_guardian.paths import focus_markdown_path, last_report_path, load_config, save_config
from focus_guardian.review import review_session
from focus_guardian.snooze import (
    clear_snooze,
    format_snooze_status,
    is_resume_phrase,
    is_snoozed,
    parse_snooze_duration,
    set_snooze_until,
)

HELP_TEXT = """*Focus Guardian* — talk to me in plain language.

*Focus*
• _This week I'm exploring pricing, competitors, and GTM_
• _What's my focus?_
• _Clear today's focus_

*Check-ins*
• _How did today go?_ — session review
• _Am I drifting?_ — live drift check
• _Status_

*Alerts*
• _Snooze until 3pm_ / _Pause alerts for 2 hours_
• _Resume alerts_

*Week schedule*
• _Set week to sun-thu_

Proactive drift alerts come from `fgr guardian start`. I'm the interactive side (`fgr slack start`)."""


def detect_intent(text: str) -> str:
    """Heuristic intent classification (no LLM)."""
    t = text.strip()
    lower = t.lower()

    if not t:
        return "unknown"
    if re.match(r"^(help|\?|what can you do|commands)\.?$", lower):
        return "help"
    if is_resume_phrase(t):
        return "resume"
    if re.search(r"\b(snooze|pause alerts|mute alerts|silence alerts)\b", lower):
        return "snooze"
    if re.search(r"\b(clear|remove|delete)\b.*\b(focus|goal)\b", lower):
        return "clear_focus"
    if re.search(r"\b(week schedule|week boundary|set week)\b", lower) or re.search(
        r"\b(mon-fri|sun-thu|sun-sat|mon-sun)\b", lower
    ):
        return "set_week"
    if re.search(
        r"\b(what('s| is) my focus|show focus|current focus|my focus)\b",
        lower,
    ):
        return "show_focus"
    if re.search(r"\b(how did today|how('s| is) today|review|recap|how did i do)\b", lower):
        return "review"
    if re.search(r"\b(am i drifting|drift check|drifting|off track|on track)\b", lower):
        return "drift"
    if re.search(r"\bstatus\b", lower) and len(lower) < 40:
        return "status"
    if re.search(
        r"\b(this week|this month|today|focus on|set focus|i('m| am) (focusing|working|exploring))\b",
        lower,
    ):
        return "set_focus"
    if re.search(r"\bfocus\b", lower) and len(t) > 12:
        return "set_focus"
    return "unknown"


def _cadence_from_clear(text: str) -> str:
    lower = text.lower()
    for c in ("day", "week", "month"):
        if c in lower:
            return c
    return "day"


def _preset_from_text(text: str) -> str | None:
    lower = text.lower()
    for preset in WEEK_PRESETS:
        if preset in lower:
            return preset
    return None


def _build_context(cfg: dict) -> dict[str, Any]:
    resolved = resolve_active_focus(cfg)
    ctx: dict[str, Any] = {
        "active_focus": {
            "text": resolved.text,
            "cadence": resolved.cadence,
            "cadence_label": resolved.cadence_label,
            "priorities": resolved.priorities,
        },
    }
    if last_report_path().exists():
        try:
            data = json.loads(last_report_path().read_text(encoding="utf-8"))
            ctx["last_drift"] = {
                "should_chime": data.get("should_chime"),
                "reason": data.get("reason", data.get("summary", ""))[:200],
            }
        except (json.JSONDecodeError, OSError):
            pass
    return ctx


def _handle_set_focus(text: str, args: dict[str, Any] | None, cfg: dict) -> str:
    body = args.get("text", text) if args else text
    cadence = args.get("cadence") if args else None
    cfg = add_focus_entry(cfg, body, cadence=cadence)
    save_config(cfg)
    return f"Got it.\n\n{format_focus_status(cfg)}\n\n_Saved to {focus_markdown_path()}_"


def _handle_show_focus(cfg: dict) -> str:
    return format_focus_status(cfg)


def _handle_clear_focus(text: str, args: dict[str, Any] | None, cfg: dict) -> str:
    cadence = (args or {}).get("cadence") or _cadence_from_clear(text)
    cfg = clear_focus_cadence(cfg, cadence)
    save_config(cfg)
    return f"Cleared *{cadence}* focus.\n\n{format_focus_status(cfg)}"


def _handle_set_week(text: str, args: dict[str, Any] | None, cfg: dict) -> str:
    preset = (args or {}).get("preset") or _preset_from_text(text)
    if not preset or preset not in WEEK_PRESETS:
        return f"Which week preset? Choose: {', '.join(WEEK_PRESETS)}"
    ws = dict(cfg.get("weekSchedule") or {})
    ws["preset"] = preset
    cfg["weekSchedule"] = ws
    save_config(cfg)
    return f"Week schedule set to *{preset}*."


def _handle_status(cfg: dict) -> str:
    resolved = resolve_active_focus(cfg)
    lines = [
        f"*Focus ({resolved.cadence_label}):* {resolved.text}",
        format_snooze_status(),
    ]
    if last_report_path().exists():
        try:
            data = json.loads(last_report_path().read_text(encoding="utf-8"))
            lines.append(f"*Last check:* {data.get('checked_at', '?')}")
            reason = data.get("reason") or data.get("summary", "")
            if reason:
                lines.append(f"*Signal:* {reason[:200]}")
        except (json.JSONDecodeError, OSError):
            pass
    return "\n".join(lines)


def _handle_review(cfg: dict) -> str:
    if not has_active_focus(cfg):
        return NO_FOCUS_HINT
    review = review_session(cfg)
    out = review.to_dict()
    last_report_path().write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    header = f"*Review — last {review.lookback_hours:.0f}h*"
    return f"{header}\n\n{review.narrative[:3800]}"


def _handle_drift(cfg: dict) -> str:
    if not has_active_focus(cfg):
        return NO_FOCUS_HINT
    cfg = with_resolved_focus(cfg)
    assessment = evaluate_drift(cfg)
    out = assessment.to_dict()
    last_report_path().write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    resolved = resolve_active_focus(cfg)

    if assessment.should_chime:
        lines = [f"You're drifting from *{resolved.text[:200]}* — {assessment.evidence[:300]}"]
    else:
        lines = [f"Looking good — no real drift from *{resolved.text[:200]}* right now."]
    if assessment.suggested_nudge:
        lines.append(assessment.suggested_nudge[:300])
    return "\n\n".join(lines)


def _handle_snooze(text: str, args: dict[str, Any] | None) -> str:
    duration = (args or {}).get("duration", text)
    until = parse_snooze_duration(duration)
    if until is None:
        return "Try: _snooze until 3pm_, _pause alerts for 2 hours_, or _resume alerts_."
    set_snooze_until(until)
    return f"Alerts paused until *{until.strftime('%a %H:%M')}*."


def _handle_resume() -> str:
    clear_snooze()
    return "Alerts resumed. You'll get drift and review notifications again."


def _dispatch(action: str, text: str, args: dict[str, Any], cfg: dict) -> str:
    if action == "help":
        return HELP_TEXT
    if action == "set_focus":
        return _handle_set_focus(text, args, cfg)
    if action == "show_focus":
        return _handle_show_focus(cfg)
    if action == "clear_focus":
        return _handle_clear_focus(text, args, cfg)
    if action == "set_week":
        return _handle_set_week(text, args, cfg)
    if action == "status":
        return _handle_status(cfg)
    if action == "review":
        return _handle_review(cfg)
    if action == "drift":
        return _handle_drift(cfg)
    if action == "snooze":
        return _handle_snooze(text, args)
    if action == "resume":
        return _handle_resume()
    return (
        "I'm not sure what you mean. Say *help* for examples, or try:\n"
        "• _What's my focus?_\n"
        "• _This week: pricing and GTM_\n"
        "• _How did today go?_"
    )


def handle_message(text: str, user_id: str) -> str:
    """Process inbound Slack DM text; return reply markdown."""
    _ = user_id  # authorized in slack_bot before routing
    cfg = load_config()
    stripped = text.strip()

    llm_result = parse_intent(stripped, _build_context(cfg), cfg)
    if llm_result and llm_result.get("action"):
        action = llm_result["action"]
        args = llm_result.get("args") or {}
    else:
        action = detect_intent(stripped)
        args = {}

    if action == "unknown" and is_resume_phrase(stripped):
        action = "resume"

    return _dispatch(action, stripped, args, cfg)


def welcome_message() -> str:
    cfg = load_config()
    resolved = resolve_active_focus(cfg)
    lines = [
        "Focus Guardian is listening.",
        "",
    ]
    if resolved.text and resolved.cadence != "legacy":
        lines.append(f"*Current focus ({resolved.cadence_label}):* {resolved.text[:200]}")
    elif resolved.text:
        lines.append(f"*Current goal:* {resolved.text[:200]}")
    else:
        lines.append("_No focus set yet — tell me what you're working on._")
    lines.append("")
    lines.append(format_snooze_status())
    lines.append("")
    lines.append("Examples: _What's my focus?_ · _How did today go?_ · _Snooze until 3pm_")
    lines.append("Say *help* for the full list.")
    return "\n".join(lines)
