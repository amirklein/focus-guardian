"""Proactive event-driven guardian — watches Familiar for drift."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from focus_guardian.clipboard_intel import proactive_cfg
from focus_guardian.coach import coach_drift_nudge
from focus_guardian.drift import DriftAssessment, evaluate_drift
from focus_guardian.familiar import stills_root
from focus_guardian.focus import with_resolved_focus
from focus_guardian.notify import notify_drift_chime
from focus_guardian.review_scheduler import maybe_run_scheduled_reviews
from focus_guardian.paths import (
    guardian_pid_path,
    last_report_path,
    load_config,
    log_path,
)


def _latest_familiar_mtime(root: Path) -> float:
    latest = 0.0
    if not root.is_dir():
        return latest
    for session in root.iterdir():
        if not session.is_dir():
            continue
        for path in session.iterdir():
            if path.suffix == ".md" or path.name.endswith(".clipboard.txt"):
                try:
                    latest = max(latest, path.stat().st_mtime)
                except OSError:
                    pass
    return latest


def evaluate_and_chime(cfg: dict) -> DriftAssessment:
    cfg = with_resolved_focus(cfg)
    assessment = evaluate_drift(cfg)
    out = assessment.to_dict()
    out["guardian"] = True
    last_report_path().write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    if assessment.should_chime:
        nudge = coach_drift_nudge(assessment, cfg)
        notify_drift_chime(assessment, nudge, cfg)
    return assessment


def _guardian_loop() -> None:
    cfg = load_config()
    p = proactive_cfg(cfg)
    poll = int(p.get("pollSeconds", 90))
    debounce = int(p.get("debounceSeconds", 60))

    root = stills_root(cfg)
    last_mtime = _latest_familiar_mtime(root)
    pending_at: float | None = None

    with log_path().open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} guardian started\n")

    last_schedule_check = 0.0

    while True:
        try:
            cfg = load_config()
            if not cfg.get("enabled", True):
                time.sleep(poll)
                continue
            mode = cfg.get("interventionMode", "proactive")
            if mode in ("on_demand", "manual"):
                time.sleep(poll)
                continue

            root = stills_root(cfg)
            p = proactive_cfg(cfg)
            poll = int(p.get("pollSeconds", 90))
            debounce = int(p.get("debounceSeconds", 60))

            now = time.time()
            if now - last_schedule_check >= 300:
                maybe_run_scheduled_reviews(cfg)
                last_schedule_check = now

            mtime = _latest_familiar_mtime(root)

            if mtime > last_mtime:
                last_mtime = mtime
                pending_at = now

            if pending_at is not None and (now - pending_at) >= debounce:
                evaluate_and_chime(cfg)
                pending_at = None
            elif pending_at is None and mtime > 0:
                # Fallback: periodic evaluation even without new files (slow path)
                pass

        except Exception as e:
            with log_path().open("a", encoding="utf-8") as f:
                f.write(f"ERROR {datetime.now().isoformat(timespec='seconds')} {e}\n")

        time.sleep(poll)


def start_guardian(foreground: bool = False) -> int:
    cfg = load_config()
    mode = cfg.get("interventionMode", "proactive")
    if mode in ("on_demand", "manual"):
        print(
            f"Guardian needs proactive mode (current: {mode}). "
            'Set interventionMode to "proactive" in config.'
        )
        return 1

    pid_file = guardian_pid_path()
    if pid_file.exists():
        try:
            old = int(pid_file.read_text().strip())
            os.kill(old, 0)
            print(f"Guardian already running (pid {old}).")
            return old
        except (OSError, ValueError):
            pid_file.unlink(missing_ok=True)

    if foreground:
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        print("Focus Guardian proactive daemon (foreground, Ctrl+C to stop).")
        try:
            _guardian_loop()
        except KeyboardInterrupt:
            pid_file.unlink(missing_ok=True)
            return os.getpid()

    proc = subprocess.Popen(
        [sys.executable, "-m", "focus_guardian.guardian", "worker"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    print(f"Focus Guardian guardian started (pid {proc.pid}).")
    return proc.pid


def stop_guardian() -> None:
    pid_file = guardian_pid_path()
    if not pid_file.exists():
        print("No guardian running.")
        return
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Stopped guardian (pid {pid}).")
    except (OSError, ValueError):
        print("Guardian not running.")
    pid_file.unlink(missing_ok=True)


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "worker":
        guardian_pid_path().write_text(str(os.getpid()), encoding="utf-8")
        _guardian_loop()
    else:
        print("Internal worker entrypoint.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
