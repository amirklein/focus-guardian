"""Slack outbound — DM via Bot Token (no macOS fallback)."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from typing import Any


def _ssl_context() -> ssl.SSLContext:
    """Use certifi CA bundle (fixes Homebrew Python SSL on macOS)."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class SlackError(RuntimeError):
    pass


def _token(cfg: dict | None = None) -> str:
    tok = os.environ.get("SLACK_BOT_TOKEN")
    if not tok and cfg:
        tok = (cfg.get("notifications") or {}).get("slack", {}).get("botToken")
    if not tok:
        raise SlackError(
            "SLACK_BOT_TOKEN not set. Create a Slack app with chat:write + im:write."
        )
    return tok


def app_token(cfg: dict | None = None) -> str:
    tok = os.environ.get("SLACK_APP_TOKEN")
    if not tok and cfg:
        tok = (cfg.get("notifications") or {}).get("slack", {}).get("appToken")
    if not tok:
        raise SlackError(
            "SLACK_APP_TOKEN not set. Enable Socket Mode and create an app-level token "
            "with connections:write."
        )
    return tok


def _user_id(cfg: dict) -> str:
    uid = os.environ.get("SLACK_USER_ID")
    if not uid:
        uid = (cfg.get("notifications") or {}).get("slack", {}).get("userId")
    if not uid:
        raise SlackError(
            "SLACK_USER_ID not set. DM yourself once or set notifications.slack.userId."
        )
    return uid


def _api(method: str, payload: dict, token: str) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SlackError(f"Slack HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}") from e
    except urllib.error.URLError as e:
        raise SlackError(f"Slack network error: {e}") from e

    if not data.get("ok"):
        raise SlackError(data.get("error", "unknown Slack API error"))
    return data


_dm_cache: dict[str, str] = {}


def open_dm_channel(user_id: str, token: str) -> str:
    if user_id in _dm_cache:
        return _dm_cache[user_id]
    data = _api("conversations.open", {"users": user_id}, token)
    ch = data["channel"]["id"]
    _dm_cache[user_id] = ch
    return ch


def post_message(
    text: str,
    cfg: dict,
    *,
    blocks: list[dict[str, Any]] | None = None,
    thread_ts: str | None = None,
) -> bool:
    token = _token(cfg)
    user = _user_id(cfg)
    channel = open_dm_channel(user, token)
    payload: dict[str, Any] = {"channel": channel, "text": text[:4000]}
    if blocks:
        payload["blocks"] = blocks
    if thread_ts:
        payload["thread_ts"] = thread_ts
    _api("chat.postMessage", payload, token)
    return True


def post_to_channel(
    channel_id: str,
    text: str,
    cfg: dict | None = None,
    *,
    thread_ts: str | None = None,
) -> bool:
    """Post a message to a channel (e.g. DM channel_id from inbound events)."""
    token = _token(cfg)
    payload: dict[str, Any] = {"channel": channel_id, "text": text[:4000]}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    _api("chat.postMessage", payload, token)
    return True


def format_drift_message(
    *,
    cadence_label: str,
    focus_text: str,
    wispr_excerpt: str,
    reason: str,
    nudge: str,
    expires_at: str | None = None,
) -> str:
    lines = [
        "*Focus Guardian — drift*",
        "",
        f"*Cadence:* {cadence_label}",
        f"*Focus:* {focus_text[:300]}",
    ]
    if expires_at:
        lines.append(f"*Expires:* {expires_at}")
    if wispr_excerpt:
        lines.append(f"\n_Wispr:_ {wispr_excerpt[:400]}")
    lines.append(f"\n*Signal:* {reason[:300]}")
    lines.append(f"*Nudge:* {nudge[:400]}")
    return "\n".join(lines)


def format_review_message(
    *,
    title: str,
    cadence_label: str,
    focus_text: str,
    narrative: str,
    summary: str,
) -> str:
    body = narrative if narrative else summary
    chunks = [
        f"*Focus Guardian — {title}*",
        "",
        f"*Focus ({cadence_label}):* {focus_text[:200]}",
        "",
        body[:3500],
    ]
    return "\n".join(chunks)
