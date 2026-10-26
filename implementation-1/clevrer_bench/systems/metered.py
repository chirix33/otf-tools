"""Metered model access shared by the Tier B baselines (ReAct, ReCode, GraphRAG).

Every attempt (successful or failed) is appended to a call ledger (`calls.jsonl` next to predictions.jsonl), so
setup costs survive restarts and accumulate over resumed attempts. Accounting follows the repository convention:
cached input is a subset of input, reasoning a subset of output. A response without usage is recorded as unknown,
never as zero. Per question at most `cap` model calls are allowed (12 in Tier B); the next call raises CallCapReached.

Calls are attributed through a context variable, so worker threads, asyncio tasks (GraphRAG) and
asyncio.to_thread (ReCode) all land in the right question's account.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..llm import ModelSpec, chat_sampling, chat_usage, endpoint_key
from .base import Usage

MAX_CALLS_PER_QUESTION = 12
INFRA_RETRIES = 6            # extra attempts per call after a connection/timeout/429/5xx failure (~3 min of backoff)
FROZEN_KEYS = ("model", "temperature", "top_p", "max_tokens", "reasoning_effort")
USAGE_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "llm_calls")


class CallCapReached(RuntimeError):
    """The question already used its model-call budget; the run scores it as unparseable."""


class ContextOverflow(RuntimeError):
    """The conversation no longer fits the served context window: a model outcome (scored as unparseable),
    not an infrastructure failure, so it is not retried."""


def is_context_overflow(err: BaseException) -> bool:
    m = str(err).lower()
    return "maximum context length" in m or "context length" in m and "exceed" in m or "context window" in m


class OutOfCredits(BaseException):
    """The hosted account has no credit left. Derives from BaseException so per-question error handling does not
    record it as a failed attempt: the whole run stops, and resumes once credits are added."""


def is_out_of_credits(err: BaseException) -> bool:
    m = str(err).lower()
    return getattr(err, "status_code", None) == 402 or "exceed your available credits" in m or \
        "insufficient credits" in m or "add credits" in m


class InfraError(RuntimeError):
    """The server could not be reached after bounded retries; the question is retried on a later pass."""


class Ledger:
    """Append-only JSONL of every model-call attempt."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, **rec) -> None:
        rec = {"t": round(time.time(), 3), **rec}
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    def rows(self) -> list[dict]:
        out = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue                   # a torn last line from a crash carries no complete record
        return out

    def setup_usage(self) -> tuple[Usage, int]:
        """Summed usage of every successful setup-phase call ever recorded, and how many had unknown usage."""
        u, unknown = Usage(), 0
        for r in self.rows():
            if r.get("phase") == "setup" and r.get("status") == "ok":
                if r.get("usage") is None:
                    unknown += 1
                    u += Usage(llm_calls=1)
                else:
                    u += Usage(**{k: r["usage"][k] for k in USAGE_FIELDS})
        return u, unknown


@dataclass
class CallContext:
    phase: str                       # "setup" | "answer"
    ledger: Optional[Ledger] = None
    uid: Optional[str] = None
    cap: Optional[int] = None
    usage: Usage = field(default_factory=Usage)
    calls: int = 0
    unknown_usage_calls: int = 0
    finish_reasons: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def summary(self) -> dict:
        return {"llm_calls": self.calls, "usage_unknown_calls": self.unknown_usage_calls,
                "finish_reasons": self.finish_reasons}


_CTX: contextvars.ContextVar[Optional[CallContext]] = contextvars.ContextVar("tierb_call_ctx", default=None)


def current() -> Optional[CallContext]:
    return _CTX.get()


@contextlib.contextmanager
def call_context(phase: str, ledger: Optional[Ledger], uid: str | None = None, cap: int | None = None):
    ctx = CallContext(phase, ledger, uid, cap)
    token = _CTX.set(ctx)
    try:
        yield ctx
    finally:
        _CTX.reset(token)


