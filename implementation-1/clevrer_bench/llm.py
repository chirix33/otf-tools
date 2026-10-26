"""Model registry (configs/models.json): where each model is served and its frozen sampling settings.

`--model` on the CLI is an alias into the registry. Aliases with a `base_url` are served by an
OpenAI-compatible server (local vLLM, or a hosted one such as OpenRouter) and are called through chat
completions; aliases without one go to the OpenAI API as in the pilot. Unknown aliases fall back to the
OpenAI API with the alias as model id.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .systems.base import Usage

REGISTRY = Path(__file__).resolve().parent.parent / "configs" / "models.json"
LOCAL_API_KEY = "EMPTY"  # vLLM ignores the key but the clients require one


@dataclass
class ModelSpec:
    alias: str
    served_name: str
    base_url: Optional[str] = None
    reasoning_effort: Optional[str] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    context_len: Optional[int] = None    # served context window (vLLM --max-model-len)
    extra_body: dict = field(default_factory=dict)
    api_key_env: Optional[str] = None    # env var holding the endpoint's key (hosted endpoints); None for vLLM

    @property
    def is_local(self) -> bool:
        # True for every OpenAI-compatible endpoint (chat completions), hosted ones included
        return self.base_url is not None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def get_model(alias: str) -> ModelSpec:
    reg = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    conf = reg.get(alias, {"served_name": alias})
    return ModelSpec(alias=alias, **conf)


def endpoint_key(spec: ModelSpec) -> str:
    """API key for a base_url endpoint: the env var named by api_key_env, else vLLM's placeholder."""
    if not spec.api_key_env:
        return LOCAL_API_KEY
    key = os.environ.get(spec.api_key_env)
    if not key:
        raise RuntimeError(f"model {spec.alias!r} needs {spec.api_key_env} in the environment or .env")
    return key


def request_timeout(spec: ModelSpec) -> int:
    """Seconds one request may take: a local vLLM server queues requests (long waits are normal), a hosted endpoint
    answers or stalls, and a stalled request is better retried (with_backoff) than waited on for half an hour."""
    return 600 if spec.api_key_env else 1800


def chat_sampling(spec: ModelSpec, reasoning_effort: Optional[str] = None) -> dict:
    """kwargs for client.chat.completions.create (OpenAI-compatible servers)."""
    kw: dict = {}
    if spec.temperature is not None:
        kw["temperature"] = spec.temperature
    if spec.top_p is not None:
        kw["top_p"] = spec.top_p
    if spec.max_tokens is not None:
        kw["max_tokens"] = spec.max_tokens
    effort = reasoning_effort or spec.reasoning_effort
    if effort:
        kw["reasoning_effort"] = effort
    if spec.extra_body:
        kw["extra_body"] = dict(spec.extra_body)
    return kw


def chat_usage(u) -> Usage:
    """Usage from a chat.completions response (vLLM reports cached/reasoning details when enabled)."""
    if u is None:
        return Usage(llm_calls=1)
    cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
    reasoning = getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", 0) or 0
    return Usage(u.prompt_tokens or 0, cached, u.completion_tokens or 0, reasoning, 1)


# Transient endpoint errors (throttling, overload, dropped connections). Hosted providers return 429 under load
# (SPEC sec. 2); the client's own few quick retries are not enough, and an error that escapes into a system can
# turn into a degraded answer (e.g. a reading fallback) instead of a retried question. Same for every system.
TRANSIENT_NAMES = {"RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError",
                   "ServiceUnavailableError", "Timeout", "LLMRetriesExhausted"}
TRANSIENT_STATUS = {402, 408, 429, 500, 502, 503, 504, 529}   # 402: OpenRouter credits held by in-flight requests
PATIENCE_S = 1800


def is_transient(e: BaseException) -> bool:
    return type(e).__name__ in TRANSIENT_NAMES or getattr(e, "status_code", None) in TRANSIENT_STATUS


def _delays():
    delay = 5.0
    while True:
        yield delay + random.uniform(0, delay)
        delay = min(delay * 2, 120.0)


def with_backoff(fn, *args, **kwargs):
    """fn(*args, **kwargs), retrying transient endpoint errors with exponential backoff for up to PATIENCE_S."""
    t0, delays = time.time(), _delays()
    while True:
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if not is_transient(e) or time.time() - t0 > PATIENCE_S:
                raise
            time.sleep(next(delays))


async def awith_backoff(fn, *args, **kwargs):
    t0, delays = time.time(), _delays()
    while True:
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            if not is_transient(e) or time.time() - t0 > PATIENCE_S:
                raise
            await asyncio.sleep(next(delays))
