"""Shared plumbing of the Tier B baselines: candidate slots, configuration hashes, provenance, the call ledger,
per-question metering, and Navigation Map access (outline / section rendering) used by ReAct and ReCode."""
from __future__ import annotations

import hashlib
import json
import platform
import time
from importlib import metadata
from pathlib import Path

from .base import Document, Prediction, QASystem
from .baseline_prompts import SLOTS
from .metered import MAX_CALLS_PER_QUESTION, Ledger, call_context

ROOT = Path(__file__).resolve().parents[2]
DEP_PACKAGES = ("openai", "graphrag", "litellm", "fastembed", "onnxruntime", "numpy", "pandas", "lancedb",
                "pdfplumber", "pypdfium2", "tiktoken", "pydantic")


def dependency_versions() -> dict:
    out = {"python": platform.python_version()}
    for p in DEP_PACKAGES:
        try:
            out[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            out[p] = None
    return out


def stable_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def file_sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class TierBSystem(QASystem):
    """Base of graphrag / react_r / react_c / recode. `slot` picks the candidate configuration (1-3);
    `out_name` overrides the output folder name (dev candidates are written as <name>_c<slot>)."""
    base_name = "tierb"

    def __init__(self, model: str, reasoning_effort=None, slot: int = 1, out_name: str | None = None, **kwargs):
        super().__init__(model, reasoning_effort)
        self.slot = int(slot)
        if self.slot not in SLOTS:
            raise ValueError(f"slot must be one of {SLOTS}")
        self.name = out_name or self.base_name
        self.ledger: Ledger | None = None

    # --- identity -------------------------------------------------------------------------------------
    def method_config(self) -> dict:
        """Everything that defines the method's behaviour (prompts, tools, settings). Subclasses extend."""
        return {}

    def upstream(self) -> dict:
        return {}

    def config_hash(self) -> str:
        return stable_hash({"system": self.base_name, "slot": self.slot, "method": self.method_config(),
                            "model_spec": self.spec.to_dict(), "reasoning_effort": self.reasoning_effort,
                            "call_cap": MAX_CALLS_PER_QUESTION, "dependencies": dependency_versions(),
                            "upstream": self.upstream()})

    def provenance(self) -> dict:
        return {"base_system": self.base_name, "slot": self.slot, "config_hash": self.config_hash(),
                "call_cap": MAX_CALLS_PER_QUESTION, "dependencies": dependency_versions(),
                "upstream": self.upstream(), "method_config": self.method_config()}

    # --- metering -------------------------------------------------------------------------------------
    def open_ledger(self, doc: Document) -> Ledger:
        self.ledger = Ledger(doc.work_dir.parent / "calls.jsonl")
        return self.ledger

    def metered_answer(self, uid: str, fn) -> Prediction:
        """Run fn() -> (text, trace) with the per-question call cap; usage comes from the call context."""
        t = time.time()
        with call_context("answer", self.ledger, uid, MAX_CALLS_PER_QUESTION) as ctx:
            text, trace = fn()
        trace.update(ctx.summary())
        trace["finish_reason"] = next((f for f in reversed(ctx.finish_reasons) if f), None)
        return Prediction(text or "", ctx.usage, time.time() - t, trace=trace)


# ------------------------------------------------------------------------------ Navigation Map access
def load_nav(doc: Document) -> tuple[dict, Path]:
    """The supplied map next to the PDF if it belongs to this PDF, else one built from the PDF (same builder)."""
    p = doc.pdf_path.parent / "navmap.json"
    pdf_id = file_sha(doc.pdf_path)[:16]
    if p.exists():
        nav = json.loads(p.read_text(encoding="utf-8"))
        if nav.get("document_id") == pdf_id:
            return nav, p
    from otf.navmap import build_map
    nav = build_map(doc.pdf_path)
    p = doc.work_dir / "navmap.json"
    p.write_text(json.dumps(nav), encoding="utf-8")
    return nav, p


def front_matter(nav: dict) -> str:
    from otf.toolgen import intro_text
    return intro_text(nav)


def _node(nav: dict, ref: str) -> dict | None:
    ref = str(ref or "").strip().strip("'\"")
    by_id = next((n for n in nav["nodes"] if n["node_id"] == ref), None)
    if by_id:
        return by_id
    same = [n for n in nav["nodes"] if n["title"] == ref]
    return same[0] if len(same) == 1 else None      # titles can repeat: only an unambiguous title is accepted


def outline(nav: dict, node_id: str | None = None) -> str:
    if node_id:
        parent = _node(nav, node_id)
        if parent is None:
            return f"error: no node with id {node_id!r}"
        nodes = [n for n in nav["nodes"] if n["node_id"] in set(parent.get("children", []))]
    else:
        nodes = [n for n in nav["nodes"] if n["parent_id"] is None]
    return "\n".join(f"{n['node_id']} | {n['title']} | pages {n['pages'][0]}-{n['pages'][1]}"
                     + (f" | {len(n.get('children', []))} children" if n.get("children") else "")
                     for n in nodes) or "(no children)"


def render_node(nav: dict, node_id: str) -> str:
    n = _node(nav, node_id)
    if n is None:
        return f"error: no node with id {node_id!r} (use list_sections to see node ids)"
    out = [f"## {n['title']} (node {n['node_id']}, pages {n['pages'][0]}-{n['pages'][1]})"]
    if n["kind"] == "table":
        out.append("\t".join(n["table"]["columns"]))
        out += ["\t".join(r) for r in n["table"]["rows"]]
        if n.get("text"):
            out.append(n["text"])
    elif n["kind"] == "list":
        out += n["lines"]
    elif n.get("text"):
        out.append(n["text"])
    if n.get("children"):
        out.append("Children:\n" + outline(nav, n["node_id"]))
    return "\n".join(out)
