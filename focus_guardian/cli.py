"""CLI: fgr review | coach | goal | profile | watch | status"""

from __future__ import annotations

import argparse
import json
import sys

from focus_guardian import __version__
from focus_guardian.analyzer import Finding, Report, analyze
from focus_guardian.coach import coach_offline, coach_with_api, format_prompt
from focus_guardian.drift import evaluate_drift
from focus_guardian.guardian import evaluate_and_chime, start_guardian, stop_guardian
from focus_guardian.slack_setup import print_slack_check
from focus_guardian.slack_bot import start_slack_bot, stop_slack_bot
from focus_guardian.monitor import run_once, start_monitor, stop_monitor
from focus_guardian.notify import maybe_notify, notify_review
from focus_guardian.paths import (
    config_path,
    ensure_config,
    focus_markdown_path,
    last_report_path,
    load_config,
    save_config,
)
from focus_guardian.drift_config import drift_rules
from focus_guardian.familiar import familiar_settings_path, stills_root as get_stills
from focus_guardian.focus import (
    NO_FOCUS_HINT,
    WEEK_PRESETS,
    add_focus_entry,
    clear_focus_cadence,
    format_focus_status,
    has_active_focus,
    resolve_active_focus,
)
from focus_guardian.profiles import apply_profile, list_profiles
from focus_guardian.review import review_session


def _report_from_saved(data: dict) -> tuple[Report, str | None]:
    narrative = data.get("narrative")
    findings = [Finding(**f) for f in data.get("findings", [])]
    report = Report(
        checked_at=data.get("checked_at", ""),
        window_minutes=int(data.get("window_minutes") or data.get("lookback_hours", 1) * 60),
        capture_count=data.get("capture_count") or len(data.get("work_blocks", [])),
        goal=data.get("goal", ""),
        on_track_ratio=data.get("on_track_ratio", 0.0),
        activity_mix=data.get("activity_mix", {}),
        findings=findings,
        summary=data.get("summary", ""),
        should_notify=data.get("should_notify", False),
    )
    return report, narrative


