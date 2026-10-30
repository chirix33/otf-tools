"""GraphRAG driver. Runs inside the GraphRAG venv (.venv-graphrag; graphrag==3.3.0), started by
clevrer_bench/systems/graphrag_system.py. Every LiteLLM completion call is metered, as for PageIndex.

  index --root <project>   build the index (standard method by default); writes <project>/setup_usage.json
  serve --root <project>   load the index once, then answer JSON lines from stdin:
                           {"id", "query", "response_type", "method": "local"|"global"} ->
                           {"id", "response", "usage", "error"?} on stdout (logs go to stderr)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import threading
import time
from pathlib import Path

USAGE_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "llm_calls")


class Meter:
    """Wraps litellm.completion / acompletion and sums the usage of every response."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.u = dict.fromkeys(USAGE_FIELDS, 0)

    def record(self, resp, count_call: bool = True) -> None:
        u = getattr(resp, "usage", None)
        if u is None:
            return
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        reasoning = getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", 0) or 0
        with self.lock:
            self.u["input_tokens"] += u.prompt_tokens or 0
            self.u["cached_input_tokens"] += cached
            self.u["output_tokens"] += u.completion_tokens or 0
            self.u["reasoning_tokens"] += reasoning
            self.u["llm_calls"] += count_call

    def install(self) -> None:
        """Streamed calls (GraphRAG's search answers stream) ask for usage in the last chunk and are metered
        while GraphRAG reads them."""
        import litellm
        orig_c, orig_a = litellm.completion, litellm.acompletion
        meter = self

        def completion(*a, **k):
            if k.get("stream"):
                k.setdefault("stream_options", {"include_usage": True})
                with meter.lock:
                    meter.u["llm_calls"] += 1
                r = orig_c(*a, **k)

                def it():
                    for chunk in r:
                        meter.record(chunk, count_call=False)
                        yield chunk
                return it()
            r = orig_c(*a, **k)
            self.record(r)
            return r

        async def acompletion(*a, **k):
            if k.get("stream"):
                k.setdefault("stream_options", {"include_usage": True})
                with meter.lock:
                    meter.u["llm_calls"] += 1
                r = await orig_a(*a, **k)

                async def it():
                    async for chunk in r:
                        meter.record(chunk, count_call=False)
                        yield chunk
                return it()
            r = await orig_a(*a, **k)
            self.record(r)
            return r

        litellm.completion, litellm.acompletion = completion, acompletion


def _index(root: Path, method: str) -> None:
    from graphrag import api
    from graphrag.config.load_config import load_config
    meter = Meter()
    meter.install()
    config = load_config(root_dir=root)
    # GraphRAG caches LLM replies, so a rerun after a failed attempt does not call the model again for them:
    # the earlier attempts' metered usage and time are kept and added (setup cost includes failed attempts)
    prev = json.loads((root / "setup_usage.json").read_text()) if (root / "setup_usage.json").exists() else {}
    t = time.time()
    results = asyncio.run(api.build_index(config=config, method=method))
    errors = [f"{r.workflow}: {r.error}" for r in results if getattr(r, "error", None)]
    usage = {f: meter.u[f] + prev.get("usage", {}).get(f, 0) for f in USAGE_FIELDS}
    (root / "setup_usage.json").write_text(json.dumps(
        {"usage": usage, "latency_s": time.time() - t + prev.get("latency_s", 0), "method": method,
         "attempts": prev.get("attempts", 0) + 1, "errors": errors, **_extraction_stats(root)}, indent=1))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)


def _extraction_stats(root: Path) -> dict:
    """Share of text units from which no entity was extracted (the design's >10% fallback rule), and graph size."""
    try:
        import pandas as pd
        tu = pd.read_parquet(root / "output" / "text_units.parquet")
        empty = int(sum(1 for x in tu.get("entity_ids", []) if x is None or len(x) == 0))
        return {"text_units": len(tu), "text_units_without_entities": empty,
                "entities": len(pd.read_parquet(root / "output" / "entities.parquet")),
                "relationships": len(pd.read_parquet(root / "output" / "relationships.parquet"))}
    except Exception as e:
        return {"stats_error": f"{type(e).__name__}: {e}"}


def _serve(root: Path, community_level: int) -> None:
    from graphrag import api
    from graphrag.cli.query import _resolve_output_files
    from graphrag.config.load_config import load_config
    meter = Meter()
    meter.install()
    config = load_config(root_dir=root)
    d = _resolve_output_files(config, ["communities", "community_reports", "text_units", "relationships",
                                       "entities"], ["covariates"])
    out = sys.stdout
    sys.stdout = sys.stderr      # anything GraphRAG prints must not reach the protocol channel
    out.write(json.dumps({"ready": True}) + "\n")
    out.flush()
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        meter.reset()
        rec = {"id": req.get("id")}
        try:
            if req.get("method", "local") == "global":
                resp, _ = asyncio.run(api.global_search(
                    config=config, entities=d["entities"], communities=d["communities"],
                    community_reports=d["community_reports"], community_level=community_level,
                    dynamic_community_selection=False, response_type=req["response_type"], query=req["query"]))
            else:
                resp, _ = asyncio.run(api.local_search(
                    config=config, entities=d["entities"], communities=d["communities"],
                    community_reports=d["community_reports"], text_units=d["text_units"],
                    relationships=d["relationships"], covariates=d["covariates"], community_level=community_level,
                    response_type=req["response_type"], query=req["query"]))
            rec["response"] = resp if isinstance(resp, str) else json.dumps(resp, default=str)
        except Exception as e:                       # reported per question; the worker keeps serving
            rec["error"] = f"{type(e).__name__}: {e}"[:2000]
        rec["usage"] = dict(meter.u)
        out.write(json.dumps(rec) + "\n")
        out.flush()


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["index", "serve"])
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--method", default="standard")
    ap.add_argument("--community-level", type=int, default=2)
    a = ap.parse_args()
    if a.cmd == "index":
        _index(a.root, a.method)
    else:
        _serve(a.root, a.community_level)
