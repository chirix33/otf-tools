"""Wait until the vLLM server serves a given model (the E1 orchestrator switches models), then run OTF on the
pilot20 smoke set with that model: setup generates + checks the process model, then 8 questions per type.
A summary goes to runs/logs/otf_generation__<model>.txt.

    python scripts/test_generation_when_up.py gemma-4-31b-think qwen3.6-27b
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clevrer_bench.llm import get_model  # noqa: E402


def served(base_url):
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/models", timeout=5) as r:
            return [m["id"] for m in json.load(r)["data"]]
    except Exception:
        return []


for model in sys.argv[1:]:
    spec = get_model(model)
    out = ROOT / "runs" / "logs" / f"otf_generation__{model}.txt"
    if out.exists():                     # already tested (e.g. before a reboot)
        print(f"{model}: already done -> {out}", flush=True)
        continue
    while spec.served_name not in served(spec.base_url):
        time.sleep(60)
    time.sleep(120)                      # let the orchestrator's first requests start
    t0 = time.time()
    run = subprocess.run([sys.executable, str(ROOT / "run.py"), "run", "--run", "pilot20", "--system", "otf",
                          "--model", model, "--per-type", "8", "--workers", "4"], cwd=ROOT, capture_output=True,
                         text=True)
    summ = subprocess.run([sys.executable, str(ROOT / "scripts" / "smoke_summary.py"), "runs/pilot20",
                           f"otf__{model}"], cwd=ROOT, capture_output=True, text=True)
    setup = ROOT / "runs" / "pilot20" / "systems" / f"otf__{model}" / "setup.json"
    log = ROOT / "runs" / "pilot20" / "systems" / f"otf__{model}" / "work" / "otf_log.txt"
    out.write_text(
        f"model {model}, finished after {round((time.time() - t0) / 60)} min\n\nSETUP:\n"
        f"{setup.read_text() if setup.exists() else '(no setup.json)'}\n\nSMOKE:\n{summ.stdout}\n"
        f"\nGENERATION LOG:\n{log.read_text(encoding='utf-8') if log.exists() else '(none)'}\n"
        f"\nRUN OUTPUT (tail):\n{run.stdout[-2000:]}\n{run.stderr[-2000:]}\n", encoding="utf-8")
    print(f"{model}: done -> {out}", flush=True)
