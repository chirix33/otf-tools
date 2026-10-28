"""PageIndex (open-source, local mode) as a QA system.

setup(): builds the PageIndex tree for the PDF (Flash indexing) with `model` as the index model.
         Every indexing LLM call goes through LiteLLM; we wrap litellm.(a)completion to sum usage.
         The index + its cost are cached under work_dir so reruns don't rebuild (cost still reported).
answer(): runs PageIndex's own document-QA agent (tree search via tool calls) with `model` as the
          chat model, over the OpenAI Responses protocol so usage and the tool-call trace are returned.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

from ..data import QAItem
from .base import Document, Prediction, QASystem, SetupResult, Usage


class _LiteLLMUsageMeter:
    """Temporarily wraps litellm.completion / acompletion and sums `usage` of every response."""

    def __init__(self):
        self.usage = Usage()
        self._lock = threading.Lock()

    def _record(self, resp):
        u = getattr(resp, "usage", None)
        if u is None:
            return
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        reasoning = getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", 0) or 0
        with self._lock:
            self.usage += Usage(u.prompt_tokens or 0, cached, u.completion_tokens or 0, reasoning, 1)

    def __enter__(self):
        import litellm
        self._orig = (litellm.completion, litellm.acompletion)
        orig_c, orig_a = self._orig

        from ..llm import awith_backoff, with_backoff

        def completion(*a, **k):
            r = with_backoff(orig_c, *a, **k)
            self._record(r)
            return r

        async def acompletion(*a, **k):
            r = await awith_backoff(orig_a, *a, **k)
            self._record(r)
            return r

        litellm.completion, litellm.acompletion = completion, acompletion
        return self

    def __exit__(self, *exc):
        import litellm
        litellm.completion, litellm.acompletion = self._orig


def _file_hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


class PageIndexSystem(QASystem):
    name = "pageindex"

    def __init__(self, model: str, reasoning_effort=None, index_model: str | None = None,
                 max_turns: int | None = None, protocol: str | None = None, **kwargs):
        super().__init__(model, reasoning_effort)
        self.index_model = index_model or model
        self.max_turns = max_turns
        # vLLM's Responses endpoint rejects the agent's list-shaped tool outputs (HTTP 400), so local
        # models default to chat_completions, whose envelope has usage but no tool-call trace
        protocol = protocol or ("chat_completions" if self.spec.is_local else "responses")
        if protocol not in ("responses", "chat_completions"):
            raise ValueError("protocol must be 'responses' or 'chat_completions'")
        self.protocol = protocol

    def setup(self, doc: Document) -> SetupResult:
        from pageindex import PageIndexClient

        from ..llm import endpoint_key, get_model

        store = doc.work_dir / "pageindex_store"
        index_spec = get_model(self.index_model)
        index_side = {"mode": "local", "model": index_spec.served_name, "storage_path": str(store)}
        chat_side = {"mode": "local", "model": self.spec.served_name}
        if index_spec.is_local:   # LiteLLM routes "openai/<id>" + api_base to an OpenAI-compatible server
            backend = {"api_base": index_spec.base_url, "api_key": endpoint_key(index_spec)}
            if "provider" in index_spec.extra_body:   # hosted: indexing calls use the same locked provider
                backend["extra_body"] = {"provider": index_spec.extra_body["provider"]}
            index_side.update(model=f"openai/{index_spec.served_name}", backend=backend)
        if self.spec.is_local:
            chat_side.update(model=f"openai/{self.spec.served_name}",
                             backend={"base_url": self.spec.base_url, "api_key": endpoint_key(self.spec)})
        self.client = PageIndexClient(index=index_side, chat=chat_side)
        cache = doc.work_dir / "pageindex_index.json"
        key = {"pdf_sha": _file_hash(doc.pdf_path), "index_model": self.index_model}
        if cache.exists():
            c = json.loads(cache.read_text())
            if c["key"] == key:
                self.doc_id = c["doc_id"]
                return SetupResult(Usage(**c["usage"]), c["latency_s"],
                                   {"doc_id": self.doc_id, "cached_index": True, "tree_nodes": c.get("tree_nodes")})

        t = time.time()
        with _LiteLLMUsageMeter() as meter:
            self.doc_id = self.client.submit_document(str(doc.pdf_path))["doc_id"]
        latency = time.time() - t
        tree = self.client.get_tree(self.doc_id)
        (doc.work_dir / "pageindex_tree.json").write_text(json.dumps(tree, indent=2, default=str))
        n_nodes = _count_nodes(tree)
        u = meter.usage
        cache.write_text(json.dumps({"key": key, "doc_id": self.doc_id, "latency_s": latency,
                                     "tree_nodes": n_nodes,
                                     "usage": {f: getattr(u, f) for f in ("input_tokens", "cached_input_tokens",
                                               "output_tokens", "reasoning_tokens", "llm_calls")}}))
        return SetupResult(u, latency, {"doc_id": self.doc_id, "cached_index": False, "tree_nodes": n_nodes})

    def answer(self, item: QAItem, instructions: str, prompt: str) -> Prediction:
        global _in_flight
        with _in_flight_lock:
            _in_flight += 1
        try:
            return self._answer(item, instructions, prompt)
        finally:
            with _in_flight_lock:
                _in_flight -= 1
                idle = _in_flight == 0
            if idle:                # clearing while another thread is mid-request hung the process (2026-10-25)
                _release_connections()

    def _answer(self, item: QAItem, instructions: str, prompt: str) -> Prediction:
        t = time.time()
        kwargs = {}
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        if self.max_turns:
            kwargs["max_turns"] = self.max_turns
        if self.spec.is_local:
            # chat() has no sampling arguments; the registry's frozen settings ride extra_body,
            # which PageIndex merges verbatim into every request of the agent loop
            body = dict(self.spec.extra_body)
            if self.spec.temperature is not None:
                body["temperature"] = self.spec.temperature
            if self.spec.top_p is not None:
                body["top_p"] = self.spec.top_p
            if self.spec.max_tokens:
                body["max_tokens" if self.protocol == "chat_completions" else "max_output_tokens"] = \
                    self.spec.max_tokens
            kwargs["extra_body"] = body
        if self.protocol == "chat_completions":
            return self._answer_chat(instructions, prompt, kwargs, t)
        from ..llm import with_backoff
        env = with_backoff(self.client.chat, prompt, doc_id=self.doc_id, protocol="responses",
                               instructions=instructions, **kwargs)
        items = env.get("items") or env.get("output") or []
        # A model turn = one batch of (possibly parallel) function_calls; +1 for the final answer turn.
        text, tool_calls, turns, in_batch = "", [], 1, False
        for it in items:
            typ = it.get("type")
            if typ == "function_call":
                turns += not in_batch
                in_batch = True
                tool_calls.append({"name": it.get("name"), "arguments": it.get("arguments")})
            elif typ in ("function_call_output", "message"):
                in_batch = False
                if typ == "message":
                    text = "".join(c.get("text", "") for c in it.get("content", []) if isinstance(c, dict))
        u = env.get("usage") or {}
        usage = Usage(u.get("input_tokens", 0), (u.get("input_tokens_details") or {}).get("cached_tokens", 0),
                      u.get("output_tokens", 0), (u.get("output_tokens_details") or {}).get("reasoning_tokens", 0),
                      turns)
        return Prediction(text, usage, time.time() - t, trace={"tool_calls": tool_calls})

    def _answer_chat(self, instructions: str, prompt: str, kwargs: dict, t: float) -> Prediction:
        from ..llm import with_backoff
        env = with_backoff(self.client.chat, [{"role": "system", "content": instructions},
                                              {"role": "user", "content": prompt}],
                               doc_id=self.doc_id, protocol="chat_completions", **kwargs)
        choice = env["choices"][0]
        u = env.get("usage") or {}
        # this envelope carries usage summed over turns but no per-turn count or tool-call trace
        usage = Usage(u.get("prompt_tokens", 0), (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
                      u.get("completion_tokens", 0),
                      (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0), 0)
        return Prediction(choice["message"]["content"] or "", usage, time.time() - t,
                          trace={"finish_reason": choice.get("finish_reason")})


_in_flight, _in_flight_lock = 0, threading.Lock()


def _release_connections() -> None:
    """PageIndex runs each question's agent in a fresh event loop, and LiteLLM caches one HTTP client per loop for
    up to an hour, so every question left an open connection behind; thousands of them choked this PC's network
    (2026-10-25). Dropping the cache and collecting the clients closes them. Requests and answers are unchanged."""
    import gc
    try:
        import litellm
        litellm.in_memory_llm_clients_cache.flush_cache()
    except Exception:
        pass
    gc.collect()


def _count_nodes(tree) -> int:
    if isinstance(tree, dict):
        return (1 if "title" in tree else 0) + sum(_count_nodes(v) for v in tree.values()
                                                    if isinstance(v, (list, dict)))
    if isinstance(tree, list):
        return sum(_count_nodes(x) for x in tree)
    return 0
