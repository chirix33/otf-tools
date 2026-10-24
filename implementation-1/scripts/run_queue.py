"""GPU queue after the E1 baselines (agreed 2026-10-23; SPEC sec. 12): one model at a time, OTF v3 first.

    python scripts/run_queue.py                # waits for the E1 orchestrator, then runs every stage
    python scripts/run_queue.py --dry-run      # show the plan and what is already done; touch nothing

Stage order (fewest server switches; each stage is resumable and skips finished jobs):
  1. qwen3.6-27b: the E1 OTF run started by run_otf_alongside.py is waited for (its own process); meanwhile the new
     domains run: OTF, then full context, RAG, PageIndex.
  2. gpt-oss-20b: E1 OTF v3 + oracle, E2 OTF v3 + RAG + full context (cut to fit, SPEC sec. 3), then the new
     domains (same systems).
  3. gemma-4-31b-think: E1 OTF v3, then the new domains.
Within a stage, two lanes share the server: OTF jobs in one, baselines in the other. A job is a split
(`<split>_d[0-9]*`: test documents only, never `<split>_dev`) x system; it gets up to 3 passes (run.py resumes),
and OTF jobs then get the end-of-split library re-check (SPEC sec. 5) and one more pass if documents switched.
Events go to runs/logs/queue__status.jsonl; job output to runs/logs/<split>__<model>__<system>.log.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
from run_baselines import LOGS, served_models, start_server, stop_server  # noqa: E402
from clevrer_bench.llm import get_model  # noqa: E402

DOMAINS = ("mfg", "itops", "fin")
BASELINES = ("full_context_text", "rag", "pageindex")
STAGES = [
    {"model": "qwen3.6-27b", "wait_alongside": True,
     "otf": [(s, "otf") for s in DOMAINS],
     "baselines": [(s, b) for b in BASELINES for s in DOMAINS]},
    {"model": "gpt-oss-20b",
     "otf": [("e1", "otf"), ("e1", "otf_oracle"), ("e2", "otf")] + [(s, "otf") for s in DOMAINS],
     "baselines": [("e2", "rag"), ("e2", "full_context_text")] + [(s, b) for b in BASELINES for s in DOMAINS]},
    {"model": "gemma-4-31b-think",
     "otf": [("e1", "otf")] + [(s, "otf") for s in DOMAINS],
     "baselines": [(s, b) for b in BASELINES for s in DOMAINS]},
]
_lock = threading.Lock()


def status(**event) -> None:
    event = {"time": datetime.now().isoformat(timespec="seconds"), **event}
    line = json.dumps(event)
    with _lock:
        print(line, flush=True)
        with (LOGS / "queue__status.jsonl").open("a") as f:
            f.write(line + "\n")


def progress(split: str, system: str, model: str) -> dict:
    """answered / expected over the split's test documents (last row per question wins)."""
    expected = answered = 0
    for d in sorted((ROOT / "runs").glob(f"{split}_d[0-9]*")):
        uids = {json.loads(l)["uid"] for l in (d / "items.jsonl").read_text().splitlines()}
        expected += len(uids)
        pred = d / "systems" / f"{system}__{model}" / "predictions.jsonl"
        rows = {}
        if pred.exists():
            for line in pred.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("uid") in uids:
                    rows[r["uid"]] = r
        answered += sum("error" not in r for r in rows.values())
    return {"expected": expected, "answered": answered}


def done(split: str, system: str, model: str) -> bool:
    p = progress(split, system, model)
    return p["expected"] > 0 and p["answered"] == p["expected"]


def processes(pattern: str) -> int:
    """How many other python processes have `pattern` in their command line (Windows, via PowerShell)."""
    ps = (f"@(Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
          f"Where-Object {{ $_.CommandLine -like '*{pattern}*' -and $_.ProcessId -ne {os.getpid()} }}).Count")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    try:
        return int(out.stdout.strip() or 0)
    except ValueError:
        return 0


def e1_orchestrator_finished() -> bool:
    """The E1 orchestrator's last start/all_done event is all_done and it is not running."""
    last = None
    for line in (LOGS / "e1__status.jsonl").read_text().splitlines():
        ev = json.loads(line).get("event")
        if ev in ("start", "all_done"):
            last = ev
    return last == "all_done" and processes("run_baselines.py") == 0


def alongside_finished(model: str) -> bool:
    return processes("run_otf_alongside.py") == 0 and any(
        json.loads(l).get("event") == "otf_alongside_done" and json.loads(l).get("model") == model
        for l in (LOGS / "e1__status.jsonl").read_text().splitlines())


