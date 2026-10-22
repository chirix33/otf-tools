"""Model registry (configs/models.json): where each model is served and its frozen sampling settings.

`--model` on the CLI is an alias into the registry. Aliases with a `base_url` are served by an
OpenAI-compatible server (vLLM) and are called through chat completions; aliases without one go to
the OpenAI API as in the pilot. Unknown aliases fall back to the OpenAI API with the alias as model id.
"""
from __future__ import annotations

import json
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

    @property
    def is_local(self) -> bool:
        return self.base_url is not None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def get_model(alias: str) -> ModelSpec:
    reg = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    conf = reg.get(alias, {"served_name": alias})
    return ModelSpec(alias=alias, **conf)


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
