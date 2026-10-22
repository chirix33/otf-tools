"""CLEVRER document-QA benchmark CLI.

  python run.py build  --run pilot20 --videos 20
  python run.py run    --run pilot20 --system full_context_text
  python run.py run    --run pilot20 --system pageindex
  python run.py run    --run pilot20 --system my_pkg.my_mod:MySystem --system-arg foo=bar
  python run.py report --run pilot20
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

try:  # optional: OPENAI_API_KEY etc. from ./.env
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def _kv(pairs):
    out = {}
    for p in pairs or []:
        k, v = p.split("=", 1)
        try:
            v = json.loads(v)
        except json.JSONDecodeError:
            pass
        out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="sample videos, render the PDF, write items.jsonl")
    b.add_argument("--run", required=True)
    b.add_argument("--videos", type=int, default=20)
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--stride", type=int, default=8, help="motion-log sampling stride in frames")
    b.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")

    s = sub.add_parser("build-split", help="sample test videos and build several documents (runs/<name>_dNN)")
    s.add_argument("--name", required=True)
    s.add_argument("--videos", type=int, default=300)
    s.add_argument("--per-doc", type=int, default=20)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--stride", type=int, default=8)
    s.add_argument("--exclude-runs", nargs="*", default=["pilot20"], help="runs whose videos are held out (dev set)")
    s.add_argument("--desc-frac", type=float, default=0.25, help="fraction of descriptive questions kept")
    s.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")

    r = sub.add_parser("run", help="answer every question with one system")
    r.add_argument("--run", required=True)
    r.add_argument("--system", required=True, help="full_context_text | full_context_file | pageindex | module:Class")
    r.add_argument("--model", default="gpt-5.5", help="alias in configs/models.json (e.g. gpt-oss-20b, qwen3.6-27b)")
    r.add_argument("--reasoning-effort", default=None, help="e.g. low|medium|high (model default if unset)")
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--limit", type=int, default=None, help="only the first N questions (smoke test)")
    r.add_argument("--types", nargs="*", default=None, help="restrict to question types")
    r.add_argument("--per-type", type=int, default=None, help="only the first N questions of each type (smoke test)")
    r.add_argument("--system-arg", action="append", help="extra constructor kwarg key=value (repeatable)")

    p = sub.add_parser("report", help="aggregate all systems of a run into report.md / report.json")
    p.add_argument("--run", required=True)
    p.add_argument("--systems", nargs="*", default=None)

    q = sub.add_parser("report-split", help="pool all documents of a split into runs/<name>_report.md")
    q.add_argument("--name", required=True)
    q.add_argument("--systems", nargs="*", default=None)

    a = ap.parse_args()
    run_dir = ROOT / "runs" / getattr(a, "run", "")
    if a.cmd == "build":
        from clevrer_bench.runner import build
        run_dir.mkdir(parents=True, exist_ok=True)
        build(a.raw, run_dir, a.videos, a.seed, a.stride)
    elif a.cmd == "build-split":
        from clevrer_bench.runner import build_split
        build_split(a.raw, ROOT / "runs", a.name, a.videos, a.per_doc, a.seed, a.stride, a.exclude_runs,
                    a.desc_frac)
    elif a.cmd == "run":
        from clevrer_bench.runner import run_system
        from clevrer_bench.systems import load_system
        system = load_system(a.system, a.model, a.reasoning_effort, **_kv(a.system_arg))
        # --run may be a glob over a split (e.g. "e1_d*"): documents run one after another
        run_dirs = sorted(p for p in (ROOT / "runs").glob(a.run) if p.is_dir()) if "*" in a.run else [run_dir]
        for d in run_dirs:
            run_system(system, d, a.workers, a.limit, a.types, a.per_type)
    elif a.cmd == "report-split":
        from clevrer_bench.report import make_split_report
        make_split_report(ROOT / "runs", a.name, a.systems)
        print((ROOT / "runs" / f"{a.name}_report.md").read_text(encoding="utf-8"))
    else:
        from clevrer_bench.report import make_report
        make_report(run_dir, a.systems)
        print((run_dir / "report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
