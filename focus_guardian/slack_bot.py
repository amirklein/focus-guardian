"""Two-way Slack bot for Focus Guardian.

Requires three env vars (from your Slack app config, Socket Mode enabled):
  SLACK_BOT_TOKEN  -> xoxb-... (OAuth & Permissions page)
  SLACK_APP_TOKEN  -> xapp-... (Basic Information > App-Level Tokens, needs connections:write)
  SLACK_USER_ID    -> your own Slack member ID (U0XXXXXXX) so the bot only talks to you

Bot scopes needed: chat:write, im:history, im:write, im:read, users:read
Event subscriptions (Socket Mode): message.im
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime

from focus_guardian import llm
from focus_guardian.analyzer import analyze
from focus_guardian.coach import coach_offline, coach_with_api
from focus_guardian.paths import (
    load_config,
    log_path,
    save_config,
    slack_bot_pid_path,
)
from focus_guardian.review import review_session

COACH_SYSTEM = """You are Focus Guardian, a warm but direct accountability coach chatting with the
user in Slack. You see their current goal and a JSON snapshot of recent drift/activity.
Reply conversationally, under 100 words, like a text from a supportive colleague — not a report.
If they're asking a question, answer it. If they're explaining/justifying an activity, weigh honestly
whether it's actually on-goal before reassuring them. End with one concrete suggestion when relevant."""


def _log(msg: str) -> None:
    with log_path().open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} [slack] {msg}\n")


def _client():
    from slack_sdk import WebClient

    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN not set.")
    return WebClient(token=token)


def _user_id() -> str:
    uid = os.environ.get("SLACK_USER_ID")
    if not uid:
        raise RuntimeError("SLACK_USER_ID not set.")
    return uid


def _dm_channel(client, user_id: str) -> str:
    resp = client.conversations_open(users=[user_id])
    return resp["channel"]["id"]


def send_dm(text: str, cfg: dict | None = None) -> bool:
    """Send a plain DM to the configured user. Used by guardian.py for proactive nudges."""
    try:
        client = _client()
        uid = _user_id()
        channel = _dm_channel(client, uid)
        client.chat_postMessage(channel=channel, text=text)
        return True
    except Exception as e:  # noqa: BLE001 - notification path must never crash the guardian loop
        _log(f"send_dm failed: {e}")
        return False


def _goal_words(text: str) -> list[str]:
    import re

    stop = {"today", "this", "that", "with", "from", "your", "need", "want", "will", "have"}
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text)
    return [w.lower() for w in words if w.lower() not in stop][:12]


def _handle_command(text: str, cfg: dict) -> str:
    stripped = text.strip()
    lower = stripped.lower()

    if lower.startswith("goal"):
        goal_text = stripped[4:].strip(" :-")
        if not goal_text:
            return (
                f"Current goal: {cfg.get('currentGoal', '(not set)')}\n"
                f"Keywords: {', '.join(cfg.get('goalKeywords', []))}\n"
                "To set one: `goal Ship the HiBob demo`"
            )
        cfg["currentGoal"] = goal_text
        cfg["goalKeywords"] = list(dict.fromkeys(_goal_words(goal_text)))
        save_config(cfg)
        return f"Got it. Focus set to: *{goal_text}*\nI'll flag drift against this."

    if lower in ("status", "check", "drift"):
        report = analyze(cfg)
        if not report.findings:
            return f"On track (~{report.on_track_ratio:.0%} aligned) with: {report.goal}"
        f = report.findings[0]
        return f"⚠️ {f.message}\n{f.evidence}"

    if lower in ("review", "recap"):
        review = review_session(cfg)
        return review.narrative

    if lower in ("coach", "help me", "nudge"):
        report = analyze(cfg)
        if llm.active_provider(cfg):
            try:
                return coach_with_api(report, cfg=cfg)
            except RuntimeError:
                pass
        return coach_offline(report)

    return ""  # not a recognized command — treat as free-form chat


def _handle_free_form(text: str, cfg: dict) -> str:
    if llm.active_provider(cfg) is None:
        return (
            "I don't have an AI key configured to chat freely — but you can use "
            "`goal`, `status`, `review`, or `coach` as commands."
        )
    report = analyze(cfg)
    payload = {
        "goal": cfg.get("currentGoal", ""),
        "user_message": text,
        "recent_report": report.to_dict(),
    }
    try:
        return llm.chat(COACH_SYSTEM, json.dumps(payload), max_tokens=250, cfg=cfg)
    except llm.LLMError as e:
        _log(f"free-form chat failed: {e}")
        return "Hit an error reaching the AI just now — try again in a bit."


def _process_message(text: str) -> str:
    cfg = load_config()
    reply = _handle_command(text, cfg)
    if reply:
        return reply
    return _handle_free_form(text, cfg)


def run_bot() -> None:
    """Blocking Socket Mode listener. Run via `fg slack start` (backgrounded) or directly."""
    from slack_sdk.socket_mode import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.socket_mode.response import SocketModeResponse
    from slack_sdk import WebClient

    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    app_token = os.environ.get("SLACK_APP_TOKEN")
    my_user_id = os.environ.get("SLACK_USER_ID")
    if not (bot_token and app_token and my_user_id):
        print(
            "Set SLACK_BOT_TOKEN, SLACK_APP_TOKEN, and SLACK_USER_ID before starting the bot.",
            file=sys.stderr,
        )
        sys.exit(1)

    web_client = WebClient(token=bot_token)
    client = SocketModeClient(app_token=app_token, web_client=web_client)

    def handle(client: SocketModeClient, req: SocketModeRequest) -> None:
        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        if req.type != "events_api":
            return
        event = req.payload.get("event", {})
        if event.get("type") != "message" or event.get("subtype"):
            return
        if event.get("user") != my_user_id:
            return
        text = (event.get("text") or "").strip()
        if not text:
            return
        try:
            reply = _process_message(text)
        except Exception as e:  # noqa: BLE001 - keep the bot alive on any single failure
            _log(f"message handling error: {e}")
            reply = "Something went wrong on my end handling that — logged it."
        if reply:
            web_client.chat_postMessage(channel=event["channel"], text=reply)

    client.socket_mode_request_listeners.append(handle)
    client.connect()
    _log("slack bot connected")
    print("Focus Guardian Slack bot connected. Ctrl+C to stop (or run via `fg slack start`).")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def start_bot(foreground: bool = False) -> int:
    pid_file = slack_bot_pid_path()
    if pid_file.exists():
        try:
            old = int(pid_file.read_text().strip())
            os.kill(old, 0)
            print(f"Slack bot already running (pid {old}).")
            return old
        except (OSError, ValueError):
            pid_file.unlink(missing_ok=True)

    if foreground:
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        try:
            run_bot()
        finally:
            pid_file.unlink(missing_ok=True)
        return os.getpid()

    proc = subprocess.Popen(
        [sys.executable, "-m", "focus_guardian.slack_bot", "worker"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    print(f"Focus Guardian Slack bot started (pid {proc.pid}).")
    return proc.pid


def stop_bot() -> None:
    pid_file = slack_bot_pid_path()
    if not pid_file.exists():
        print("No Slack bot running.")
        return
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Stopped Slack bot (pid {pid}).")
    except (OSError, ValueError):
        print("Slack bot not running.")
    pid_file.unlink(missing_ok=True)


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "worker":
        slack_bot_pid_path().write_text(str(os.getpid()), encoding="utf-8")
        run_bot()
    else:
        print("Internal worker entrypoint.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
