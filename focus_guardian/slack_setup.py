"""Validate Slack configuration before starting daemons."""

from __future__ import annotations

import os

from focus_guardian.paths import load_config
from focus_guardian.slack_client import SlackError, _api, _token, app_token


def _has_bot_token(cfg: dict) -> bool:
    return bool(os.environ.get("SLACK_BOT_TOKEN") or (cfg.get("notifications") or {}).get("slack", {}).get("botToken"))


def _has_user_id(cfg: dict) -> bool:
    return bool(os.environ.get("SLACK_USER_ID") or (cfg.get("notifications") or {}).get("slack", {}).get("userId"))


def _has_app_token(cfg: dict) -> bool:
    return bool(os.environ.get("SLACK_APP_TOKEN") or (cfg.get("notifications") or {}).get("slack", {}).get("appToken"))


def check_slack_setup(*, interactive: bool = False) -> tuple[list[str], list[str]]:
    """Return (ok_messages, issues). interactive=True requires Socket Mode token."""
    cfg = load_config()
    ok: list[str] = []
    issues: list[str] = []

    if _has_bot_token(cfg):
        ok.append("SLACK_BOT_TOKEN set")
    else:
        issues.append("Missing SLACK_BOT_TOKEN (Bot User OAuth Token, xoxb-...)")

    if _has_user_id(cfg):
        ok.append("SLACK_USER_ID set")
    else:
        issues.append("Missing SLACK_USER_ID (Profile → Copy member ID)")

    if interactive:
        if _has_app_token(cfg):
            ok.append("SLACK_APP_TOKEN set")
        else:
            issues.append(
                "Missing SLACK_APP_TOKEN — enable Socket Mode in api.slack.com/apps, "
                "create app token with connections:write"
            )

    if _has_bot_token(cfg):
        try:
            data = _api("auth.test", {}, _token(cfg))
            ok.append(f"Bot connected as {data.get('user', 'bot')}")
        except SlackError as e:
            issues.append(f"auth.test failed: {e}")

    return ok, issues


def print_slack_check(*, interactive: bool = False) -> int:
    ok, issues = check_slack_setup(interactive=interactive)
    print("Slack setup check")
    print("─" * 40)
    for line in ok:
        print(f"  OK  {line}")
    for line in issues:
        print(f"  !!  {line}")
    print()
    if interactive:
        print("Slack app (for typing in DM): App Home → Messages tab ON;")
        print("  Event Subscriptions → message.im; reinstall app if prompted.")
        print("  Docs: docs/SLACK.md")
    if issues:
        return 1
    print("Ready.")
    return 0
