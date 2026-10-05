"""LLM client — OpenAI-compatible chat API (DeepSeek default, override via env).

Env: LLM_API_KEY (required), LLM_BASE_URL (default https://api.deepseek.com),
     LLM_MODEL (default deepseek-chat).
Key stays server-side, never logged. All analyst calls go through chat_json
so outputs are structured and validatable.
"""
from __future__ import annotations

import json
import os

import httpx

BASE = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
MODEL = os.getenv("LLM_MODEL", "deepseek-chat")


def is_configured() -> bool:
    return bool(os.getenv("LLM_API_KEY", ""))


def chat_json(system: str, user: str, max_tokens: int = 2500,
              temperature: float = 0.2, timeout: float = 120.0) -> dict:
    key = os.getenv("LLM_API_KEY", "")
    if not key:
        raise RuntimeError("LLM_API_KEY is not set — add it to .env (never commit it).")
    try:
        r = httpx.post(
            f"{BASE}/chat/completions", timeout=timeout,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": os.getenv("LLM_MODEL", MODEL),
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}],
                  "temperature": temperature, "max_tokens": max_tokens,
                  "response_format": {"type": "json_object"}},
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"] or "{}"
    except Exception as exc:
        raise RuntimeError(f"LLM call failed: {exc}") from exc
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0] if "```" in content[3:] else content
    try:
        out = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM returned non-JSON: {content[:200]}") from exc
    if not isinstance(out, dict):
        raise RuntimeError("LLM returned a JSON array, expected an object.")
    return out
