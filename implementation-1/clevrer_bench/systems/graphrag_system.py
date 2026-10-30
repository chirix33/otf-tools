"""Baseline GraphRAG (Edge et al. 2024; microsoft/graphrag 3.3.0; docs/new_baselines_design.md sec. 5.1).

setup(): writes the PDF's extracted text (the same extraction as full context) into a GraphRAG project with the
         default settings and prompts of `graphrag init`, wires every LLM role to the model under test and the
         embeddings to RAG's embedder (bge-small-en-v1.5 on CPU, scripts/embed_server.py), and builds the index
         with the standard (LLM) method. Indexing tokens are setup cost. The index is cached per (PDF, model, method).
answer(): GraphRAG local search (the shared answer rules and the question go in as the query; the response type asks
          for the JSON answer). Workers that keep the index in memory serve the questions
          (scripts/graphrag_worker.py, run in .venv-graphrag because GraphRAG pins pandas 3 / numpy 2.4).
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from ..data import QAItem
from ..render import extract_pdf_pages
from .base import Document, Prediction, QASystem, SetupResult, Usage

ROOT = Path(__file__).resolve().parents[2]
GR_PYTHON = ROOT / ".venv-graphrag" / "bin" / "python"
GR_CLI = ROOT / ".venv-graphrag" / "bin" / "graphrag"
WORKER = ROOT / "scripts" / "graphrag_worker.py"
EMBED_PORT = 8765
EMBED_URL = f"http://127.0.0.1:{EMBED_PORT}/v1"
EMBED_DIM = 384           # bge-small-en-v1.5
GRAPHRAG_VERSION = "3.3.0"
RESPONSE_TYPE = ("A single JSON object, exactly as the answer rules below require, and nothing else.\n"
                 "ANSWER RULES:\n{instructions}")
_embed_lock = threading.Lock()


def _usage(d: dict) -> Usage:
    return Usage(*(int(d.get(f, 0)) for f in ("input_tokens", "cached_input_tokens", "output_tokens",
                                              "reasoning_tokens", "llm_calls")))


def ensure_embed_server() -> None:
    with _embed_lock:
        try:
            urllib.request.urlopen(EMBED_URL + "/models", timeout=3)
            return
        except Exception:
            pass
        subprocess.Popen([sys.executable, str(ROOT / "scripts" / "embed_server.py"), "--port", str(EMBED_PORT)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(60):
            time.sleep(1)
            try:
                urllib.request.urlopen(EMBED_URL + "/models", timeout=3)
                return
            except Exception:
                continue
        raise RuntimeError("the embedding server did not start")


class _Worker:
    def __init__(self, project: Path, env: dict):
        self.project, self.env = project, env
        self.log = open(project / "worker_stderr.log", "a")
        self.p = subprocess.Popen([str(GR_PYTHON), str(WORKER), "serve", "--root", str(project)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True,
                                  env=env, cwd=str(project))
        line = self.p.stdout.readline()
        if not line or not json.loads(line).get("ready"):
            raise RuntimeError(f"GraphRAG worker did not start; see {project / 'worker_stderr.log'}")

    def ask(self, req: dict) -> dict:
        self.p.stdin.write(json.dumps(req) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError(f"GraphRAG worker died; see {self.project / 'worker_stderr.log'}")
        return json.loads(line)

    def close(self) -> None:
        try:
            self.p.stdin.close()
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()


class GraphRAGSystem(QASystem):
    name = "graphrag"

    def __init__(self, model: str, reasoning_effort=None, method: str = "standard", search: str = "local",
                 workers: int = 4, **kwargs):
        super().__init__(model, reasoning_effort)
        self.method, self.search, self.n_workers = method, search, int(workers)
        if search != "local":
            self.name = f"graphrag_{search}"
        self._pool: queue.Queue | None = None

    # ---------- settings ----------
    def _env(self) -> dict:
        env = dict(os.environ)
        if self.spec.api_key_env:
            from ..llm import endpoint_key
            env[self.spec.api_key_env] = endpoint_key(self.spec)
        return env

    def _completion_model(self) -> dict:
        s = self.spec
        call_args: dict = {}
        for k in ("temperature", "top_p", "max_tokens"):
            if getattr(s, k) is not None:
                call_args[k] = getattr(s, k)
        extra = dict(s.extra_body)
        effort = self.reasoning_effort
        if effort:
            if s.api_key_env:            # hosted (OpenRouter): its own reasoning field; LiteLLM may drop the OpenAI one
                extra["reasoning"] = {"effort": effort}
            else:
                call_args["reasoning_effort"] = effort
        if extra:
            call_args["extra_body"] = extra
        m = {"model_provider": "openai", "model": s.served_name, "auth_method": "api_key",
             "api_key": f"${{{s.api_key_env}}}" if s.api_key_env else "EMPTY",
             "retry": {"type": "exponential_backoff"}, "call_args": call_args}
        if s.base_url:
            m["api_base"] = s.base_url
        return m

    def _write_project(self, project: Path, text: str) -> None:
        import yaml
        if not (project / "settings.yaml").exists():
            subprocess.run([str(GR_CLI), "init", "--root", str(project), "--force", "-m", self.spec.served_name,
                            "-e", "bge-small-en-v1.5"], check=True, capture_output=True, text=True)
        settings = yaml.safe_load((project / "settings.yaml").read_text())
        settings["completion_models"]["default_completion_model"] = self._completion_model()
        settings["embedding_models"]["default_embedding_model"] = {
            "model_provider": "openai", "model": "bge-small-en-v1.5", "api_base": EMBED_URL, "api_key": "EMPTY",
            "auth_method": "api_key", "retry": {"type": "exponential_backoff"}}
        settings["vector_store"]["vector_size"] = EMBED_DIM
        (project / "settings.yaml").write_text(yaml.safe_dump(settings, sort_keys=False))
        (project / "input").mkdir(exist_ok=True)
        (project / "input" / "document.txt").write_text(text, encoding="utf-8")

    # ---------- QASystem ----------
    def setup(self, doc: Document) -> SetupResult:
        ensure_embed_server()
        project = doc.work_dir / "graphrag"
        project.mkdir(parents=True, exist_ok=True)
        key = {"pdf_sha": hashlib.sha256(doc.pdf_path.read_bytes()).hexdigest()[:16], "model": self.model,
               "method": self.method, "graphrag": GRAPHRAG_VERSION}
        key_p, usage_p = project / "index_key.json", project / "setup_usage.json"
        cached = key_p.exists() and usage_p.exists() and json.loads(key_p.read_text()) == key
        if not cached:
            self._write_project(project, "\n".join(extract_pdf_pages(doc.pdf_path)))
            r = subprocess.run([str(GR_PYTHON), str(WORKER), "index", "--root", str(project), "--method",
                                self.method], env=self._env(), cwd=str(project), capture_output=True, text=True)
            (project / "index_stderr.log").write_text(r.stderr[-200000:])
            if r.returncode != 0:
                raise RuntimeError(f"GraphRAG indexing failed; see {project / 'index_stderr.log'}")
            key_p.write_text(json.dumps(key))
        u = json.loads(usage_p.read_text())
        info = {"method": self.method, "search": self.search, "graphrag": GRAPHRAG_VERSION, "cached_index": cached,
                **{k: v for k, v in u.items() if k not in ("usage", "latency_s")}}
        if self._pool is not None:   # one run covers several documents: stop the workers of the previous document
            while not self._pool.empty():
                self._pool.get().close()
        env = self._env()
        self._pool = queue.Queue()
        for _ in range(self.n_workers):
            self._pool.put(_Worker(project, env))
        self.project = project
        return SetupResult(_usage(u["usage"]), u["latency_s"], info)

    def answer(self, item: QAItem, instructions: str, prompt: str) -> Prediction:
        t = time.time()
        w = self._pool.get()
        try:
            # the query is the question alone: GraphRAG also embeds it to find entities; the answer rules go in
            # the response format slot of its system prompt
            rec = w.ask({"id": item.uid, "query": prompt, "method": self.search,
                         "response_type": RESPONSE_TYPE.replace("{instructions}", instructions)})
        except Exception:
            w.close()
            w = _Worker(self.project, self._env())
            raise
        finally:
            self._pool.put(w)
        if "error" in rec:
            raise RuntimeError(f"GraphRAG {self.search} search failed: {rec['error']}")
        return Prediction(rec["response"], _usage(rec["usage"]), time.time() - t, trace={"search": self.search})
