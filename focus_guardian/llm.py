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
import urllib.error
import urllib.request

DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"


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


def _call_gemini(system: str, user_content: str, max_tokens: int, model: str | None) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise LLMError("GEMINI_API_KEY not set.")
    model = model or os.environ.get("FOCUS_GUARDIAN_MODEL", DEFAULT_GEMINI_MODEL)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_content}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise LLMError(e.read().decode("utf-8", errors="replace")) from e

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
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise LLMError(e.read().decode("utf-8", errors="replace")) from e
    texts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(texts).strip()


def chat(
    system: str,
    user_content: str,
    *,
    max_tokens: int = 500,
    cfg: dict | None = None,
    model: str | None = None,
) -> str:
    """Call whichever provider is configured. Raises LLMError if none available or on failure."""
    provider = active_provider(cfg)
    if provider == "gemini":
        return _call_gemini(system, user_content, max_tokens, model)
    if provider == "anthropic":
        return _call_anthropic(system, user_content, max_tokens, model)
    raise LLMError("No LLM provider configured. Set GEMINI_API_KEY or ANTHROPIC_API_KEY.")


def chat_json(
    system: str,
    user_content: str,
    *,
    max_tokens: int = 300,
    cfg: dict | None = None,
    model: str | None = None,
) -> dict:
    """Call chat() and parse the response as JSON (stripping ``` fences if present)."""
    text = chat(system, user_content, max_tokens=max_tokens, cfg=cfg, model=model).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return json.loads(text)