def ensure_served(model: str):
    spec = get_model(model)
    if spec.served_name in (served_models(spec.base_url) or []):
        return None
    return start_server("queue", model)          # stops whatever else is served


def run_job(split: str, system: str, model: str, workers: int, passes: int = 3) -> None:
    spec = get_model(model)

    def one_round():
        for p in range(1, passes + 1):
            prog = progress(split, system, model)
            if prog["expected"] and prog["answered"] == prog["expected"]:
                return
            while spec.served_name not in (served_models(spec.base_url) or []):
                time.sleep(30)                   # the stage owner restarts a dead server
            status(event="pass_start", split=split, system=system, model=model, pass_no=p, **prog)
            t0 = time.time()
            with (LOGS / f"{split}__{model}__{system}.log").open("a") as log:
                subprocess.run([sys.executable, str(ROOT / "run.py"), "run", "--run", f"{split}_d[0-9]*",
                                "--system", system, "--model", model, "--workers", str(workers)],
                               cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            status(event="pass_end", split=split, system=system, model=model, pass_no=p,
                   hours=round((time.time() - t0) / 3600, 2), **progress(split, system, model))

    one_round()
    if system == "otf":
        with (LOGS / f"{split}__{model}__otf_library_pass.log").open("a") as log:
            out = subprocess.run([sys.executable, str(ROOT / "scripts" / "otf_library_pass.py"), "--split", split,
                                  "--model", model], cwd=ROOT, capture_output=True, text=True)
            log.write(out.stdout + out.stderr)
        changed = int(next((l.split()[1] for l in out.stdout.splitlines() if l.startswith("CHANGED")), 0))
        status(event="otf_library_pass", split=split, model=model, documents_switched=changed)
        if changed:
            one_round()
    status(event="job_done", split=split, system=system, model=model, **progress(split, system, model))


def lane(jobs: list, model: str, workers: int) -> None:
    for split, system in jobs:
        if done(split, system, model):
            continue
        try:
            run_job(split, system, model, workers)
        except Exception as e:                   # one job's failure does not stop the lane
            status(event="job_failed", split=split, system=system, model=model, error=f"{type(e).__name__}: {e}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    if a.dry_run:
        print(f"E1 orchestrator finished: {e1_orchestrator_finished()}")
        for st in STAGES:
            print(f"\n== {st['model']}" + ("  (waits for the E1 OTF alongside run)" if st.get("wait_alongside") else ""))
            for kind in ("otf", "baselines"):
                for split, system in st[kind]:
                    p = progress(split, system, st["model"])
                    docs = len(list((ROOT / "runs").glob(f"{split}_d[0-9]*")))
                    print(f"  [{kind:9s}] {split:5s} {system:18s} {docs:2d} docs  {p['answered']:5d}/{p['expected']:5d}"
                          + ("  done" if done(split, system, st["model"]) else ""))
        return
    LOGS.mkdir(parents=True, exist_ok=True)
    status(event="queue_start")
    while not e1_orchestrator_finished():
        time.sleep(120)
    status(event="e1_orchestrator_finished")
    for st in STAGES:
        model = st["model"]
        pending = [j for j in st["otf"] + st["baselines"] if not done(*j, model)]
        if not pending and not (st.get("wait_alongside") and not alongside_finished(model)):
            status(event="stage_skipped", model=model)
            continue
        try:
            proc = ensure_served(model)
        except Exception as e:
            status(event="server_failed", model=model, error=str(e))
            continue
        status(event="stage_start", model=model, pending=len(pending))
        lanes = [threading.Thread(target=lane, args=(st["otf"], model, a.workers)),
                 threading.Thread(target=lane, args=(st["baselines"], model, a.workers))]
        for t in lanes:
            t.start()
        while any(t.is_alive() for t in lanes) or (st.get("wait_alongside") and not alongside_finished(model)):
            time.sleep(60)
            spec = get_model(model)
            if spec.served_name not in (served_models(spec.base_url) or []):
                status(event="server_down_restarting", model=model)
                try:
                    proc = start_server("queue", model)
                except Exception as e:
                    status(event="server_failed", model=model, error=str(e))
        status(event="stage_done", model=model)
    stop_server(get_model(STAGES[-1]["model"]).base_url)
    status(event="queue_done")


if __name__ == "__main__":
    main()
