"""Local MCP server for Claude Desktop, Cursor, and Codex CLI.

Exposes Focus Guardian tools over stdio — no LLM API key required.
The host app (Claude, Cursor, Codex) provides the model; this server
only reads/writes local focus state and runs rule-based drift/review.
"""

from __future__ import annotations

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
        "Tools for the user's current focus (day/week/month), drift detection "
        "against that focus using Familiar screen context, session reviews, "
        "and alert snooze. All data stays local — no API keys."
    ),
)


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
    return _handle_set_focus(text, args, cfg)


@mcp.tool()
def clear_focus(cadence: str = "day") -> str:
    """Remove focus for a cadence: day, week, or month."""
    cfg = load_config()
    return _handle_clear_focus("", {"cadence": cadence.lower()}, cfg)


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
    """Session review over recent work blocks (Familiar timeline + rule-based synthesis)."""
    return _handle_review(load_config())


@mcp.tool()
def get_drift_status() -> str:
    """Live drift check — are you off your stated focus right now?"""
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