def check_cap() -> None:
    ctx = current()
    if ctx is not None and ctx.cap is not None and ctx.calls >= ctx.cap:
        raise CallCapReached(f"call cap of {ctx.cap} model calls reached")


def record(usage: Optional[Usage], finish: Optional[str], latency: float, source: str, attempt: int = 0) -> None:
    """Account one successful call to the current context and its ledger."""
    ctx = current()
    if ctx is None:
        return
    with ctx._lock:
        ctx.calls += 1
        ctx.finish_reasons.append(finish)
        if usage is None:
            ctx.unknown_usage_calls += 1
            ctx.usage += Usage(llm_calls=1)
        else:
            ctx.usage += usage
    if ctx.ledger is not None:
        ctx.ledger.write(phase=ctx.phase, uid=ctx.uid, source=source, status="ok", attempt=attempt,
                         finish_reason=finish, latency_s=round(latency, 3),
                         usage=usage.to_dict() if usage is not None else None)


def record_failure(err: BaseException, source: str, attempt: int) -> None:
    ctx = current()
    if ctx is not None and ctx.ledger is not None:
        ctx.ledger.write(phase=ctx.phase, uid=ctx.uid, source=source, status="failed", attempt=attempt,
                         error=f"{type(err).__name__}: {str(err)[:300]}")


def usage_or_none(u) -> Optional[Usage]:
    if u is None:
        return None
    if isinstance(u, dict):
        if u.get("prompt_tokens") is None:
            return None
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        reasoning = (u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
        return Usage(u["prompt_tokens"] or 0, cached, u.get("completion_tokens") or 0, reasoning, 1)
    if getattr(u, "prompt_tokens", None) is None:
        return None
    return chat_usage(u)


class MeteredChat:
    """Chat completions against the model under test with its frozen sampling settings."""

    def __init__(self, spec: ModelSpec, reasoning_effort: Optional[str] = None, timeout_s: float = 1800):
        from openai import OpenAI
        if not spec.is_local:
            raise ValueError(f"model {spec.alias} has no base_url; Tier B baselines run on the local server")
        if spec.max_tokens != 16384:
            raise ValueError(f"model {spec.alias}: max_tokens must be 16384 (got {spec.max_tokens})")
        self.spec = spec
        self.sampling = chat_sampling(spec, reasoning_effort)
        self.client = OpenAI(base_url=spec.base_url, api_key=endpoint_key(spec), max_retries=0, timeout=timeout_s)

    def request_kwargs(self, **kw) -> dict:
        """Frozen sampling + per-call extras (tools, response_format). Frozen keys cannot be overridden."""
        bad = [k for k in kw if k in FROZEN_KEYS]
        if bad:
            raise ValueError(f"frozen sampling settings cannot be overridden per call: {bad}")
        out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in self.sampling.items()}
        if "extra_body" in kw:
            out["extra_body"] = {**out.get("extra_body", {}), **kw.pop("extra_body")}
        out.update(kw)
        return out

    def chat(self, messages: list[dict], source: str = "chat", **kw):
        """One counted model call (bounded retries on infrastructure errors). Returns the raw response."""
        import openai
        check_cap()
        args = self.request_kwargs(**kw)
        for attempt in range(INFRA_RETRIES + 1):
            t = time.time()
            try:
                resp = self.client.chat.completions.create(model=self.spec.served_name, messages=messages, **args)
            except (openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError,
                    openai.RateLimitError) as e:
                record_failure(e, source, attempt)
                if attempt == INFRA_RETRIES:
                    raise InfraError(f"{type(e).__name__}: {e}") from e
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            except openai.BadRequestError as e:
                record_failure(e, source, attempt)
                if is_context_overflow(e):
                    raise ContextOverflow(str(e)[:500]) from e
                raise
            except openai.APIStatusError as e:
                if is_out_of_credits(e):
                    raise OutOfCredits(str(e)[:300]) from e
                raise
            if not resp.choices or resp.choices[0].finish_reason == "error":
                # hosted endpoints may return 200 with only an error body, or end a generation with finish_reason
                # "error" when the provider failed mid-way: infrastructure, retried like a 5xx
                err = RuntimeError(f"provider error: {str(getattr(resp, 'error', None) or resp)[:300]}")
                record_failure(err, source, attempt)
                if attempt == INFRA_RETRIES:
                    raise InfraError(str(err))
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            record(usage_or_none(resp.usage), resp.choices[0].finish_reason if resp.choices else None,
                   time.time() - t, source, attempt)
            return resp
        raise AssertionError("unreachable")


