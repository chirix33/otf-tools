"""Our system (OTF: on-the-fly tools) as a benchmark QASystem. The method itself lives in the
document-agnostic `otf` package; this adapter only meters tokens and caches the generated model.

setup(): builds the Navigation Map and generates + checks the process model (setup tokens). The model is
         cached in work_dir/otf_model.json per (PDF hash, model alias) so reruns reuse it (cost still reported).
answer(): routes, runs the type's tool in the sandbox, answers; all LLM calls counted per question.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time

from openai import OpenAI

from otf.engine import OTFEngine

from ..data import QAItem
from ..llm import chat_sampling, chat_usage, endpoint_key, request_timeout, with_backoff
from .base import Document, Prediction, QASystem, SetupResult, Usage


class OTFSystem(QASystem):
    name = "otf"

    VERSION = "v3"          # OTF version (SPEC sec. 5); part of the model cache key and the library folder

    def __init__(self, model: str, reasoning_effort=None, max_tries: int = 3, model_code: str | None = None,
                 use_library: bool = True, ablation: str | None = None, **kwargs):
        super().__init__(model, reasoning_effort)
        self.max_tries = max_tries
        self.use_library = str(use_library).lower() not in ("false", "0", "no")
        # ablation (SPEC sec. 11): "reading_only" or "no_replay"; None for the full system
        self.ablation = ablation or None
        if self.ablation:
            self.name = f"otf_{self.ablation}"
        # library off writes to its own folder (otf_no_library, ...) so it never mixes with the main run's answers
        if not self.use_library:
            self.name = f"{self.name}_no_library"
        # model_code: path to a hand-written process model used instead of generating one (oracle upper bound)
        self.model_code = model_code
        if model_code:
            self.name = "otf_oracle" + (f"_{self.ablation}" if self.ablation else "")
        self.client = (OpenAI(base_url=self.spec.base_url, api_key=endpoint_key(self.spec), max_retries=6, timeout=request_timeout(self.spec))
                       if self.spec.is_local else OpenAI(max_retries=6, timeout=600))
        self._tl = threading.local()

    def _llm(self, messages: list[dict], empty_retries: int = 2) -> str:
        """One chat call. A reply with no content (gpt-oss sometimes ends its turn after reasoning) is retried
        up to `empty_retries` times; every call's tokens are counted."""
        for _ in range(empty_retries + 1):
            resp = with_backoff(self.client.chat.completions.create, model=self.spec.served_name, messages=messages,
                                                       **chat_sampling(self.spec, self.reasoning_effort))
            self._tl.usage = getattr(self._tl, "usage", Usage()) + chat_usage(resp.usage)
            self._tl.finish = resp.choices[0].finish_reason
            text = resp.choices[0].message.content or ""
            if text.strip():
                return text
        return ""

    def setup(self, doc: Document) -> SetupResult:
        t = time.time()
        self._tl.usage = Usage()
        log_path = doc.work_dir / "otf_log.txt"
        self.engine = OTFEngine(self._llm, doc.work_dir, self.max_tries,
                                log=lambda s: log_path.open("a", encoding="utf-8").write(s + "\n"),
                                ablation=self.ablation)
        cache = doc.work_dir / "otf_model.json"
        key = {"pdf_sha": hashlib.sha256(doc.pdf_path.read_bytes()).hexdigest()[:16], "model": self.model,
               "max_tries": self.max_tries, "version": self.VERSION}
        cached = None
        if self.model_code:
            from pathlib import Path
            code = Path(self.model_code).read_text(encoding="utf-8")
            info = self.engine.prepare(doc.pdf_path, {"code": code, "passed": True, "mean_f1": None, "tries": 0,
                                                      "attempts": [], "hand_written": True})
            return SetupResult(Usage(), time.time() - t, {**info, "model_code": self.model_code})
        if cache.exists():
            c = json.loads(cache.read_text())
            if c["key"] == key:
                cached = c["model"]
        # tool library shared by the documents of one split (runs/<split>_dNN), per model: test-split tools are
        # generated from test-split documents only
        split = doc.work_dir.parents[2].name.rsplit("_d", 1)[0]
        lib_dir = (doc.work_dir.parents[3] / f"otf_library_{self.VERSION}" / split / self.model
                   if self.use_library else None)
        info = self.engine.prepare(doc.pdf_path, cached, lib_dir)
        if cached is None:
            usage, latency = self._tl.usage, time.time() - t
            cache.write_text(json.dumps({"key": key, "model": self.engine.model, "latency_s": latency,
                                         "usage": usage.to_dict()}, indent=1))
        else:
            c = json.loads(cache.read_text())
            u = c["usage"]
            usage = Usage(u["input_tokens"], u["cached_input_tokens"], u["output_tokens"], u["reasoning_tokens"],
                          u["llm_calls"])
            latency = c["latency_s"]
            info["cached_model"] = True
        return SetupResult(usage, latency, info)

    def answer(self, item: QAItem, instructions: str, prompt: str) -> Prediction:
        t = time.time()
        self._tl.usage, self._tl.finish = Usage(), None
        text, trace = self.engine.answer(prompt, instructions)
        trace["finish_reason"] = self._tl.finish
        return Prediction(text, self._tl.usage, time.time() - t, trace=trace)
