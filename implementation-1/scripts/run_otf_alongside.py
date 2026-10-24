"""Run OTF for one model and split on a vLLM server that another job (the orchestrator) owns, sharing it.

It never starts or stops a server: it waits until the model is served, then does what the orchestrator does for
`otf` (SPEC sec. 5): up to --passes passes over the split (run.py resumes), the end-of-split library re-check, and
one more pass if documents switched to a library model. If the server goes away, it waits for it to return.

    python scripts/run_otf_alongside.py --split e1 --model qwen3.6-27b
Progress goes to runs/logs/<split>__status.jsonl (as "otf_alongside" events), output to
runs/logs/<split>__<model>__otf.log.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
from run_baselines import LOGS, served_models, split_progress, status  # noqa: E402
from clevrer_bench.llm import get_model  # noqa: E402


def wait_served(spec) -> None:
    while spec.served_name not in (served_models(spec.base_url) or []):
        time.sleep(60)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--passes", type=int, default=3)
    a = ap.parse_args()
    spec = get_model(a.model)
    status(a.split, event="otf_alongside_start", model=a.model)

    def passes():
        for p in range(1, a.passes + 1):
            prog = split_progress(a.split, "otf", a.model)
            if prog["answered"] == prog["expected"]:
                return
            wait_served(spec)
            status(a.split, event="otf_alongside_pass_start", model=a.model, pass_no=p, **prog)
            t0 = time.time()
            with (LOGS / f"{a.split}__{a.model}__otf.log").open("a") as log:
                subprocess.run([sys.executable, str(ROOT / "run.py"), "run", "--run", f"{a.split}_d*", "--system", "otf",
                                "--model", a.model, "--workers", str(a.workers)], cwd=ROOT, stdout=log,
                               stderr=subprocess.STDOUT)
            status(a.split, event="otf_alongside_pass_end", model=a.model, pass_no=p,
                   hours=round((time.time() - t0) / 3600, 2), **split_progress(a.split, "otf", a.model))

    passes()
    with (LOGS / f"{a.split}__{a.model}__otf_library_pass.log").open("a") as log:
        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "otf_library_pass.py"), "--split", a.split,
                              "--model", a.model], cwd=ROOT, capture_output=True, text=True)
        log.write(out.stdout + out.stderr)
    changed = int(next((l.split()[1] for l in out.stdout.splitlines() if l.startswith("CHANGED")), 0))
    status(a.split, event="otf_library_pass", model=a.model, documents_switched=changed)
    if changed:
        passes()
    status(a.split, event="otf_alongside_done", model=a.model, **split_progress(a.split, "otf", a.model))


if __name__ == "__main__":
    main()
