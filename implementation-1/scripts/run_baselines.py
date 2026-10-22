"""Unattended runner: for each model in order, start its vLLM server in WSL, wait until it serves,
run each system over every document of a split, then stop the server.

    python scripts/run_baselines.py --split e1 --models gpt-oss-20b gemma-4-31b-think qwen3.6-27b \
        --systems full_context_text pageindex

Each (model, system) gets up to --passes passes over the split; run.py resumes, so a later pass only
retries questions that errored. If the server dies, it is restarted before the next pass.
Logs: runs/logs/<split>__<model>__server.log, runs/logs/<split>__<model>__<system>.log
Progress (one JSON line per event): runs/logs/<split>__status.jsonl
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clevrer_bench.llm import get_model  # noqa: E402

WSL = ["wsl", "-d", "Ubuntu-24.04", "--"]
SERVE_SH = "/mnt/" + str(ROOT / "scripts" / "serve.sh").replace(":", "").replace("\\", "/")
SERVE_SH = SERVE_SH[:5] + SERVE_SH[5].lower() + SERVE_SH[6:]          # /mnt/C/... -> /mnt/c/...
LOGS = ROOT / "runs" / "logs"


def status(split: str, **event) -> None:
    event = {"time": datetime.now().isoformat(timespec="seconds"), **event}
    print(json.dumps(event), flush=True)
    with (LOGS / f"{split}__status.jsonl").open("a") as f:
        f.write(json.dumps(event) + "\n")


def served_models(base_url: str) -> list[str] | None:
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/models", timeout=5) as r:
            return [m["id"] for m in json.load(r)["data"]]
    except Exception:
        return None


def stop_server(base_url: str) -> None:
    subprocess.run(WSL + ["pkill", "-INT", "-f", "[v]llm serve"], capture_output=True)
    for _ in range(60):
        if served_models(base_url) is None and subprocess.run(
                WSL + ["pgrep", "-f", "[v]llm serve"], capture_output=True).returncode != 0:
            return
        time.sleep(2)
    subprocess.run(WSL + ["pkill", "-9", "-f", "[v]llm"], capture_output=True)
    time.sleep(10)


def start_server(split: str, model: str, timeout_s: int = 1800) -> subprocess.Popen:
    spec = get_model(model)
    stop_server(spec.base_url)
    log = (LOGS / f"{split}__{model}__server.log").open("a")
    proc = subprocess.Popen(WSL + ["bash", SERVE_SH, model], stdout=log, stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        ids = served_models(spec.base_url)
        if ids:
            if spec.served_name not in ids:
                raise RuntimeError(f"server answers but serves {ids}, expected {spec.served_name}")
            status(split, event="server_ready", model=model, seconds=round(time.time() - t0))
            return proc
        if proc.poll() is not None:
            raise RuntimeError(f"vLLM server for {model} exited with code {proc.returncode}; see its log")
        time.sleep(10)
    raise RuntimeError(f"vLLM server for {model} not ready after {timeout_s}s")


def split_progress(split: str, system: str, model: str) -> dict:
    """answered / errored / expected over every document of the split (last write per question wins)."""
    expected = answered = errored = 0
    for d in sorted((ROOT / "runs").glob(f"{split}_d[0-9]*")):
        uids = {json.loads(l)["uid"] for l in (d / "items.jsonl").read_text().splitlines()}
        expected += len(uids)
        pred = d / "systems" / f"{system}__{model}" / "predictions.jsonl"
        rows = {}
        if pred.exists():
            for line in pred.read_text().splitlines():
                r = json.loads(line)
                if r["uid"] in uids:
                    rows[r["uid"]] = r
        answered += sum("error" not in r for r in rows.values())
        errored += sum("error" in r for r in rows.values())
    return {"expected": expected, "answered": answered, "errored": errored}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", required=True)
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--systems", nargs="+", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--passes", type=int, default=3)
    a = ap.parse_args()
    LOGS.mkdir(parents=True, exist_ok=True)
    status(a.split, event="start", models=a.models, systems=a.systems)

    for model in a.models:
        spec = get_model(model)
        if all(split_progress(a.split, s, model)["answered"] == split_progress(a.split, s, model)["expected"]
               for s in a.systems):
            status(a.split, event="model_already_complete", model=model)
            continue
        try:
            proc = start_server(a.split, model)
        except Exception as e:
            status(a.split, event="server_failed", model=model, error=str(e))
            continue
        def run_passes(system):
            nonlocal proc
            for p in range(1, a.passes + 1):
                prog = split_progress(a.split, system, model)
                if prog["answered"] == prog["expected"]:
                    break
                if served_models(spec.base_url) is None:
                    status(a.split, event="server_down_restarting", model=model)
                    try:
                        proc = start_server(a.split, model)
                    except Exception as e:
                        status(a.split, event="server_failed", model=model, error=str(e))
                        break
                status(a.split, event="pass_start", model=model, system=system, pass_no=p, **prog)
                t0 = time.time()
                with (LOGS / f"{a.split}__{model}__{system}.log").open("a") as log:
                    subprocess.run([sys.executable, str(ROOT / "run.py"), "run", "--run", f"{a.split}_d*",
                                    "--system", system, "--model", model, "--workers", str(a.workers)],
                                   cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                status(a.split, event="pass_end", model=model, system=system, pass_no=p,
                       hours=round((time.time() - t0) / 3600, 2), **split_progress(a.split, system, model))

        for system in a.systems:
            run_passes(system)
            if system == "otf":
                # SPEC sec. 5: documents whose own model failed re-check the split's library at the end
                with (LOGS / f"{a.split}__{model}__otf_library_pass.log").open("a") as log:
                    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "otf_library_pass.py"), "--split",
                                          a.split, "--model", model], cwd=ROOT, capture_output=True, text=True)
                    log.write(out.stdout + out.stderr)
                changed = int(next((l.split()[1] for l in out.stdout.splitlines() if l.startswith("CHANGED")), 0))
                status(a.split, event="otf_library_pass", model=model, documents_switched=changed)
                if changed:
                    run_passes(system)
            status(a.split, event="system_done", model=model, system=system,
                   **split_progress(a.split, system, model))
        stop_server(spec.base_url)
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
        status(a.split, event="model_done", model=model)
    status(a.split, event="all_done")


if __name__ == "__main__":
    main()
