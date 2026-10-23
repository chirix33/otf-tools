"""GraphRAG (Edge et al. 2024; microsoft/graphrag 3.3.0) as a QA system, local search only.

setup(): one index per (document, model, indexing method, indexing prompts, dependency versions), shared by the
         dev candidates that only differ at query time. Input text comes from the repository's PDF extraction
         (render.extract_pdf_pages); chunking, extraction, summarisation, clustering and community reports use
         GraphRAG's defaults. Every LLM call goes through LiteLLM and is metered into the index's ledger, so
         interrupted builds resume from GraphRAG's own LLM cache and their costs accumulate. Embeddings: the same
         BAAI/bge-small-en-v1.5 (fastembed, CPU, normalised) as RAG, served by a local OpenAI-compatible
         /v1/embeddings endpoint started in-process.
answer(): GraphRAG local search (community level 2, default settings) with the frozen sampling of the model under
          test. The local-search system prompt is GraphRAG's own, plus the slot's extra text and the shared answer
          contract; the query is the shared question prompt.

index_method: "standard" (LLM extraction) or "fast" (GraphRAG's documented NLP extraction). The choice is made on
pilot20 by the pipeline (>10% failed extraction chunks -> fast) and frozen; this class never switches by itself.
slot 3 uses prompts produced by GraphRAG's prompt auto-tuning on pilot20 (`tuned_prompts_dir`).
"""
from __future__ import annotations

import asyncio
import json
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..data import QAItem
from ..prompts import ANSWER_INSTRUCTIONS
from ..render import extract_pdf_pages
from . import baseline_prompts as P
from .base import Document, SetupResult
from .metered import Ledger, call_context, install_litellm_meter
from .tierb_common import TierBSystem, dependency_versions, file_sha, stable_hash

COMMUNITY_LEVEL = 2                      # GraphRAG CLI default for local search
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384                          # bge-small-en-v1.5
SERVER_MAX_SEQS = 8                      # scripts/serve.sh --max-num-seqs for Qwen and Gemma
TUNED_FILES = {"extract_graph": "extract_graph.txt", "summarize_descriptions": "summarize_descriptions.txt",
               "community_report_graph": "community_report_graph.txt"}


def graphrag_version() -> dict:
    """Exact installed version and the upstream release commit it was built from (recorded at lock time)."""
    from importlib import metadata
    v = metadata.version("graphrag")
    return {"package": "graphrag", "version": v, "commit": GRAPHRAG_COMMITS.get(v)}


# Release tag -> commit of microsoft/graphrag (`git ls-remote https://github.com/microsoft/graphrag refs/tags/v3.3.0`),
# checked when the dependency lock was made. Only the locked version is used.
GRAPHRAG_COMMITS = {"3.3.0": "5faaaf4f5685fa2056fa8c3bf9342cb089f2942f"}


class IndexBuildError(RuntimeError):
    def __init__(self, msg: str, extraction: dict):
        super().__init__(msg)
        self.extraction = extraction


# ------------------------------------------------------------------ local CPU embedding endpoint (bge-small)
class _EmbedServer:
    _lock = threading.Lock()
    _srv = None
    _embedder = None

    @classmethod
    def url(cls) -> str:
        with cls._lock:
            if cls._srv is None:
                from .rag import RAGSystem
                rag = RAGSystem.__new__(RAGSystem)          # reuse RAG's embedder (same model, cache, normalisation)
                rag._embed_lock, rag._embedder = threading.Lock(), None
                cls._embedder = rag

                class H(BaseHTTPRequestHandler):
                    protocol_version = "HTTP/1.1"

                    def log_message(self, *a):
                        pass

                    def do_POST(self):
                        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                        inp = body.get("input", [])
                        texts = [inp] if isinstance(inp, str) else [str(x) for x in inp]
                        vecs = cls._embedder._embed(texts) if texts else []
                        out = json.dumps({"object": "list", "model": EMBED_MODEL, "data": [
                            {"object": "embedding", "index": i, "embedding": [float(x) for x in v]}
                            for i, v in enumerate(vecs)], "usage": {"prompt_tokens": 0, "total_tokens": 0}}).encode()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(out)))
                        self.end_headers()
                        self.wfile.write(out)

                cls._srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
                cls._srv.daemon_threads = True
                threading.Thread(target=cls._srv.serve_forever, daemon=True).start()
            return f"http://127.0.0.1:{cls._srv.server_address[1]}/v1"


# ------------------------------------------------------------------ extraction-failure meter
_EXTRACT = {"lock": threading.Lock(), "active": None}


