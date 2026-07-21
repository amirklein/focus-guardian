"""Resolve config and state paths (portable across machines)."""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_DIR_NAME = ".focus-guardian"


def app_state_dir() -> Path:
    p = Path.home() / APP_DIR_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    env = os.environ.get("FOCUS_GUARDIAN_CONFIG")
    if env:
        return Path(env).expanduser()
    return app_state_dir() / "config.json"


def example_config_path() -> Path:
    repo = Path(__file__).resolve().parent.parent
    return repo / "config.example.json"


def ensure_config() -> Path:
    p = config_path()
    if not p.exists():
        ex = example_config_path()
        if ex.exists():
            p.write_text(ex.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            p.write_text("{}", encoding="utf-8")
    return p


def load_config() -> dict:
    p = ensure_config()
    return json.loads(p.read_text(encoding="utf-8"))


def save_config(cfg: dict) -> None:
    from focus_guardian.focus import prune_stack, sync_legacy_goal_fields, write_focus_markdown

    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    focus = dict(cfg.get("focus") or {})
    focus["stack"] = prune_stack(list(focus.get("stack") or []))
    cfg = {**cfg, "focus": focus}
    cfg = sync_legacy_goal_fields(cfg)
    p.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    write_focus_markdown(cfg)


def state_dir() -> Path:
    p = app_state_dir() / "state"
    p.mkdir(parents=True, exist_ok=True)
    return p


def last_report_path() -> Path:
    return state_dir() / "last_report.json"


def last_notify_path() -> Path:
    return state_dir() / "last_notify.txt"


def monitor_pid_path() -> Path:
    return state_dir() / "monitor.pid"


def guardian_pid_path() -> Path:
    return state_dir() / "guardian.pid"


def slack_bot_pid_path() -> Path:
    return state_dir() / "slack_bot.pid"


def log_path() -> Path:
    return state_dir() / "check.log"


def snooze_until_path() -> Path:
    return state_dir() / "snooze_until.txt"


def focus_markdown_path() -> Path:
    return state_dir() / "focus.md"


def slack_pid_path() -> Path:
    return state_dir() / "slack.pid"