def cmd_review(args: argparse.Namespace) -> int:
    cfg = load_config()
    if not has_active_focus(cfg):
        print(NO_FOCUS_HINT)
        return 0
    if getattr(args, "api", False):
        cfg = {**cfg, "synthesis": {**cfg.get("synthesis", {}), "useApiForReview": True}}
    review = review_session(cfg)
    out = review.to_dict()
    last_report_path().write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    if args.notify:
        title = "session review" if args.human else "review alert"
        notify_review(
            cfg,
            title=title,
            narrative=review.narrative if args.human else "",
            summary=review.summary,
        )

    if args.human or args.synthesize:
        print(review.narrative)
    else:
        print(json.dumps(out, indent=2))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Short snapshot (legacy). Prefer `fgr review`."""
    cfg = load_config()
    report = analyze(cfg)
    out = report.to_dict()
    last_report_path().write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    if args.notify:
        maybe_notify(report, cfg)
    print(json.dumps(out, indent=2))
    return 0


def cmd_coach(args: argparse.Namespace) -> int:
    cfg = load_config()
    narrative = None

    if args.fresh or not last_report_path().exists():
        review = review_session(cfg)
        out = review.to_dict()
        last_report_path().write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        report, narrative = _report_from_saved(out)
    else:
        data = json.loads(last_report_path().read_text(encoding="utf-8"))
        report, narrative = _report_from_saved(data)
        if not narrative and "work_blocks" not in data:
            review = review_session(cfg)
            out = review.to_dict()
            last_report_path().write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
            report, narrative = _report_from_saved(out)

    if args.print_prompt:
        print(format_prompt(report, narrative))
        return 0

    if args.api:
        try:
            text = coach_with_api(report, cfg=cfg)
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            print("\n--- offline coach ---\n", file=sys.stderr)
            text = coach_offline(report)
    else:
        text = coach_offline(report)
        if narrative and "Next 25 min" not in text:
            text = f"{narrative}\n\n{text}"

    print(text)
    return 0


def _goal_words_from_text(text: str) -> list[str]:
    import re

    stop = {"today", "this", "that", "with", "from", "your", "need", "want", "will", "have"}
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text)
    return [w.lower() for w in words if w.lower() not in stop][:12]


def cmd_goal(args: argparse.Namespace) -> int:
    """Legacy alias for `fgr focus`."""
    if args.hours is not None and not args.words:
        cfg = load_config()
        cfg["lookbackHours"] = args.hours
        save_config(cfg)
        print(f"Review window: {args.hours}h")
        return 0
    focus_args = argparse.Namespace(
        words=args.words,
        cadence=None,
        priorities=args.keywords if args.keywords else None,
        avoid=None,
        week=None,
        clear=None,
    )
    if args.words and args.auto_keywords and not args.keywords:
        focus_args.priorities = None
    return cmd_focus(focus_args)


def cmd_focus(args: argparse.Namespace) -> int:
    cfg = load_config()

    if getattr(args, "week", None):
        ws = dict(cfg.get("weekSchedule") or {})
        preset = args.week.lower()
        if preset not in WEEK_PRESETS:
            print(f"Unknown week preset: {preset}. Choose: {', '.join(WEEK_PRESETS)}")
            return 1
        ws["preset"] = preset
        cfg["weekSchedule"] = ws
        save_config(cfg)
        print(f"Week schedule set to {preset}.")
        return 0

    if getattr(args, "clear", None):
        cfg = clear_focus_cadence(cfg, args.clear)
        save_config(cfg)
        print(f"Cleared {args.clear} focus.")
        print(format_focus_status(cfg))
        return 0

    if not args.words:
        print(format_focus_status(cfg))
        print()
        print("Set focus (natural language):")
        print('  fgr focus "This week explore pricing, competitor analysis, and GTM" --cadence week')
        print('  fgr focus "Today: finish competitor spreadsheet" --cadence day')
        print('  fgr focus --week sun-thu')
        return 0

    text = " ".join(args.words)
    priorities = None
    if getattr(args, "priorities", None):
        priorities = [p.strip() for p in args.priorities.split(",") if p.strip()]
    avoid = None
    if getattr(args, "avoid", None):
        avoid = [a.strip() for a in args.avoid.split(",") if a.strip()]

    cfg = add_focus_entry(
        cfg,
        text,
        cadence=getattr(args, "cadence", None),
        priorities=priorities,
        avoid=avoid,
    )
    save_config(cfg)
    print("Focus updated.")
    print(format_focus_status(cfg))
    print(f"\nSaved to {focus_markdown_path()}")
    return 0


def cmd_paths(_: argparse.Namespace) -> int:
    import json

    cfg = load_config()
    print("Where your data lives")
    print("═" * 50)
    fs = familiar_settings_path()
    if fs.exists():
        data = json.loads(fs.read_text(encoding="utf-8"))
        ctx = data.get("contextFolderPath", "(not set)")
        print(f"\n1. Familiar main folder (you chose this in Familiar):")
        print(f"   {ctx}")
        print(f"   All Familiar data lives under here.")
    else:
        print("\n1. Familiar: not set up on this Mac yet.")
        ctx = None

    try:
        stills = get_stills(cfg)
        print(f"\n2. Screen + Wispr recordings (Focus Guardian reads this):")
        print(f"   {stills}")
    except FileNotFoundError as e:
        print(f"\n2. Stills path: {e}")
        stills = None

    override = cfg.get("familiarStillsPath")
    if override:
        print(f"\n   (Overridden in config to: {override})")

    print(f"\n3. Your goals & drift rules:")
    print(f"   {config_path()}")

    print(f"\n4. Your current focus (auto-updated markdown):")
    print(f"   {focus_markdown_path()}")

    print("\n" + "─" * 50)
    print("To move Familiar data (e.g. iCloud):")
    print("  • In Familiar app → Settings → change the data/context folder")
    print("  • Or copy the whole folder above to iCloud/Drive")
    print("  • On a new Mac: point Familiar to the same folder")
    print("  • Focus Guardian follows automatically (same path).")
    print("\nIf Familiar and Guardian ever disagree, set in config:")
    print('  "familiarStillsPath": "/full/path/to/stills-markdown"')
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    cfg = load_config()
    rules = drift_rules(cfg)
    if args.show_config:
        print(json.dumps({"driftRules": rules, "thresholds": cfg.get("thresholds", {})}, indent=2))
        return 0
    print("What counts as drift (you can edit in config.json → driftRules)")
    print("═" * 50)
    labels = {
        "wisprOffTopic": "Off-topic dictation (Wispr) for ~10+ min",
        "distractionStreak": "LinkedIn, WhatsApp, personal tabs too long",
        "aiLoop": "Claude/Gemini without building",
        "polishSpiral": "Slides/Lovable without code/demo",
        "topicPivot": "Dictation suddenly leaves assignment topic",
        "wisprDistractionSpike": "Off-topic speech while on distraction site",
    }
    for key, desc in labels.items():
        on = "ON " if rules.get(key, True) else "OFF"
        print(f"  [{on}] {desc}")
    off = rules.get("offTopicPhrases") or []
    on_p = rules.get("onTopicPhrases") or []
    if off:
        print(f"\nExtra off-topic phrases: {', '.join(off)}")
    if on_p:
        print(f"Extra on-topic phrases: {', '.join(on_p)}")
    if rules.get("useApiForDrift"):
        print("\nSemantic layer: ON (uses ANTHROPIC_API_KEY for drift judgment)")
    else:
        print("\nSemantic layer: OFF (keyword + tone heuristics)")
        print("  Turn on: driftRules.useApiForDrift + export ANTHROPIC_API_KEY")
    print(f"\nConfig file: {config_path()}")
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    if args.list:
        for name in list_profiles():
            print(name)
        return 0
    cfg = load_config()
    merged = apply_profile(cfg, args.name)
    save_config(merged)
    print(f"Active profile: {args.name}")
    print(f"Goal: {merged.get('currentGoal')}")
    print(f"Mode: {merged.get('interventionMode')}")
    if merged.get("interventionMode") == "proactive":
        print("Run: fgr guardian start")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    cfg = load_config()
    print(f"Focus Guardian v{__version__}")
    print(f"Config: {config_path()}")
    print(f"Profile: {cfg.get('activeProfile', 'custom')}")
    print(f"Intervention: {cfg.get('interventionMode', 'proactive')}")
    p = cfg.get("proactive", {})
    if p:
        print(
            f"Proactive: poll={p.get('pollSeconds', 90)}s, "
            f"drift≥{p.get('driftSustainedMinutes', 10)}m, "
            f"chime cooldown={p.get('chimeCooldownMinutes', 25)}m"
        )
    resolved = resolve_active_focus(cfg)
    print(f"Focus ({resolved.cadence_label}): {resolved.text}")
    print(f"Lookback: {cfg.get('lookbackHours', 6)}h work-block review")
    try:
        print(f"Familiar stills: {get_stills(cfg)}")
    except FileNotFoundError as e:
        print(f"Familiar: {e}")
    if last_report_path().exists():
        data = json.loads(last_report_path().read_text(encoding="utf-8"))
        print(f"Last review: {data.get('checked_at')} — {data.get('summary')}")
    return 0


def cmd_slack(args: argparse.Namespace) -> int:
    if args.action == "check":
        return print_slack_check(interactive=True)
    if args.action == "start":
        if print_slack_check(interactive=True) != 0:
            print("\nFix the issues above, then run: fgr slack start -f", file=sys.stderr)
            return 1
        start_slack_bot(args.foreground)
        return 0
    if args.action == "stop":
        stop_slack_bot()
        return 0
    print("Usage: fgr slack check | start | stop")
    return 1


def cmd_guardian(args: argparse.Namespace) -> int:
    if args.action == "start":
        start_guardian(args.foreground)
        return 0
    if args.action == "stop":
        stop_guardian()
        return 0
    if args.action == "once":
        cfg = load_config()
        if not has_active_focus(cfg):
            print(NO_FOCUS_HINT)
            return 0
        a = evaluate_and_chime(cfg)
        print(json.dumps(a.to_dict(), indent=2))
        return 0
    cfg = load_config()
    if not has_active_focus(cfg):
        print(NO_FOCUS_HINT)
        return 0
    a = evaluate_drift(cfg)
    print(json.dumps(a.to_dict(), indent=2))
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    if args.action == "start":
        start_monitor(args.interval, args.foreground)
        return 0
    if args.action == "stop":
        stop_monitor()
        return 0
    out = run_once()
    print(json.dumps(out, indent=2))
    return 0


def cmd_mcp(_: argparse.Namespace) -> int:
    """Run the local MCP server (stdio) for Claude Desktop, Cursor, or Codex."""
    from focus_guardian.mcp_server import main as mcp_main

    mcp_main()
    return 0


def cmd_init(_: argparse.Namespace) -> int:
    ensure_config()
    cfg = load_config()
    if cfg.get("activeProfile") == "job_search" and "Describe your" in cfg.get("currentGoal", ""):
        merged = apply_profile(cfg, "job_search")
        save_config(merged)
    print(f"Config: {config_path()}")
    if familiar_settings_path().exists():
        print(f"Familiar OK: {get_stills(load_config())}")
    else:
        print("Install Familiar on this machine and complete setup.")
    print("Default: proactive guardian. Run: fgr guardian start  |  fgr slack start  |  fgr review --human")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="fgr",
        description="Focus Guardian — Familiar-powered productivity companion",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_review = sub.add_parser(
        "review",
        help="Deep review: stitch work blocks from Familiar history + clipboards",
    )
    p_review.add_argument("-n", "--notify", action="store_true")
    p_review.add_argument(
        "--human",
        "--synthesize",
        action="store_true",
        dest="human",
        help="Coaching-style synthesis (not a dry log)",
    )
    p_review.add_argument(
        "--api",
        action="store_true",
        help="Use ANTHROPIC_API_KEY for richer synthesis (needs --human)",
    )
    p_review.set_defaults(func=cmd_review, synthesize=False)

    p_check = sub.add_parser("check", help="Short snapshot only (legacy)")
    p_check.add_argument("-n", "--notify", action="store_true")
    p_check.set_defaults(func=cmd_check)

    p_coach = sub.add_parser("coach", help="Coaching from last review")
    p_coach.add_argument("--api", action="store_true")
    p_coach.add_argument("--fresh", action="store_true")
    p_coach.add_argument("--print-prompt", action="store_true")
    p_coach.set_defaults(func=cmd_coach)

    p_goal = sub.add_parser(
        "goal",
        help="Set or show today's focus (what Guardian compares you against)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Example: fgr goal "HiBob slide and demo today"',
    )
    p_goal.add_argument(
        "words",
        nargs="*",
        help='Your focus in plain English, in quotes if it has spaces',
    )
    p_goal.add_argument(
        "-k",
        "--keywords",
        help="Optional extra on-topic words, comma-separated: hibob,cursor,slides",
    )
    p_goal.add_argument(
        "--hours",
        type=float,
        help="How many hours fgr review looks back (default 6)",
    )
    p_goal.add_argument(
        "--auto-keywords",
        action="store_true",
        default=True,
        help="Pull keywords from your goal text (default: on)",
    )
    p_goal.set_defaults(func=cmd_goal)

    p_focus = sub.add_parser(
        "focus",
        help="Dynamic focus stack — day / week / month",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Examples:\n'
            '  fgr focus "This week explore pricing, competitors, and GTM" --cadence week\n'
            '  fgr focus "Today: competitor spreadsheet" --cadence day\n'
            '  fgr focus --week sun-thu\n'
            '  fgr focus --clear day'
        ),
    )
    p_focus.add_argument("words", nargs="*", help="Focus in plain English")
    p_focus.add_argument(
        "--cadence",
        choices=["day", "week", "month"],
        help="How long this focus applies (default: inferred from text)",
    )
    p_focus.add_argument(
        "--priorities",
        help="Comma-separated priorities (overrides parsing from text)",
    )
    p_focus.add_argument(
        "--avoid",
        help="Comma-separated drift triggers, e.g. linkedin,new tooling",
    )
    p_focus.add_argument(
        "--week",
        metavar="PRESET",
        help=f"Week boundary preset: {', '.join(WEEK_PRESETS)}",
    )
    p_focus.add_argument(
        "--clear",
        choices=["day", "week", "month"],
        help="Remove focus for a cadence",
    )
    p_focus.set_defaults(func=cmd_focus)

    sub.add_parser("paths", help="Show Familiar data folder + Guardian config paths").set_defaults(
        func=cmd_paths
    )

    p_drift = sub.add_parser("drift", help="Show or inspect drift detection rules")
    p_drift.add_argument("--show-config", action="store_true", help="Print driftRules JSON")
    p_drift.set_defaults(func=cmd_drift)

    p_prof = sub.add_parser("profile", help="Switch life-stage profile")
    p_prof.add_argument("name", nargs="?", default="job_search", help="Profile name")
    p_prof.add_argument("--list", action="store_true")
    p_prof.set_defaults(func=cmd_profile)

    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("init").set_defaults(func=cmd_init)

    sub.add_parser(
        "mcp",
        help="Run local MCP server (Claude Desktop, Cursor, Codex — no API key)",
    ).set_defaults(func=cmd_mcp)

    p_slack = sub.add_parser(
        "slack",
        help="Interactive Slack bot (Socket Mode DM listener)",
    )
    p_slack.add_argument(
        "action",
        choices=["check", "start", "stop"],
        nargs="?",
        default="check",
        help="check setup, start, or stop the Slack bot daemon",
    )
    p_slack.add_argument("-f", "--foreground", action="store_true")
    p_slack.set_defaults(func=cmd_slack)

    p_guard = sub.add_parser(
        "guardian",
        help="Proactive daemon: Wispr + screen drift detection (primary)",
    )
    p_guard.add_argument(
        "action",
        choices=["start", "stop", "once", "status"],
        default="status",
        nargs="?",
    )
    p_guard.add_argument("-f", "--foreground", action="store_true")
    p_guard.set_defaults(func=cmd_guardian)

    p_mon = sub.add_parser("watch", help="Alias for guardian (legacy interval watch if not proactive)")
    p_mon.add_argument("action", choices=["start", "stop", "once"], default="once", nargs="?")
    p_mon.add_argument("-i", "--interval", type=int, default=None, help="Minutes (>=30 recommended)")
    p_mon.add_argument("-f", "--foreground", action="store_true")
    p_mon.set_defaults(func=cmd_monitor)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
