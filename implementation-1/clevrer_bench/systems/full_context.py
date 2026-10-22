"""Baseline: the whole PDF in the model's context for every question.

doc_mode="text": the PDF's extracted text (the same characters PageIndex reads) is inlined.
doc_mode="file": the PDF itself is uploaded once and attached as an input_file (OpenAI adds
                 page images + text, so token counts are higher). OpenAI API only.
The document precedes the question so the prompt cache (OpenAI's, or vLLM's automatic prefix
caching) can reuse it; cached tokens are reported separately.

OpenAI models go through the Responses API (as in the pilot); locally served models
(configs/models.json entries with a base_url) go through chat completions.
"""
from __future__ import annotations

import time

from openai import OpenAI

from ..data import QAItem
from ..llm import LOCAL_API_KEY, chat_sampling, chat_usage
from ..render import extract_pdf_pages
from .base import Document, Prediction, QASystem, SetupResult, Usage

PROMPT_MARGIN_TOKENS = 3000   # instructions + question + chat template, reserved out of the context


def responses_usage(u) -> Usage:
    if u is None:
        return Usage(llm_calls=1)
    cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
    reasoning = getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", 0) or 0
    return Usage(u.input_tokens or 0, cached, u.output_tokens or 0, reasoning, 1)


class FullContextSystem(QASystem):
    name = "full_context"

    def __init__(self, model: str, reasoning_effort=None, doc_mode: str = "text", **kwargs):
        super().__init__(model, reasoning_effort)
        if doc_mode not in ("text", "file"):
            raise ValueError("doc_mode must be 'text' or 'file'")
        if doc_mode == "file" and self.spec.is_local:
            raise ValueError("doc_mode='file' needs the OpenAI Files API; use 'text' for local models")
        self.doc_mode = doc_mode
        self.name = f"full_context_{doc_mode}"
        if self.spec.is_local:
            self.client = OpenAI(base_url=self.spec.base_url, api_key=LOCAL_API_KEY, max_retries=6, timeout=1800)
        else:
            self.client = OpenAI(max_retries=6, timeout=600)

    def _doc_budget(self) -> int | None:
        """Tokens the document may occupy: the served context minus the output cap and a margin for the
        instructions, question and chat template. None for API models (no cut)."""
        if not (self.spec.is_local and self.spec.context_len):
            return None
        return self.spec.context_len - (self.spec.max_tokens or 0) - PROMPT_MARGIN_TOKENS

    def setup(self, doc: Document) -> SetupResult:
        t = time.time()
        if self.doc_mode == "text":
            pages = extract_pdf_pages(doc.pdf_path)
            info = {"pages": len(pages)}
            budget = self._doc_budget()
            if budget is not None:
                # SPEC sec. 4: a document longer than the context is cut from the end, at a page boundary.
                # Tokens are counted with o200k_base (gpt-oss's tokenizer family; an estimate for other models).
                import tiktoken
                enc = tiktoken.get_encoding("o200k_base")
                kept, used = [], 0
                for p in pages:
                    n = len(enc.encode(p)) + 1
                    if used + n > budget:
                        break
                    kept.append(p)
                    used += n
                total = used + sum(len(enc.encode(p)) + 1 for p in pages[len(kept):])
                info.update(doc_tokens_est=total, kept_tokens_est=used, kept_pages=len(kept),
                            truncated=len(kept) < len(pages), budget_tokens=budget)
                pages = kept
            note = "" if len(pages) == info["pages"] else \
                f" (only the first {len(pages)} of {info['pages']} pages fit in the context)"
            self.doc_text = f"DOCUMENT (full text of the PDF{note}):\n" + "\n".join(pages)
            self.doc_part = {"type": "input_text", "text": self.doc_text}
            info["doc_chars"] = len(self.doc_text)
        else:
            with open(doc.pdf_path, "rb") as f:
                fid = self.client.files.create(file=f, purpose="user_data").id
            self.doc_part = {"type": "input_file", "file_id": fid}
            info = {"file_id": fid}
        return SetupResult(Usage(), time.time() - t, info)   # no LLM tokens spent at setup

    def answer(self, item: QAItem, instructions: str, prompt: str) -> Prediction:
        if self.spec.is_local:
            return self._answer_chat(instructions, prompt)
        t = time.time()
        kwargs = {}
        if self.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        resp = self.client.responses.create(
            model=self.spec.served_name,
            instructions=instructions,
            input=[{"role": "user", "content": [self.doc_part, {"type": "input_text", "text": prompt}]}],
            prompt_cache_key=f"clevrer-{self.name}",
            **kwargs,
        )
        return Prediction(resp.output_text, responses_usage(resp.usage), time.time() - t)

    def _answer_chat(self, instructions: str, prompt: str) -> Prediction:
        t = time.time()
        resp = self.client.chat.completions.create(
            model=self.spec.served_name,
            messages=[{"role": "system", "content": instructions},
                      {"role": "user", "content": self.doc_text + "\n\n" + prompt}],
            **chat_sampling(self.spec, self.reasoning_effort),
        )
        choice = resp.choices[0]
        return Prediction(choice.message.content or "", chat_usage(resp.usage), time.time() - t,
                          trace={"finish_reason": choice.finish_reason})
