"""End-of-split library re-check (SPEC sec. 5, frozen 2026-10-22).

After OTF has run over every document of a split, each document whose own model failed its check re-checks the
models stored in the split's library (generated on later documents of the same split by the same model). If
one passes the forecast check on this document, the document switches to it: its cached model is updated (the
tokens of its failed generation attempts stay in its setup cost) and its earlier answers are moved to
predictions_pass1.jsonl so that the next run answers its questions again.

    python scripts/otf_library_pass.py --split e1 --model gpt-oss-20b
Prints one line per document and, last, "CHANGED <n>".
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from otf import library  # noqa: E402
from otf.toolgen import check_model, short_report  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--split", required=True)
ap.add_argument("--model", required=True)
ap.add_argument("--system", default="otf")
a = ap.parse_args()

from clevrer_bench.systems.otf_system import OTFSystem  # noqa: E402

lib_dir = ROOT / "runs" / f"otf_library_{OTFSystem.VERSION}" / a.split / a.model
changed = 0
for d in sorted((ROOT / "runs").glob(f"{a.split}_d[0-9]*")):
    sys_dir = d / "systems" / f"{a.system}__{a.model}"
    cache_p, nav_p = sys_dir / "work" / "otf_model.json", sys_dir / "work" / "navmap.json"
    if not (cache_p.exists() and nav_p.exists()):
        print(f"{d.name}: no cached model yet, skipped")
        continue
    cache = json.loads(cache_p.read_text(encoding="utf-8"))
    if cache["model"].get("passed"):
        print(f"{d.name}: own model passed, unchanged")
        continue
    nav = json.loads(nav_p.read_text(encoding="utf-8"))
    t0 = time.time()
    picked = None
    for entry in library.load(lib_dir, nav):
        rep = check_model(entry["code"], nav, nav_p)
        print(f"{d.name}: library model from {entry.get('source')}: {short_report(rep).splitlines()[0]}")
        if rep["passed"]:
            picked = (entry, rep)
            break
    if picked is None:
        print(f"{d.name}: no library model passes, stays on fallback")
        continue
    entry, rep = picked
    m = cache["model"]
    m["first_pass"] = {"passed": m.get("passed"), "mean_f1": m.get("mean_f1"), "failed_step": m.get("failed_step")}
    m.update(code=entry["code"], passed=True, mean_f1=rep["mean_f1"], failed_step=None,
             reused_from=entry.get("source"), second_pass=True)
    m.setdefault("attempts", []).append({"step": "library_second_pass", "report": rep, "source": entry.get("source")})
    cache["latency_s"] = cache.get("latency_s", 0) + (time.time() - t0)
    cache_p.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    pred = sys_dir / "predictions.jsonl"
    if pred.exists():
        pred.replace(sys_dir / "predictions_pass1.jsonl")
    changed += 1
    print(f"{d.name}: switched to the model from {entry.get('source')} (F1 {rep['mean_f1']}); questions will be re-answered")
print(f"CHANGED {changed}")
