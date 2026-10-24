"""Tool library: process models that passed their check, keyed by the document's structural signature.

Documents with the same structure (same node title patterns, kinds and table columns) first try the stored
model; it is reused only if it also passes the forecast check on the new document. Generation then has to
succeed once per structure, and its cost is shared across documents.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def signature(nav: dict) -> str:
    """Node title patterns and kinds, with the table columns of each pattern when they are the same in every
    scope ("*" when they vary from scope to scope, e.g. tables headed by different years)."""
    cols: dict = {}
    for n in nav["nodes"]:
        cols.setdefault((re.sub(r"\d+", "#", n["title"]), n["kind"]), set()).add(
            tuple(n.get("table", {}).get("columns", [])))
    shapes = sorted((p, k, next(iter(c)) if len(c) == 1 else ("*",)) for (p, k), c in cols.items())
    return hashlib.sha256(json.dumps(shapes).encode()).hexdigest()[:16]


def load(lib_dir: Path | None, nav: dict) -> list[dict]:
    """Stored passing models for this structure, most recent first."""
    if lib_dir is None:
        return []
    f = lib_dir / f"{signature(nav)}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def store(lib_dir: Path | None, nav: dict, model: dict, source: str) -> None:
    if lib_dir is None or not model.get("passed"):
        return
    lib_dir.mkdir(parents=True, exist_ok=True)
    f = lib_dir / f"{signature(nav)}.json"
    entries = load(lib_dir, nav)
    if any(e["code"] == model["code"] for e in entries):
        return
    entries.insert(0, {"code": model["code"], "mean_f1": model["mean_f1"], "source": source})
    f.write_text(json.dumps(entries[:3], indent=1), encoding="utf-8")
