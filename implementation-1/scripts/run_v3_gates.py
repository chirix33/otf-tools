"""One-off (2026-10-23): OTF v3 gates G3-G5 (SPEC sec. 5) on gpt-oss-20b, unattended.

Expects the Qwen orchestrator stopped and the v2 OTF folders already renamed (otf__* -> otf_v2__*,
otf_oracle__* -> otf_oracle_v2__*). Then:
  1. serve gpt-oss-20b;
  2. v3 on all 308 pilot20 questions: `otf` (fresh v3 generation) and `otf_oracle` (v3 oracle);
  3. v2 on the same 308 from a git worktree of the frozen v2 code (commit 91f5893), reusing v2's cached
     pilot20 model and its 32 smoke answers; results copied back as otf_v2__ / otf_oracle_v2__;
  4. G5: v3 generation on each new-domain dev document (tool library off, so dev models never reach test
     documents), plus 4 answered questions to exercise the answer path;
  5. pilot20 report; stop the server; restart the Qwen orchestrator (non-OTF systems, as before).
Log: runs/logs/v3_gates.log.

    python scripts/run_v3_gates.py --worktree <dir>
"""
import argparse
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
from run_baselines import start_server, stop_server  # noqa: E402
from clevrer_bench.llm import get_model  # noqa: E402

MODEL = "gpt-oss-20b"
LOG = ROOT / "runs" / "logs" / "v3_gates.log"
V2_COMMIT = "91f5893"


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cwd: Path, *args: str) -> int:
    t0 = time.time()
    with LOG.open("a", encoding="utf-8") as f:
        p = subprocess.run([sys.executable, "run.py", "run", "--model", MODEL, "--workers", "8", *args], cwd=cwd,
                           stdout=f, stderr=subprocess.STDOUT)
    log(f"done ({p.returncode}, {(time.time() - t0) / 60:.1f} min): run {' '.join(args)}  [in {cwd}]")
    return p.returncode


def run_v2(wt: Path, worktree: Path) -> None:
    """v2 on all pilot20 questions from the frozen v2 code, resuming from v2's cached model and answers."""
    if not wt.exists():
        subprocess.run(["git", "worktree", "add", "--detach", str(worktree), V2_COMMIT], cwd=ROOT, check=True)
    src, dst = ROOT / "runs" / "pilot20", wt / "runs" / "pilot20"
    (dst / "systems").mkdir(parents=True, exist_ok=True)
    for f in ("document.pdf", "items.jsonl", "items_all.jsonl", "manifest.json", "build_config.json"):
        if (src / f).exists():
            shutil.copy2(src / f, dst / f)
    for v3_name, v2_name in (("otf", "otf_v2"), ("otf_oracle", "otf_oracle_v2")):
        if not (dst / "systems" / f"{v3_name}__{MODEL}").exists():
            shutil.copytree(src / "systems" / f"{v2_name}__{MODEL}", dst / "systems" / f"{v3_name}__{MODEL}")
    run(wt, "--run", "pilot20", "--system", "otf")
    run(wt, "--run", "pilot20", "--system", "otf_oracle")
    for v3_name, v2_name in (("otf", "otf_v2"), ("otf_oracle", "otf_oracle_v2")):
        back = src / "systems" / f"{v2_name}__{MODEL}"
        shutil.rmtree(back)
        shutil.copytree(dst / "systems" / f"{v3_name}__{MODEL}", back)
    log("v2 results copied back as otf_v2 / otf_oracle_v2")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worktree", type=Path, required=True)
    ap.add_argument("--skip-v2", action="store_true", help="v2 pilot20 results already exist (otf_v2__, otf_oracle_v2__)")
    a = ap.parse_args()
    wt = a.worktree / "implementation-1"
    log("gates: start")
    subprocess.run([sys.executable, "scripts/repair_predictions.py"], cwd=ROOT)
    proc = start_server("pilot20", MODEL)
    try:
        # 2. v3 on pilot20
        run(ROOT, "--run", "pilot20", "--system", "otf")
        run(ROOT, "--run", "pilot20", "--system", "otf_oracle")
        # 3. v2 on pilot20, from the frozen v2 code
        if a.skip_v2:
            log("v2 skipped (results already present)")
        else:
            run_v2(wt, a.worktree)
        # 4. G5 on the new-domain dev documents
        for dev in ("mfg_dev", "itops_dev", "fin_dev"):
            if (ROOT / "runs" / dev / "document.pdf").exists():
                run(ROOT, "--run", dev, "--system", "otf", "--system-arg", "use_library=false", "--limit", "4")
        # 5. report
        with LOG.open("a", encoding="utf-8") as f:
            subprocess.run([sys.executable, "run.py", "report", "--run", "pilot20"], cwd=ROOT, stdout=f,
                           stderr=subprocess.STDOUT)
        log("pilot20 report written (runs/pilot20/report.md)")
    finally:
        stop_server(get_model(MODEL).base_url)
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
        subprocess.Popen([sys.executable, "scripts/run_baselines.py", "--split", "e1",
                          "--models", "gemma-4-31b-think", "qwen3.6-27b",
                          "--systems", "full_context_text", "pageindex", "rag"], cwd=ROOT,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        log("gates: done; Qwen orchestrator restarted (gemma-4-31b-think, qwen3.6-27b; non-OTF systems)")


if __name__ == "__main__":
    main()
