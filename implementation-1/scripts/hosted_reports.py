"""Final hosted-only (OpenRouter `or-*`) split reports: runs/<split>_hosted_report.{md,json}. Local rows are never
mixed in. Gemma's E2 and ablations were cut at the deadline (SPEC sec. 5) and are left out.

    python scripts/hosted_reports.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clevrer_bench.report import make_split_report  # noqa: E402

MODELS = ("or-gpt-oss-20b", "or-qwen3.6-27b", "or-gemma-4-31b-think")
MAIN = ("otf", "full_context_text", "rag", "pageindex")
ABLATIONS = ("otf_oracle", "otf_reading_only", "otf_no_replay", "otf_no_library")
CUT = {("e2", "or-gemma-4-31b-think")}                  # stopped by the deadline


def systems(split: str) -> list[str]:
    out = []
    for m in MODELS:
        if (split, m) in CUT:
            continue
        out += [f"{s}__{m}" for s in MAIN]
        if split == "e1" and m != "or-gemma-4-31b-think":
            out += [f"{s}__{m}" for s in ABLATIONS]
    if split == "mfg":
        out.append("otf_reading_only__or-qwen3.6-27b")
    return out


for split in ("e1", "e2", "mfg", "itops", "fin"):
    rep = make_split_report(ROOT / "runs", split, systems(split), f"{split}_hosted")
    print(split, [(s["system"], s["model"], s["overall"]["question_accuracy"], s["coverage"]["answered"],
                   s["coverage"]["expected"]) for s in rep["systems"]])
