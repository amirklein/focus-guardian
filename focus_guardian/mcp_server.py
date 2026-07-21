"""Local MCP server for Claude Desktop, Cursor, and Codex CLI.

Exposes Focus Guardian tools over stdio — no LLM API key required.
The host app (Claude, Cursor, Codex) provides the model; this server
only reads/writes local focus state and runs rule-based drift/review.
"""

from __future__ import annotations

from focus_guardian.coach_context import (
    clear_pending_alert,
    format_context_for_host,
    load_live_context,
    refresh_live_context,
)
from focus_guardian.paths import load_config
from focus_guardian.slack_commands import (
    _handle_clear_focus,
    _handle_drift,
    _handle_resume,
    _handle_review,
    _handle_set_focus,
    _handle_set_week,
    _handle_show_focus,
    _handle_snooze,
    _handle_status,
)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "MCP support requires the optional dependency. Install with:\n"
        '  pip install -e ".[mcp]"'
    ) from exc

mcp = FastMCP(
    "Focus Guardian",
    instructions=(
        "You are the user's focus coach. Use get_live_context or catch_me_up to "
        "understand what Familiar saw on their screen, correlate it with their "
        "stated focus, and respond in warm plain language. Use set_focus when they "
        "want to change priorities. Use explain_last_alert when they ask why Slack "
        "pinged them. Never mention internal drift codes or technical labels."
    ),
)


@mcp.tool()
def get_live_context() -> str:
    """Full live dossier: focus, Familiar activity story, drift state, work blocks."""
    cfg = load_config()
    ctx = refresh_live_context(cfg)
    return format_context_for_host(ctx)


@mcp.tool()
def explain_last_alert() -> str:
    """Why Slack sent a drift ping, plus context since the alert."""
    data = load_live_context()
    cfg = load_config()
    if not data:
        ctx = refresh_live_context(cfg)
        return format_context_for_host(ctx)

    parts = []
    if data.get("pending_alert"):
        parts.append(
            f"Slack alert at {data.get('last_alert_at', '?')}: "
            f"{data.get('last_alert_reason') or data.get('drift_reason', 'drift detected')}"
        )
    else:
        parts.append("No pending Slack alert — here's your current context:")
    parts.append("")
    parts.append(format_context_for_host(data))
    clear_pending_alert()
    return "\n".join(parts)


@mcp.tool()
def catch_me_up() -> str:
    """Main coaching entry point: live context plus last 6h work blocks."""
    clear_pending_alert()
    return get_live_context()


@mcp.tool()
def get_focus() -> str:
    """Return the user's active focus stack (day, week, month) and week schedule."""
    return _handle_show_focus(load_config())


@mcp.tool()
def set_focus(text: str, cadence: str | None = None) -> str:
    """Set or update focus. cadence is day, week, or month (inferred from text if omitted)."""
    cfg = load_config()
    args = {"text": text}
    if cadence:
        args["cadence"] = cadence.lower()
    result = _handle_set_focus(text, args, cfg)
    refresh_live_context(load_config())
    return result


@mcp.tool()
def clear_focus(cadence: str = "day") -> str:
    """Remove focus for a cadence: day, week, or month."""
    cfg = load_config()
    result = _handle_clear_focus("", {"cadence": cadence.lower()}, cfg)
    refresh_live_context(load_config())
    return result


@mcp.tool()
def set_week_schedule(preset: str) -> str:
    """Set week boundary preset: mon-fri, sun-thu, sun-sat, or mon-sun."""
    cfg = load_config()
    return _handle_set_week("", {"preset": preset.lower()}, cfg)


@mcp.tool()
def get_status() -> str:
    """Quick snapshot: active focus, snooze state, and last drift check signal."""
    return _handle_status(load_config())


@mcp.tool()
def get_review() -> str:
    """Session review snapshot (prefer catch_me_up for full host-model synthesis)."""
    return _handle_review(load_config())


@mcp.tool()
def get_drift_status() -> str:
    """Live drift check snapshot (prefer catch_me_up for full coaching read)."""
    return _handle_drift(load_config())


@mcp.tool()
def snooze_alerts(duration: str) -> str:
    """Pause proactive Slack alerts. Examples: 'until 3pm', '2 hours', '30 minutes'."""
    return _handle_snooze(duration, {"duration": duration})


@mcp.tool()
def resume_alerts() -> str:
    """Resume proactive Slack drift and review notifications."""
    return _handle_resume()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