_litellm_installed = False
_install_lock = threading.Lock()


def install_litellm_meter() -> None:
    """Wrap litellm.completion / acompletion once per process (GraphRAG's model path). Calls made inside a
    call_context are capped, accounted and ledgered; calls outside one pass through unchanged."""
    global _litellm_installed
    import litellm
    with _install_lock:
        if _litellm_installed:
            return
        orig_c, orig_a = litellm.completion, litellm.acompletion

        def completion(*a, **k):
            if current() is None:
                return orig_c(*a, **k)
            check_cap()
            t = time.time()
            try:
                r = orig_c(*a, **k)
            except Exception as e:
                record_failure(e, "litellm", 0)
                if is_out_of_credits(e):
                    raise OutOfCredits(str(e)[:300]) from e
                raise
            if _provider_failed(r):
                e = ProviderFailed("provider ended the generation with finish_reason 'error'")
                record_failure(e, "litellm", 0)
                raise e
            _record_litellm(r, time.time() - t)
            return r

        async def acompletion(*a, **k):
            if current() is None:
                return await orig_a(*a, **k)
            check_cap()
            t = time.time()
            # A streamed request is sent as one ordinary request and handed back as a one-chunk stream: LiteLLM
            # rebuilds streamed usage from the visible text and drops reasoning tokens (seen with OpenRouter:
            # output 6, reasoning 1,332), while the non-streamed usage is the provider's own count. Same request
            # otherwise, so the model's answer is unaffected.
            stream = bool(k.pop("stream", False))
            k.pop("stream_options", None)
            try:
                r = await orig_a(*a, **k)
            except Exception as e:
                record_failure(e, "litellm", 0)
                if is_out_of_credits(e):
                    raise OutOfCredits(str(e)[:300]) from e
                raise
            if _provider_failed(r):
                e = ProviderFailed("provider ended the generation with finish_reason 'error'")
                record_failure(e, "litellm", 0)
                raise e                          # GraphRAG retries indexing calls; an answer is retried later
            _record_litellm(r, time.time() - t)
            return _as_stream(r) if stream else r

        litellm.completion, litellm.acompletion = completion, acompletion
        _litellm_installed = True


class ProviderFailed(RuntimeError):
    """A hosted provider ended the generation with finish_reason 'error' (infrastructure, not a model outcome)."""


def _provider_failed(resp) -> bool:
    ch = getattr(resp, "choices", None)
    return bool(ch) and getattr(ch[0], "finish_reason", None) == "error"


async def _as_stream(resp):
    """A complete ModelResponse as a single streaming chunk (what GraphRAG's local search iterates over)."""
    from litellm.types.utils import Delta, ModelResponseStream, StreamingChoices
    ch = resp.choices[0] if resp.choices else None
    yield ModelResponseStream(id=resp.id, created=resp.created, model=resp.model, choices=[StreamingChoices(
        index=0, delta=Delta(role="assistant", content=(ch.message.content if ch else "") or ""),
        finish_reason=ch.finish_reason if ch else "stop")])


def _record_litellm(resp, latency: float) -> None:
    choices = getattr(resp, "choices", None)
    if choices is None:                       # a streaming iterator: usage unknown
        record(None, None, latency, "litellm")
        return
    record(usage_or_none(getattr(resp, "usage", None)), choices[0].finish_reason if choices else None,
           latency, "litellm")