def _install_extraction_meter() -> None:
    """Count, per chunk, whether standard extraction produced any entity (an exception or no parseable record
    counts as a failed chunk). Active only while an index build records into _EXTRACT['active']."""
    from graphrag.index.operations.extract_graph import graph_extractor as ge
    if getattr(ge.GraphExtractor, "_tierb_metered", False):
        return
    orig = ge.GraphExtractor.__call__

    async def __call__(self, text, entity_types, source_id):
        ents, rels = await orig(self, text, entity_types, source_id)
        with _EXTRACT["lock"]:
            if _EXTRACT["active"] is not None:
                _EXTRACT["active"].append({"source_id": str(source_id), "entities": int(len(ents)),
                                           "relationships": int(len(rels))})
        return ents, rels

    ge.GraphExtractor.__call__ = __call__
    ge.GraphExtractor._tierb_metered = True


def _settings(spec, embed_url: str, prompts_dir: Path, local_prompt: Path) -> dict:
    call_args = {"max_tokens": spec.max_tokens, "timeout": 1800}   # as the repo's other clients; queued calls wait
    if spec.temperature is not None:
        call_args["temperature"] = spec.temperature
    if spec.top_p is not None:
        call_args["top_p"] = spec.top_p
    if spec.reasoning_effort:
        call_args["reasoning_effort"] = spec.reasoning_effort
    if spec.extra_body:
        call_args["extra_body"] = dict(spec.extra_body)
    p = lambda name: str((prompts_dir / name).as_posix())
    return {
        "completion_models": {"default_completion_model": {
            "model_provider": "openai", "model": spec.served_name, "api_base": spec.base_url, "api_key": "EMPTY",
            "call_args": call_args, "retry": {"type": "exponential_backoff"}}},
        "embedding_models": {"default_embedding_model": {
            "model_provider": "openai", "model": EMBED_MODEL, "api_base": embed_url, "api_key": "EMPTY",
            "retry": {"type": "exponential_backoff"}}},
        "concurrent_requests": SERVER_MAX_SEQS,       # throughput only: match vLLM's --max-num-seqs (serve.sh)
        "input": {"type": "text"},
        "input_storage": {"type": "file", "base_dir": "input"},
        "output_storage": {"type": "file", "base_dir": "output"},
        "reporting": {"type": "file", "base_dir": "logs"},
        "cache": {"type": "json", "storage": {"type": "file", "base_dir": "cache"}},
        "vector_store": {"type": "lancedb", "db_uri": "output/lancedb", "vector_size": EMBED_DIM},
        "extract_graph": {"prompt": p("extract_graph.txt")},
        "summarize_descriptions": {"prompt": p("summarize_descriptions.txt")},
        "community_reports": {"graph_prompt": p("community_report_graph.txt"),
                              "text_prompt": p("community_report_text.txt")},
        "local_search": {"prompt": str(local_prompt.as_posix())},
        "snapshots": {"graphml": False, "embeddings": False},
    }


def _write_default_prompts(dst: Path) -> None:
    """GraphRAG's own default prompt files (what `graphrag init` writes)."""
    import tempfile
    from graphrag.cli.initialize import initialize_project_at
    with tempfile.TemporaryDirectory() as td:
        initialize_project_at(Path(td), True, "m", "e")
        dst.mkdir(parents=True, exist_ok=True)
        for f in (Path(td) / "prompts").iterdir():
            shutil.copy2(f, dst / f.name)


def _quiet_query_loggers(config) -> None:
    """GraphRAG's query API re-creates its log handlers on every call (closing the file handlers other worker
    threads are writing to). Initialise them once per setup and make the per-query call a no-op."""
    import graphrag.api.query as q
    from graphrag.logger.standard_logging import init_loggers
    init_loggers(config=config, filename="query.log")
    q.init_loggers = lambda *a, **k: None


def _load_config(root: Path):
    from graphrag.config.load_config import load_config
    return load_config(root_dir=root)


def _read_outputs(config) -> dict:
    from graphrag.cli.query import _resolve_output_files
    return _resolve_output_files(config=config, output_list=["communities", "community_reports", "text_units",
                                                            "relationships", "entities"],
                                 optional_list=["covariates"])


