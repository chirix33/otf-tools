"""A minimal OpenAI-compatible /v1/embeddings endpoint on CPU, serving RAG's embedder (BAAI/bge-small-en-v1.5,
fastembed), so GraphRAG retrieves with the same embeddings as the `rag` system (docs/new_baselines_design.md 5.1).

  python scripts/embed_server.py --port 8765
"""
from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
_lock = threading.Lock()
_model = None


def embed(texts: list[str]) -> list[list[float]]:
    global _model
    from fastembed import TextEmbedding
    with _lock:
        if _model is None:
            cache = ROOT / ".cache" / "fastembed"
            cache.mkdir(parents=True, exist_ok=True)
            _model = TextEmbedding(EMBED_MODEL, cache_dir=str(cache))
        return [v.tolist() for v in _model.embed(texts)]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._send(200, {"object": "list", "data": [{"id": EMBED_MODEL, "object": "model"}]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/embeddings"):
            return self._send(404, {"error": "not found"})
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        texts = req.get("input", [])
        texts = [texts] if isinstance(texts, str) else texts
        vecs = embed([str(t) for t in texts])
        n_tok = sum(len(str(t).split()) for t in texts)
        self._send(200, {"object": "list", "model": EMBED_MODEL,
                         "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vecs)],
                         "usage": {"prompt_tokens": n_tok, "total_tokens": n_tok}})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
