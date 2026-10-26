"""Baseline: standard retrieval-augmented generation over the PDF.

setup(): splits the PDF's text into sections using its embedded outline (the same bookmarks PageIndex
         reads), cuts each section into 512-token chunks with 64-token overlap, prefixes every chunk with
         its section path (e.g. "Video 10331 > Video 10331: Motion log"), and embeds the chunks on CPU
         with BAAI/bge-small-en-v1.5 (fastembed's ONNX build). No LLM tokens are spent; the index is cached.
answer(): embeds the question prompt, takes the top-k chunks by cosine similarity, and makes one LLM call
          with the retrieved chunks + the shared instructions and question prompt.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import numpy as np
from openai import OpenAI

from ..data import QAItem
from ..llm import chat_sampling, chat_usage, endpoint_key
from .base import Document, Prediction, QASystem, SetupResult, Usage

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "fastembed"


def _sections(pdf_path: Path) -> list[tuple[str, str, list[int]]]:
    """(section path, text, pages) for every leaf of the PDF outline, in document order. Section text runs
    from its heading to the next heading; text before the first heading is its own section."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(pdf_path))
    pages = [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
    full, starts = "", []
    for t in pages:
        starts.append(len(full))
        full += t + "\n"

    def page_of(pos: int) -> int:
        return max(i for i, s in enumerate(starts) if s <= pos) + 1

    marks, cursor, stack = [], 0, []
    for b in pdf.get_toc():
        title = b.get_title()
        stack = stack[:b.level] + [title]
        dest = b.get_dest()
        lo = starts[dest.get_index()] if dest is not None else cursor
        pos = full.find(title, max(cursor, lo))
        if pos < 0:
            continue
        marks.append((pos, " > ".join(stack)))
        cursor = pos + len(title)
    marks = [(0, "(front matter)")] + marks if not marks or marks[0][0] > 0 else marks
    out = []
    for (pos, path), nxt in zip(marks, marks[1:] + [(len(full), None)]):
        text = full[pos:nxt[0]].strip()
        if text:
            out.append((path, text, sorted({page_of(pos), page_of(max(pos, nxt[0] - 1))})))
    return out


class RAGSystem(QASystem):
    name = "rag"

    def __init__(self, model: str, reasoning_effort=None, top_k: int = 5, chunk_tokens: int = 512,
                 overlap_tokens: int = 64, **kwargs):
        super().__init__(model, reasoning_effort)
        self.top_k, self.chunk_tokens, self.overlap = top_k, chunk_tokens, overlap_tokens
        if self.spec.is_local:
            self.client = OpenAI(base_url=self.spec.base_url, api_key=endpoint_key(self.spec), max_retries=6, timeout=1800)
        else:
            self.client = OpenAI(max_retries=6, timeout=600)
        self._embed_lock = threading.Lock()
        self._embedder = None

    def _embed(self, texts: list[str]) -> np.ndarray:
        from fastembed import TextEmbedding
        with self._embed_lock:
            if self._embedder is None:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                self._embedder = TextEmbedding(EMBED_MODEL, cache_dir=str(CACHE_DIR))
            v = np.array(list(self._embedder.embed(texts)), dtype=np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    def setup(self, doc: Document) -> SetupResult:
        import tiktoken
        t = time.time()
        key = {"pdf_sha": hashlib.sha256(doc.pdf_path.read_bytes()).hexdigest()[:16], "embed": EMBED_MODEL,
               "chunk": self.chunk_tokens, "overlap": self.overlap}
        meta_p, vec_p = doc.work_dir / "rag_chunks.json", doc.work_dir / "rag_vectors.npy"
        if meta_p.exists() and vec_p.exists() and json.loads(meta_p.read_text())["key"] == key:
            self.chunks = json.loads(meta_p.read_text())["chunks"]
            self.vectors = np.load(vec_p)
        else:
            enc = tiktoken.get_encoding("o200k_base")
            step = self.chunk_tokens - self.overlap
            self.chunks = []
            for path, text, pages in _sections(doc.pdf_path):
                toks = enc.encode(text)
                for s in range(0, max(len(toks) - self.overlap, 1), step):
                    self.chunks.append({"path": path, "pages": pages,
                                        "text": f"[{path}]\n" + enc.decode(toks[s:s + self.chunk_tokens])})
            self.vectors = self._embed([c["text"] for c in self.chunks])
            np.save(vec_p, self.vectors)               # vectors first: the meta file marks a complete cache
            meta_p.write_text(json.dumps({"key": key, "chunks": self.chunks}))
        return SetupResult(Usage(), time.time() - t, {"chunks": len(self.chunks), "embed_model": EMBED_MODEL,
                                                      "top_k": self.top_k})

    def retrieve(self, query: str, k: int | None = None) -> tuple[list[int], str]:
        """Top-k chunk indices by cosine similarity, and the passages formatted as the answer prompt shows them."""
        q = self._embed([query])[0]
        top = [int(j) for j in np.argsort(-(self.vectors @ q))[:k or self.top_k]]
        return top, "\n\n".join(f"PASSAGE {i + 1} (pages {self.chunks[j]['pages']}):\n{self.chunks[j]['text']}"
                                for i, j in enumerate(top))

    def answer(self, item: QAItem, instructions: str, prompt: str) -> Prediction:
        t = time.time()
        top, ctx = self.retrieve(prompt)
        messages = [{"role": "system", "content": instructions},
                    {"role": "user", "content": f"RETRIEVED PASSAGES FROM THE DOCUMENT:\n{ctx}\n\n{prompt}"}]
        if self.spec.is_local:
            resp = self.client.chat.completions.create(model=self.spec.served_name, messages=messages,
                                                       **chat_sampling(self.spec, self.reasoning_effort))
            choice = resp.choices[0]
            text, usage, finish = choice.message.content or "", chat_usage(resp.usage), choice.finish_reason
        else:
            kwargs = {"reasoning": {"effort": self.reasoning_effort}} if self.reasoning_effort else {}
            resp = self.client.responses.create(model=self.spec.served_name, instructions=instructions,
                                                input=messages[1]["content"], **kwargs)
            from .full_context import responses_usage
            text, usage, finish = resp.output_text, responses_usage(resp.usage), None
        return Prediction(text, usage, time.time() - t,
                          trace={"finish_reason": finish,
                                 "retrieved": [{"path": self.chunks[j]["path"], "pages": self.chunks[j]["pages"]}
                                               for j in top]})