class GraphRAGSystem(TierBSystem):
    base_name = "graphrag"

    def __init__(self, model: str, reasoning_effort=None, slot: int = 1, out_name: str | None = None,
                 index_method: str = "standard", tuned_prompts_dir: str | None = None, **kwargs):
        super().__init__(model, reasoning_effort, slot, out_name)
        if index_method not in ("standard", "fast"):
            raise ValueError("index_method must be 'standard' or 'fast'")
        if self.slot == 3 and not tuned_prompts_dir:
            raise ValueError("slot 3 needs tuned_prompts_dir (pilot20 prompt auto-tuning output)")
        self.index_method = index_method
        self.tuned = Path(tuned_prompts_dir) if tuned_prompts_dir and self.slot == 3 else None
        install_litellm_meter()
        _install_extraction_meter()

    def _tuned_hashes(self) -> dict:
        return {k: file_sha(self.tuned / f) for k, f in TUNED_FILES.items()} if self.tuned else {}

    def method_config(self) -> dict:
        return {"index_method": self.index_method, "community_level": COMMUNITY_LEVEL, "search": "local",
                "local_prompt_extra": P.GRAPHRAG_LOCAL_EXTRA[self.slot], "response_type": P.GRAPHRAG_RESPONSE_TYPE,
                "tuned_prompts": self._tuned_hashes(), "embed_model": EMBED_MODEL, "defaults": "graphrag 3.x"}

    def upstream(self) -> dict:
        return graphrag_version()

    def index_key(self, pdf_sha: str) -> str:
        return stable_hash({"pdf": pdf_sha, "model_spec": self.spec.to_dict(), "method": self.index_method,
                            "tuned_prompts": self._tuned_hashes(), "deps": dependency_versions(),
                            "upstream": self.upstream()})

    # ------------------------------------------------------------------ setup
    def setup(self, doc: Document) -> SetupResult:
        t = time.time()
        self.open_ledger(doc)
        pdf_sha = file_sha(doc.pdf_path)
        key = self.index_key(pdf_sha)
        # shared by every candidate with the same index: runs/tier_b/graphrag_index/<doc>__<model>__<key>
        index_root = doc.work_dir.parents[3] / "tier_b" / "graphrag_index"
        self.root = index_root / f"{doc.pdf_path.parent.name}__{self.model}__{key}"
        self.index_ledger = Ledger(self.root / "index_calls.jsonl")
        embed_url = _EmbedServer.url()
        prompts_dir = self.root / "prompts"
        local_prompt = doc.work_dir / f"local_search_prompt_slot{self.slot}.txt"
        marker = self.root / "index_complete.json"
        if not (prompts_dir / "local_search_system_prompt.txt").exists():
            _write_default_prompts(prompts_dir)
            if self.tuned:                                  # slot 3: auto-tuned indexing prompts (pilot20 only)
                for f in TUNED_FILES.values():
                    shutil.copy2(self.tuned / f, prompts_dir / f)
        added = P.GRAPHRAG_LOCAL_EXTRA[self.slot] + P.GRAPHRAG_ANSWER_HEADER + ANSWER_INSTRUCTIONS
        added = added.replace("{", "{{").replace("}", "}}")   # GraphRAG str.format()s this prompt
        local_prompt.write_text((prompts_dir / "local_search_system_prompt.txt").read_text(encoding="utf-8")
                                + added, encoding="utf-8")
        (self.root / "input").mkdir(parents=True, exist_ok=True)
        text = "\n".join(extract_pdf_pages(doc.pdf_path))
        (self.root / "input" / "document.txt").write_text(text, encoding="utf-8")
        (self.root / "settings.yaml").write_text(json.dumps(_settings(self.spec, embed_url, prompts_dir,
                                                                      local_prompt), indent=1), encoding="utf-8")
        self.config = _load_config(self.root)
        stats = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else None
        if stats is None or stats.get("key") != key:
            stats = self._build(key)
            marker.write_text(json.dumps(stats, indent=1), encoding="utf-8")
        self.tables = _read_outputs(self.config)
        _quiet_query_loggers(self.config)
        u, unknown = self.index_ledger.setup_usage()        # every indexing attempt, including resumed ones
        info = {"index_method": self.index_method, "index_dir": str(self.root), "index_key": key,
                "extraction": stats.get("extraction"), "index_build_s": stats.get("build_s"),
                "usage_unknown_calls": unknown, "config_hash": self.config_hash(),
                "entities": len(self.tables["entities"]), "communities": len(self.tables["communities"])}
        latency = sum(r.get("latency_s", 0) for r in self.index_ledger.rows() if r.get("status") == "ok")
        return SetupResult(u, stats.get("build_s", time.time() - t), {**info, "llm_seconds": round(latency, 1)})

    def _build(self, key: str) -> dict:
        from graphrag.api import build_index
        t = time.time()
        records: list = []
        with _EXTRACT["lock"]:
            _EXTRACT["active"] = records
        try:
            with call_context("setup", self.index_ledger):
                results = asyncio.run(build_index(config=self.config, method=self.index_method))
        finally:
            with _EXTRACT["lock"]:
                _EXTRACT["active"] = None
        failed = sum(1 for r in records if r["entities"] == 0)
        extraction = {"chunks": len(records), "failed_chunks": failed,
                      "failed_fraction": round(failed / len(records), 4) if records else None}
        errors = [f"{r.workflow}: {r.error}" for r in results if r.error is not None]
        if errors:
            raise IndexBuildError("GraphRAG indexing failed: " + "; ".join(map(str, errors))[:2000], extraction)
        return {"key": key, "build_s": round(time.time() - t, 1), "method": self.index_method,
                "extraction": extraction}

    # ------------------------------------------------------------------ answer
    def _search(self, instructions: str, prompt: str) -> tuple[str, dict]:
        if instructions != ANSWER_INSTRUCTIONS:
            raise ValueError("GraphRAG's local-search prompt embeds the shared answer contract; got a different one")
        from graphrag.api import local_search
        tb = self.tables
        resp, context = asyncio.run(local_search(
            config=self.config, entities=tb["entities"], communities=tb["communities"],
            community_reports=tb["community_reports"], text_units=tb["text_units"],
            relationships=tb["relationships"], covariates=tb["covariates"], community_level=COMMUNITY_LEVEL,
            response_type=P.GRAPHRAG_RESPONSE_TYPE, query=prompt))
        text = resp if isinstance(resp, str) else json.dumps(resp, default=str)
        sizes = {k: len(v) for k, v in context.items()} if isinstance(context, dict) else None
        return text, {"slot": self.slot, "index_method": self.index_method, "context_rows": sizes}

    def answer(self, item: QAItem, instructions: str, prompt: str):
        def run():
            from .metered import is_context_overflow
            try:
                return self._search(instructions, prompt)
            except Exception as e:                   # a too-long request is a scored outcome, not a retry
                if is_context_overflow(e):
                    return "", {"slot": self.slot, "outcome": "context_overflow", "error": str(e)[:500]}
                raise
        return self.metered_answer(item.uid, run)


