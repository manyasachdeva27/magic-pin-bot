"""
config.py — Environment-driven configuration.

All LLM provider details come from env vars. No hardcoded model IDs.
Supports LLM_PROVIDER=none for deterministic template-only mode.
"""
import os
import time
import json
import hashlib
import logging
from typing import Optional

import httpx

log = logging.getLogger("vera")

# ── Team identity (for /v1/metadata) ─────────────────────────────────────────
TEAM_NAME = os.getenv("TEAM_NAME", "VeraX")
TEAM_MEMBERS = os.getenv("TEAM_MEMBERS", "participant").split(",")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "participant@example.com")
BOT_VERSION = "2.0.0"

# ── LLM provider config ─────────────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "none")  # anthropic|openai|gemini|deepseek|groq|openrouter|none
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
COMPOSE_MODEL = os.getenv("COMPOSE_MODEL", "")     # slow/smart model for composition
FAST_MODEL = os.getenv("FAST_MODEL", "")            # fast/cheap for classification

# Provider defaults
_PROVIDER_DEFAULTS = {
    "anthropic": {"compose": "claude-sonnet-4-5-20250514", "fast": "claude-haiku-4-20250414",
                  "url": "https://api.anthropic.com/v1/messages"},
    "openai":    {"compose": "gpt-4o", "fast": "gpt-4o-mini",
                  "url": "https://api.openai.com/v1/chat/completions"},
    "gemini":    {"compose": "gemini-3.6-pro", "fast": "gemini-3.6-flash",
                  "url": "https://generativelanguage.googleapis.com/v1beta"},
    "deepseek":  {"compose": "deepseek-chat", "fast": "deepseek-chat",
                  "url": "https://api.deepseek.com/v1/chat/completions"},
    "groq":       {"compose": "openai/gpt-oss-120b", "fast": "openai/gpt-oss-120b",
                   "url": "https://api.groq.com/openai/v1/chat/completions"},
    "openrouter": {"compose": "google/gemma-4-26b-a4b-it:free", "fast": "google/gemma-4-26b-a4b-it:free",
                   "url": "https://openrouter.ai/api/v1/chat/completions"},
}

def _get_model(role: str) -> str:
    """Get model name for a role (compose/fast). Falls back to provider defaults."""
    if role == "compose" and COMPOSE_MODEL:
        return COMPOSE_MODEL
    if role == "fast" and FAST_MODEL:
        return FAST_MODEL
    defaults = _PROVIDER_DEFAULTS.get(LLM_PROVIDER, {})
    return defaults.get(role, "")

# ── Timing budgets ───────────────────────────────────────────────────────────
TICK_BUDGET_S = float(os.getenv("TICK_BUDGET_S", "8.0"))
ACTION_DEADLINE_S = float(os.getenv("ACTION_DEADLINE_S", "6.0"))
REPLY_BUDGET_S = float(os.getenv("REPLY_BUDGET_S", "8.0"))

# ── Suppression ──────────────────────────────────────────────────────────────
MAX_SENDS_PER_MERCHANT_PER_DAY = int(os.getenv("MAX_SENDS_PER_MERCHANT", "3"))
MIN_SECONDS_BETWEEN_SENDS = int(os.getenv("MIN_SEND_INTERVAL_S", "300"))

# ── Circuit breaker ──────────────────────────────────────────────────────────
CB_FAILURE_THRESHOLD = 3   # consecutive failures before opening
CB_RESET_TIMEOUT_S = 60    # seconds before trying again


# ── LLM call ─────────────────────────────────────────────────────────────────
_http_client: Optional[httpx.Client] = None

def _get_client() -> httpx.Client:
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client(timeout=ACTION_DEADLINE_S)
    return _http_client


def llm_complete(
    system_prompt: str,
    user_prompt: str,
    role: str = "compose",
    json_mode: bool = False,
    max_tokens: int = 1024,
) -> Optional[str]:
    """
    Unified LLM call. Returns raw text or None on failure.
    Provider-agnostic: dispatches based on LLM_PROVIDER env var.
    Returns None when LLM_PROVIDER=none (template-only mode).
    """
    if LLM_PROVIDER == "none":
        return None

    model = _get_model(role)
    if not model:
        log.warning("No model configured for role=%s provider=%s", role, LLM_PROVIDER)
        return None

    client = _get_client()

    try:
        if LLM_PROVIDER == "anthropic":
            return _call_anthropic(client, model, system_prompt, user_prompt, max_tokens)
        elif LLM_PROVIDER == "openai":
            return _call_openai(client, model, system_prompt, user_prompt, max_tokens, json_mode)
        elif LLM_PROVIDER == "gemini":
            return _call_gemini(client, model, system_prompt, user_prompt, max_tokens)
        elif LLM_PROVIDER == "deepseek":
            return _call_openai_compat(
                client, model, system_prompt, user_prompt, max_tokens, json_mode,
                "https://api.deepseek.com/v1/chat/completions",
            )
        elif LLM_PROVIDER == "groq":
            return _call_openai_compat(
                client, model, system_prompt, user_prompt, max_tokens, json_mode,
                "https://api.groq.com/openai/v1/chat/completions",
            )
        elif LLM_PROVIDER == "openrouter":
            return _call_openrouter(client, model, system_prompt, user_prompt, max_tokens, json_mode)
        else:
            log.warning("Unknown LLM_PROVIDER: %s", LLM_PROVIDER)
            return None
    except Exception as e:
        log.error("LLM call failed: %s", e)
        return None


def _call_anthropic(client, model, system, user, max_tokens) -> str:
    resp = client.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": LLM_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def _call_openai(client, model, system, user, max_tokens, json_mode) -> str:
    return _call_openai_compat(
        client, model, system, user, max_tokens, json_mode,
        "https://api.openai.com/v1/chat/completions",
    )


def _call_openai_compat(client, model, system, user, max_tokens, json_mode, url) -> str:
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    if "groq" in url:
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

    for attempt in range(8):
        resp = client.post(url, headers=headers, json=body)
        if resp.status_code == 429:
            time.sleep(4 * (2 ** attempt))
            continue
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_gemini(client, model, system, user, max_tokens) -> str:
    full_prompt = f"{system}\n\n{user}"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={LLM_API_KEY}"
    resp = client.post(
        url,
        headers={"Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens},
        },
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def _call_openrouter(client, model, system, user, max_tokens, json_mode) -> str:
    """OpenRouter: OpenAI-compatible endpoint. Requires Referer + X-Title headers."""
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/manyasachdeva27/vera-bot",  # required by OpenRouter
        "X-Title": "Vera Bot",
    }

    for attempt in range(4):
        resp = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=body,
        )
        if resp.status_code == 429:
            time.sleep(4 * (2 ** attempt))
            continue
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ── Prompt version (for cache keying) ────────────────────────────────────────
PROMPT_VERSION = "v2.0"


def cache_key(fact_sheet_text: str) -> str:
    """Deterministic cache key from prompt version + model + fact sheet."""
    model = _get_model("compose")
    raw = f"{PROMPT_VERSION}|{LLM_PROVIDER}|{model}|{fact_sheet_text}"
    return hashlib.sha256(raw.encode()).hexdigest()
