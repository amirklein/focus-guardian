"""Background monitor process."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

from focus_guardian.analyzer import analyze
from focus_guardian.notify import maybe_notify
from focus_guardian.paths import load_config, last_report_path, log_path, monitor_pid_path


def run_once() -> dict:
    cfg = load_config()
    if not cfg.get("enabled", True):
        return {"enabled": False}
    mode = cfg.get("interventionMode", "proactive")
    if mode in ("on_demand", "manual", "proactive"):
        if mode == "proactive":
            from focus_guardian.guardian import evaluate_and_chime

            a = evaluate_and_chime(cfg)
            return a.to_dict()
        return {"enabled": True, "interventionMode": mode, "skipped": f"{mode} — use fgr guardian or fgr review"}
    from focus_guardian.review import review_session

    review = review_session(cfg)
    out = review.to_dict()
    last_report_path().write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    from focus_guardian.analyzer import Report, Finding

    report = Report(
        checked_at=review.checked_at,
        window_minutes=int(review.lookback_hours * 60),
        capture_count=len(review.work_blocks),
        goal=review.goal,
        on_track_ratio=0.0,
        activity_mix={},
        findings=review.findings,
        summary=review.summary,
        should_notify=review.should_notify,
    )
    maybe_notify(report, cfg)
    return out


def run_once_snapshot() -> dict:
    """Legacy short-window snapshot (rarely used)."""
    cfg = load_config()
    if not cfg.get("enabled", True):
        return {"enabled": False}
    report = analyze(cfg)
    out = report.to_dict()
    last_report_path().write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    maybe_notify(report, cfg)
    return out


def _monitor_loop(interval_minutes: int) -> None:
    while True:
        try:
            run_once()
        except Exception as e:
            with log_path().open("a", encoding="utf-8") as f:
                f.write(f"ERROR {time.strftime('%Y-%m-%dT%H:%M:%S')} {e}\n")
        time.sleep(max(1, interval_minutes) * 60)


def start_monitor(interval_minutes: int | None = None, foreground: bool = False) -> int:
    cfg = load_config()
    mode = cfg.get("interventionMode", "proactive")
    if mode == "proactive":
        from focus_guardian.guardian import start_guardian

        print("Note: fgr watch is an alias for fgr guardian in proactive mode.")
        return start_guardian(foreground=foreground)

    interval = interval_minutes or int(cfg.get("watchIntervalMinutes", 0))
    if interval <= 0:
        print(
            "Background watch is off. Use: fgr guardian start | fgr review | fgr coach"
        )
        return 0
    if interval < 30:
        print(f"Warning: interval {interval}m is aggressive. Recommend >= 30 for watch mode.")

    pid_file = monitor_pid_path()
    if pid_file.exists():
        try:
            old = int(pid_file.read_text().strip())
            os.kill(old, 0)
            print(f"Monitor already running (pid {old}).")
            return old
        except (OSError, ValueError):
            pid_file.unlink(missing_ok=True)

    if foreground:
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        run_once()
        print(f"Monitor foreground, interval {interval}m (Ctrl+C to stop).")
        try:
            while True:
                time.sleep(interval * 60)
                run_once()
        except KeyboardInterrupt:
            pid_file.unlink(missing_ok=True)
            return os.getpid()

    proc = subprocess.Popen(
        [sys.executable, "-m", "focus_guardian.monitor", "worker", str(interval)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    run_once()
    print(f"Focus Guardian watch started (pid {proc.pid}), every {interval} minutes.")
    return proc.pid


def stop_monitor() -> None:
    from focus_guardian.guardian import stop_guardian
    from focus_guardian.paths import guardian_pid_path

    if guardian_pid_path().exists():
        stop_guardian()

    pid_file = monitor_pid_path()
    if not pid_file.exists():
        print("No monitor running.")
        return
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Stopped monitor (pid {pid}).")
    except (OSError, ValueError):
        print("Monitor not running.")
    pid_file.unlink(missing_ok=True)


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "worker":
        interval = int(sys.argv[2])
        pid_file = monitor_pid_path()
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        _monitor_loop(interval)
    else:
        print("Internal worker entrypoint.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
