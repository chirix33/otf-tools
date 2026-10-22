"""System registry. Built-ins by short name; anything else as 'package.module:ClassName'."""
from __future__ import annotations

import importlib
from pathlib import Path

from .base import Document, Prediction, QASystem, SetupResult, Usage

BUILTIN = {
    "full_context_text": ("clevrer_bench.systems.full_context:FullContextSystem", {"doc_mode": "text"}),
    "full_context_file": ("clevrer_bench.systems.full_context:FullContextSystem", {"doc_mode": "file"}),
    "pageindex": ("clevrer_bench.systems.pageindex_system:PageIndexSystem", {}),
    "rag": ("clevrer_bench.systems.rag:RAGSystem", {}),
    "otf": ("clevrer_bench.systems.otf_system:OTFSystem", {}),
    # upper bound: the same engine with the hand-written process model instead of a generated one
    "otf_oracle": ("clevrer_bench.systems.otf_system:OTFSystem",
                   {"model_code": str(Path(__file__).resolve().parents[2] / "oracle" / "oracle_model.py")}),
}


def load_system(spec: str, model: str, reasoning_effort=None, **kwargs) -> QASystem:
    target, defaults = BUILTIN.get(spec, (spec, {}))
    if ":" not in target:
        raise ValueError(f"unknown system {spec!r}; use one of {list(BUILTIN)} or 'module:Class'")
    mod, cls = target.split(":")
    system_cls = getattr(importlib.import_module(mod), cls)
    system = system_cls(model=model, reasoning_effort=reasoning_effort, **{**defaults, **kwargs})
    if spec not in BUILTIN and system.name == QASystem.name:
        system.name = cls
    return system


__all__ = ["Document", "Prediction", "QASystem", "SetupResult", "Usage", "load_system", "BUILTIN"]