def _keep_placeholders(text: str, default: str) -> str:
    """Tuned prompts embed model-written examples that may contain braces; GraphRAG str.format()s the prompt,
    so escape every brace except the placeholders the default prompt uses."""
    import re
    names = set(re.findall(r"\{(\w+)\}", default))
    out = text.replace("{", "{{").replace("}", "}}")
    for n in names:
        out = out.replace("{{" + n + "}}", "{" + n + "}")
    return out


def tune_prompts(model: str, pilot_dir: Path, out_dir: Path, ledger_path: Path, reasoning_effort=None) -> dict:
    """GraphRAG's prompt auto-tuning on the pilot20 document only (GraphRAG candidate slot 3). Writes the three
    tuned indexing prompts to out_dir; its LLM calls are metered as setup cost into ledger_path."""
    from graphrag.api import generate_indexing_prompts
    sysm = GraphRAGSystem(model, reasoning_effort, slot=1)
    done = out_dir / "tune_complete.json"
    if done.exists():
        return json.loads(done.read_text(encoding="utf-8"))
    root = out_dir / "project"
    (root / "input").mkdir(parents=True, exist_ok=True)
    (root / "input" / "document.txt").write_text("\n".join(extract_pdf_pages(pilot_dir / "document.pdf")),
                                                 encoding="utf-8")
    _write_default_prompts(root / "prompts")
    (root / "settings.yaml").write_text(json.dumps(_settings(sysm.spec, _EmbedServer.url(), root / "prompts",
                                                             root / "prompts" / "local_search_system_prompt.txt")),
                                        encoding="utf-8")
    config = _load_config(root)
    t = time.time()
    with call_context("setup", Ledger(ledger_path)):
        extract, summarize, community = asyncio.run(generate_indexing_prompts(config=config))
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in zip(TUNED_FILES.values(), (extract, summarize, community)):
        default = (root / "prompts" / name).read_text(encoding="utf-8")
        (out_dir / name).write_text(_keep_placeholders(text, default), encoding="utf-8")
    info = {"seconds": round(time.time() - t, 1), "files": {f: file_sha(out_dir / f) for f in TUNED_FILES.values()},
            "source_document": "pilot20", "upstream": graphrag_version()}
    done.write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info
