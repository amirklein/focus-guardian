"""Unified LLM calling layer.

Supports two providers, auto-detected from environment variables:
  - GEMINI_API_KEY    -> Google Gemini API (free tier via Google AI Studio)
  - ANTHROPIC_API_KEY -> Anthropic API (paid)

If both are set, `cfg["synthesis"]["provider"]` can force one ("gemini" | "anthropic").
If neither is set, callers should fall back to their offline/rule-based path.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request

DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"


def _ssl_context() -> ssl.SSLContext:
    """Use certifi's CA bundle (fixes SSL verification on Homebrew Python/macOS)."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class LLMError(RuntimeError):
    pass


def active_provider(cfg: dict | None = None) -> str | None:
    """Return 'gemini', 'anthropic', or None if no key is configured."""
    cfg = cfg or {}
    forced = (cfg.get("synthesis", {}) or {}).get("provider")
    if forced in ("gemini", "anthropic"):
        return forced
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def _call_gemini(
    system: str,
    user_content: str,
    max_tokens: int,
    model: str | None,
    disable_thinking: bool = False,
) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise LLMError("GEMINI_API_KEY not set.")
    model = model or os.environ.get("FOCUS_GUARDIAN_MODEL", DEFAULT_GEMINI_MODEL)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    generation_config: dict = {"maxOutputTokens": max_tokens}
    if disable_thinking:
        # "Thinking" models (Gemini 2.5+ flash/pro) burn maxOutputTokens on
        # internal reasoning by default, which silently truncates short
        # structured-output calls (e.g. intent parsing). Not all models
        # support thinkingConfig; harmless if ignored.
        generation_config["thinkingConfig"] = {"thinkingBudget": 0}
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_content}]}],
        "generationConfig": generation_config,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise LLMError(e.read().decode("utf-8", errors="replace")) from e
    except urllib.error.URLError as e:
        raise LLMError(f"Gemini network error: {e}") from e

    try:
        candidates = data.get("candidates") or []
        parts = candidates[0]["content"]["parts"]
        texts = [p.get("text", "") for p in parts if "text" in p]
        return "".join(texts).strip()
    except (KeyError, IndexError) as e:
        raise LLMError(f"Unexpected Gemini response shape: {data}") from e


def _call_anthropic(system: str, user_content: str, max_tokens: int, model: str | None) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY not set.")
    model = model or os.environ.get("FOCUS_GUARDIAN_MODEL", DEFAULT_ANTHROPIC_MODEL)
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_content}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90, context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise LLMError(e.read().decode("utf-8", errors="replace")) from e
    except urllib.error.URLError as e:
        raise LLMError(f"Anthropic network error: {e}") from e
    texts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(texts).strip()


def chat(
    system: str,
    user_content: str,
    *,
    max_tokens: int = 500,
    cfg: dict | None = None,
    model: str | None = None,
    disable_thinking: bool = True,
) -> str:
    """Call whichever provider is configured. Raises LLMError if none available or on failure.

    ``disable_thinking`` defaults to True: every call site here wants a short,
    direct reply (coaching, JSON, review prose), and Gemini's "thinking"
    models otherwise burn ``max_tokens`` on invisible reasoning, silently
    truncating the actual output. Pass False if a future caller genuinely
    wants Gemini's extended reasoning.
    """
    provider = active_provider(cfg)
    if provider == "gemini":
        return _call_gemini(system, user_content, max_tokens, model, disable_thinking)
    if provider == "anthropic":
        return _call_anthropic(system, user_content, max_tokens, model)
    raise LLMError("No LLM provider configured. Set GEMINI_API_KEY or ANTHROPIC_API_KEY.")


def chat_json(
    system: str,
    user_content: str,
    *,
    max_tokens: int = 500,
    cfg: dict | None = None,
    model: str | None = None,
) -> dict:
    """Call chat() and parse the response as JSON (stripping ``` fences if present)."""
    text = chat(system, user_content, max_tokens=max_tokens, cfg=cfg, model=model).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return json.loads(text)


INTENT_ACTIONS = (
    "help",
    "set_focus",
    "show_focus",
    "clear_focus",
    "set_week",
    "status",
    "review",
    "drift",
    "snooze",
    "resume",
    "unknown",
)

_INTENT_SYSTEM = """You are the intent parser for Focus Guardian, a Slack bot that tracks the
user's current focus (day/week/month) and their productivity drift.

Classify the user's message into exactly one action from this list:
- help: asking what the bot can do
- set_focus: telling you what they're focusing on (a day/week/month goal)
- show_focus: asking what their current focus is
- clear_focus: asking to remove/clear a focus
- set_week: setting their week schedule boundary (e.g. sun-thu, mon-fri)
- status: asking for a quick status/snapshot
- review: asking for a recap of how a period went
- drift: asking whether they're drifting / on track right now
- snooze: asking to pause or mute alerts for a while
- resume: asking to resume/unmute alerts
- unknown: anything else, small talk, or unclear

Respond with ONLY compact JSON, no prose, no markdown fences, matching this shape:
{"action": "<one of the actions above>", "args": {}}

Fill "args" only when relevant and confidently extractable from the message:
- set_focus: {"text": "<the focus text, cleaned up>", "cadence": "day"|"week"|"month"|null}
- clear_focus: {"cadence": "day"|"week"|"month"|null}
- set_week: {"preset": "<week preset text if mentioned>"}
- snooze: {"duration": "<the duration phrase as written, e.g. '3pm' or '2 hours'>"}

If you are not confident, use "unknown". Never invent fields not listed above."""


def parse_intent(message: str, context: dict | None = None, cfg: dict | None = None) -> dict | None:
    """Classify a free-form Slack message into a structured action + args.

    Works with whichever provider is configured (Gemini or Anthropic). Returns
    None if no provider is configured, or if the call/parse fails for any
    reason — callers should fall back to heuristic intent detection.
    """
    if active_provider(cfg) is None:
        return None
    payload = {"message": message, "context": context or {}}
    try:
        result = chat_json(_INTENT_SYSTEM, json.dumps(payload), max_tokens=300, cfg=cfg)
    except (LLMError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(result, dict):
        return None
    action = result.get("action")
    if action not in INTENT_ACTIONS:
        return None
    args = result.get("args")
    if not isinstance(args, dict):
        args = {}
    return {"action": action, "args": args}
