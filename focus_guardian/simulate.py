"""Inject synthetic Familiar captures for testing drift detection."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from focus_guardian.familiar import stills_root
from focus_guardian.guardian import evaluate_and_chime
from focus_guardian.paths import last_notify_path, load_config


def _capture_md(*, app: str, title: str) -> str:
    return f"""---
format: familiar-layout-v0
extractor: simulate
app: {app}
window_title_raw: {title}
window_title_norm: {title}
---
# OCR
- "{title}"
- "simulated capture for Focus Guardian drift test"
"""


def _session_dir(parent: Path) -> Path:
    name = f"session-sim-{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}"
    path = parent / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def simulate_drift(
    cfg: dict,
    *,
    app: str = "Google Chrome",
    title: str = "linkedin feed | top job picks",
    minutes: int = 25,
    interval_seconds: int = 90,
    wispr_text: str | None = None,
    notify: bool = False,
    keep: bool = False,
) -> dict:
    """Write synthetic distraction captures and evaluate drift in isolation."""
    tmp_root = Path(tempfile.mkdtemp(prefix="fg-sim-"))
    session = _session_dir(tmp_root)
    now = datetime.now()
    start = now - timedelta(minutes=minutes)
    count = max(3, int((minutes * 60) / interval_seconds) + 1)

    written: list[str] = []
    for i in range(count):
        ts = start + timedelta(seconds=i * interval_seconds)
        stem = ts.strftime("%Y-%m-%dT%H-%M-%S") + "-000"
        path = session / f"{stem}.md"
        path.write_text(_capture_md(app=app, title=title), encoding="utf-8")
        written.append(str(path))

    if wispr_text:
        wispr_stem = now.strftime("%Y-%m-%dT%H-%M-%S") + "-001"
        clip = session / f"{wispr_stem}.clipboard.txt"
        clip.write_text(wispr_text, encoding="utf-8")
        written.append(str(clip))

    if notify:
        last_notify_path().unlink(missing_ok=True)

    eval_cfg = {**cfg, "familiarStillsPath": str(tmp_root)}
    assessment = evaluate_and_chime(eval_cfg)

    persisted: str | None = None
    if keep:
        real_root = stills_root(cfg)
        dest = real_root / session.name
        shutil.copytree(session, dest)
        persisted = str(dest)
        result_session = persisted
    else:
        result_session = str(session)
        shutil.rmtree(tmp_root, ignore_errors=True)

    return {
        "session": result_session,
        "persisted_to_familiar": persisted,
        "captures_written": len(written),
        "sample_paths": written[:3],
        "should_chime": assessment.should_chime,
        "reason": assessment.reason,
        "evidence": assessment.evidence,
        "notified": notify and assessment.should_chime,
    }
