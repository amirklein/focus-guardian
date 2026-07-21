"""Slack Socket Mode listener — inbound DMs to Focus Guardian."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime

from focus_guardian.paths import load_config, log_path, slack_pid_path
from focus_guardian.slack_client import (
    SlackError,
    app_token,
    post_to_channel,
    ssl_context,
    _token,
)
from focus_guardian.slack_commands import handle_message, welcome_message


def _authorized_user(user_id: str, cfg: dict) -> bool:
    expected = os.environ.get("SLACK_USER_ID")
    if not expected:
        expected = (cfg.get("notifications") or {}).get("slack", {}).get("userId")
    if not expected:
        return False
    return user_id == expected


def _log(msg: str) -> None:
    with log_path().open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} slack {msg}\n")


def _run_listener() -> None:
    from slack_sdk.socket_mode import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.socket_mode.response import SocketModeResponse
    from slack_sdk.web import WebClient

    cfg = load_config()
    bot = _token(cfg)
    app_tok = app_token(cfg)
    web = WebClient(token=bot, ssl=ssl_context())
    client = SocketModeClient(app_token=app_tok, web_client=web)

    def _send_welcome() -> None:
        try:
            uid = os.environ.get("SLACK_USER_ID") or (
                (cfg.get("notifications") or {}).get("slack", {}).get("userId")
            )
            if uid:
                from focus_guardian.slack_client import open_dm_channel

                ch = open_dm_channel(uid, bot)
                post_to_channel(ch, welcome_message(), cfg)
        except SlackError as e:
            _log(f"welcome error: {e}")

    def process(client: SocketModeClient, req: SocketModeRequest) -> None:
        if req.type != "events_api":
            client.send_socket_mode_response(
                SocketModeResponse(envelope_id=req.envelope_id)
            )
            return

        payload = req.payload
        event = payload.get("event", {})
        client.send_socket_mode_response(
            SocketModeResponse(envelope_id=req.envelope_id)
        )

        if event.get("type") != "message":
            return
        if event.get("subtype") in ("bot_message", "message_changed", "message_deleted"):
            return
        if event.get("bot_id"):
            return

        user_id = event.get("user")
        if not user_id or not _authorized_user(user_id, load_config()):
            _log(f"ignored message from {user_id or 'unknown'}")
            return

        text = (event.get("text") or "").strip()
        if not text:
            return

        channel = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")

        try:
            reply = handle_message(text, user_id)
            post_to_channel(channel, reply, load_config(), thread_ts=thread_ts)
        except Exception as e:
            _log(f"handler error: {e}")
            try:
                post_to_channel(
                    channel,
                    "Something went wrong processing that. Try *help* or check `fgr slack` logs.",
                    load_config(),
                    thread_ts=thread_ts,
                )
            except SlackError:
                pass

    client.socket_mode_request_listeners.append(process)
    _log("listener started")
    _send_welcome()
    client.connect()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()
        slack_pid_path().unlink(missing_ok=True)
        _log("listener stopped")


def start_slack_bot(foreground: bool = False) -> int:
    pid_file = slack_pid_path()
    if pid_file.exists():
        try:
            old = int(pid_file.read_text().strip())
            os.kill(old, 0)
            print(f"Slack bot already running (pid {old}).")
            return old
        except (OSError, ValueError):
            pid_file.unlink(missing_ok=True)

    try:
        load_config()
        _token(load_config())
        app_token(load_config())
    except SlackError as e:
        print(str(e))
        return 1

    if foreground:
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        print("Focus Guardian Slack bot (foreground, Ctrl+C to stop).")
        try:
            _run_listener()
        except KeyboardInterrupt:
            pid_file.unlink(missing_ok=True)
            return os.getpid()
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


def stop_slack_bot() -> None:
    pid_file = slack_pid_path()
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
        slack_pid_path().write_text(str(os.getpid()), encoding="utf-8")
        _run_listener()
    else:
        print("Internal worker entrypoint.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
