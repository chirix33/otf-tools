"""Hosted runs on OpenRouter (SPEC sec. 2 and 5, "Move to OpenRouter", 2026-10-25). No local server is touched.

    python scripts/run_hosted.py --phase dev                      # pilot20 + dev-document checks
    python scripts/run_hosted.py --phase main e2 ablations        # test runs, in priority order
    python scripts/run_hosted.py --phase main --dry-run           # show the plan and progress; touch nothing

A job is (split, system, model). Each job runs `run.py run --run "<split>_d[0-9]*"` (test documents only, never
`<split>_dev`) as its own process; run.py resumes by question id, and a job gets up to 3 passes to retry errored
questions. OTF jobs then get the end-of-split library re-check (scripts/otf_library_pass.py) and another round if
documents switched. Jobs run concurrently, at most --jobs-per-model at once per model; within a phase jobs start in
list order. The reading-only and no-replay ablations start from the main OTF run's final process models (copied
otf_model.json), so they differ from the main run only by the ablation switch; they wait for that job.
Create runs/logs/HOSTED_RUNS_HALTED to stop starting new passes (running passes finish). `--stop` kills every hosted
runner and its run.py children at once (a killed runner's children otherwise keep running on Windows, and a new
runner would then answer the same questions twice); a runner leaves alone any job that another process is running.
Events: runs/logs/hosted__status.jsonl; job output: runs/logs/hosted/<split>__<model>__<system>.log.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "runs" / "logs"
HALT = LOGS / "HOSTED_RUNS_HALTED"
MODELS = ("or-gpt-oss-20b", "or-qwen3.6-27b", "or-gemma-4-31b-think")
MAIN_SPLITS = ("e1", "mfg", "itops", "fin")
MAIN_SYSTEMS = ("otf", "full_context_text", "rag", "pageindex")
# PageIndex processes per document (one question at a time each); Qwen's agent is slow (2026-10-26)
PI_SHARDS = {"e2_d01": 12, **{f"{s}_d0{i}": 3 for s in ("mfg", "itops") for i in range(1, 6)},
             **{f"fin_d0{i}": 4 for i in range(1, 4)}}
_lock = threading.Lock()


class Job:
    def __init__(self, phase, split, system, model, args=(), folder=None, limit=None, pattern=None, after=None,
                 copy_models_from=None):
        self.phase, self.split, self.system, self.model = phase, split, system, model
        self.args = list(args)                       # extra run.py arguments (--system-arg ...)
        self.folder = folder or system               # systems/<folder>__<model>
        self.limit = limit
        self.pattern = pattern or f"{split}_d[0-9]*"
        self.after = after                           # key of a job that must be done first
        self.copy_models_from = copy_models_from     # folder whose cached process models are copied in first

    @property
    def shard(self):
        return self.args[self.args.index("--shard") + 1] if "--shard" in self.args else None

    @property
    def key(self):
        return f"{self.pattern}|{self.folder}|{self.shard or ''}|{self.model}"

    @property
    def name(self):
        base = f"{self.pattern.replace('_d[0-9]*', '').replace('*', '')}__{self.model}__{self.folder}"
        return base + (f"__shard{self.shard.replace('/', 'of')}" if self.shard else "")


def plan(phases: list[str]) -> list[Job]:
    jobs = []
    for ph in phases:
        for m in MODELS:
            if ph == "dev":
                jobs.append(Job(ph, "pilot20", "otf_oracle", m, folder="otf_oracle", pattern="pilot20"))
                jobs.append(Job(ph, "pilot20", "otf", m, pattern="pilot20"))
                for dev in ("mfg_dev", "itops_dev", "fin_dev"):
                    jobs.append(Job(ph, dev, "otf", m, ["--system-arg", "use_library=false"], folder="otf_no_library",
                                    limit=4, pattern=dev))
            elif ph == "main":   # OTF first (longest: one document after another), then the baselines
                jobs += [Job(ph, s, "otf", m) for s in MAIN_SPLITS]
                jobs += [Job(ph, s, sy, m) for s in MAIN_SPLITS for sy in MAIN_SYSTEMS if sy != "otf"]
            elif ph == "e2":
                jobs += [Job(ph, "e2", sy, m) for sy in MAIN_SYSTEMS]
            elif ph == "ablations":
                main_otf = Job("main", "e1", "otf", m).key
                jobs += [Job(ph, "e1", "otf_oracle", m, folder="otf_oracle"),
                         Job(ph, "e1", "otf", m, ["--system-arg", "ablation=reading_only"],
                             folder="otf_reading_only", after=main_otf, copy_models_from="otf"),
                         Job(ph, "e1", "otf", m, ["--system-arg", "ablation=no_replay"],
                             folder="otf_no_replay", after=main_otf, copy_models_from="otf"),
                         Job(ph, "e1", "otf", m, ["--system-arg", "use_library=false"], folder="otf_no_library")]
    # PageIndex runs one question at a time per process (its connection clean-up is not safe across threads), so
    # it gets one job per document instead: the documents run in parallel
    out = []
    for j in jobs:
        if j.system != "pageindex":
            out.append(j)
            continue
        for d in sorted((ROOT / "runs").glob(j.pattern)):
            if not d.is_dir():
                continue
            n = PI_SHARDS.get(d.name, 1)        # a large document is also split across processes by question
            out += [Job(j.phase, j.split, j.system, j.model, j.args + (["--shard", f"{k}/{n}"] if n > 1 else []),
                        j.folder, j.limit, pattern=d.name) for k in range(n)]
    return out


def status(**event) -> None:
    event = {"time": datetime.now().isoformat(timespec="seconds"), **event}
    line = json.dumps(event)
    with _lock:
        print(line, flush=True)
        with (LOGS / "hosted__status.jsonl").open("a") as f:
            f.write(line + "\n")


def spend() -> float | None:
    """Total USD used by the OpenRouter key so far (None if the endpoint cannot be read)."""
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/key",
                                     headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
        return round(json.load(urllib.request.urlopen(req, timeout=30))["data"]["usage"], 4)
    except Exception:
        return None


def hosted_processes(kind: str) -> list[tuple[int, str]]:
    """(PID, command line) of other python processes that are hosted runners ("runner") or hosted run.py jobs
    ("job")."""
    like = "*run_hosted.py*" if kind == "runner" else "*run.py*--model or-*"
    ps = (f"Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | Where-Object {{ $_.CommandLine -like "
          f"'{like}' -and $_.ProcessId -ne {os.getpid()} -and $_.ProcessId -ne {os.getppid()} }} | "
          f"ForEach-Object {{ \"$($_.ProcessId)`t$($_.CommandLine)\" }}")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    return [(int(p), c) for p, _, c in (l.partition("	") for l in out.stdout.splitlines()) if p.strip().isdigit()]


def owns(job: Job, cmdline: str) -> bool:
    """Whether a running run.py command line is this job (same split pattern, system, model and extra arguments)."""
    m = re.search(r"--run (\S+) --system (\S+) --model (\S+) --workers \d+(.*)$", cmdline.strip())
    if not m:
        return False
    rest = m.group(4).split()
    return (m.group(1), m.group(2), m.group(3)) == (job.pattern, job.system, job.model) and         rest == job.args + (["--limit", str(job.limit)] if job.limit else [])


def run_dirs(job: Job) -> list[Path]:
    return sorted(p for p in (ROOT / "runs").glob(job.pattern) if p.is_dir())


def progress(job: Job) -> dict:
    """answered / expected over the job's documents (last row per question wins)."""
    expected = answered = errors = 0
    for d in run_dirs(job):
        uids = [json.loads(l)["uid"] for l in (d / "items.jsonl").read_text().splitlines()]
        if job.limit:
            uids = uids[:job.limit]
        if job.shard:
            k, n = (int(x) for x in job.shard.split("/"))
            uids = [u for i, u in enumerate(uids) if i % n == k]
        uids = set(uids)
        expected += len(uids)
        pred = d / "systems" / f"{job.folder}__{job.model}" / "predictions.jsonl"
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
        errors += sum("error" in r for r in rows.values())
    return {"expected": expected, "answered": answered, "errors": errors}


def done(job: Job) -> bool:
    p = progress(job)
    return p["expected"] > 0 and p["answered"] == p["expected"]


def needs_library_pass(job: Job) -> bool:
    return job.system == "otf" and job.folder == "otf" and job.phase != "dev"


def library_pass_logged(job: Job) -> bool:
    log = LOGS / "hosted__status.jsonl"
    return log.exists() and f'"event": "otf_library_pass", "job": "{job.name}"' in log.read_text()


TRANSIENT = re.compile(r"RateLimitError|APIConnectionError|APITimeoutError|InternalServerError|Error code: (402|429|5\d\d)")


def drop_transient_tool_errors(job: Job) -> int:
    """OTF answers whose tool step died on a transient endpoint error (429, 5xx, connection) fell back to reading
    for an infrastructure reason; drop them so run.py asks them again (harness fix, SPEC sec. 5, 2026-10-25)."""
    dropped = 0
    for d in run_dirs(job):
        pred = d / "systems" / f"{job.folder}__{job.model}" / "predictions.jsonl"
        if not pred.exists():
            continue
        lines = pred.read_text(encoding="utf-8").splitlines()
        keep = []
        for line in lines:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if TRANSIENT.search(str((r.get("trace") or {}).get("tool_error", ""))):
                dropped += 1
            else:
                keep.append(line)
        if len(keep) != len(lines):
            pred.write_text("".join(l + "\n" for l in keep), encoding="utf-8")
    return dropped


def copy_models(job: Job) -> None:
    """Start an ablation from the main run's final process models (same models, only the switch differs)."""
    for d in run_dirs(job):
        src = d / "systems" / f"{job.copy_models_from}__{job.model}" / "work" / "otf_model.json"
        dst = d / "systems" / f"{job.folder}__{job.model}" / "work" / "otf_model.json"
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def run_job(job: Job, workers: int, passes: int = 3) -> None:
    log_p = LOGS / "hosted" / f"{job.name}.log"
    if job.system == "pageindex":
        workers = 1

    def one_round():
        for p in range(1, passes + 1):
            prog = progress(job)
            if prog["expected"] and prog["answered"] == prog["expected"]:
                return
            if HALT.exists():
                status(event="halted", job=job.name)
                return
            if job.system.startswith("otf") and (n := drop_transient_tool_errors(job)):
                status(event="dropped_transient_tool_errors", job=job.name, n=n)
            status(event="pass_start", job=job.name, pass_no=p, **prog)
            t0 = time.time()
            cmd = [sys.executable, str(ROOT / "run.py"), "run", "--run", job.pattern, "--system", job.system,
                   "--model", job.model, "--workers", str(workers), *job.args]
            if job.limit:
                cmd += ["--limit", str(job.limit)]
            with log_p.open("a", encoding="utf-8") as log:
                log.write(f"\n=== {datetime.now().isoformat(timespec='seconds')} pass {p}: {' '.join(cmd)}\n")
                log.flush()
                rc = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode
            status(event="pass_end", job=job.name, pass_no=p, rc=rc, hours=round((time.time() - t0) / 3600, 2),
                   spend_usd=spend(), **progress(job))

    if job.copy_models_from:
        copy_models(job)
    one_round()
    if needs_library_pass(job):
        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "otf_library_pass.py"), "--split", job.split,
                              "--model", job.model], cwd=ROOT, capture_output=True, text=True)
        with (LOGS / "hosted" / f"{job.name}__library_pass.log").open("a", encoding="utf-8") as log:
            log.write(f"\n=== {datetime.now().isoformat(timespec='seconds')}\n{out.stdout}{out.stderr}")
        changed = int(next((l.split()[1] for l in out.stdout.splitlines() if l.startswith("CHANGED")), 0))
        status(event="otf_library_pass", job=job.name, documents_switched=changed)
        if changed:
            one_round()
    status(event="job_done" if done(job) else "job_incomplete", job=job.name, spend_usd=spend(), **progress(job))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", nargs="+", default=["main", "e2", "ablations"],
                    choices=["dev", "main", "e2", "ablations"])
    ap.add_argument("--models", nargs="+", default=list(MODELS))
    ap.add_argument("--systems", nargs="+", default=None, help="only these system folders (e.g. rag otf_oracle)")
    ap.add_argument("--workers", type=int, default=8, help="questions in flight per job")
    ap.add_argument("--jobs-per-model", type=int, default=6)
    ap.add_argument("--model-limits", nargs="*", default=[], metavar="ALIAS=JOBS,WORKERS",
                    help="per-model overrides, e.g. or-gemma-4-31b-think=3,4")
    ap.add_argument("--exclude", default=None, help="regex over job names to leave out")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stop", action="store_true", help="kill all hosted runners and their run.py jobs")
    a = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    jobs = [j for j in plan(a.phase) if j.model in a.models and (a.systems is None or j.folder in a.systems)
            and not (a.exclude and re.search(a.exclude, j.name))]
    limits = {m: (a.jobs_per_model, a.workers) for m in MODELS}
    for o in a.model_limits:
        m, v = o.split("=")
        limits[m] = tuple(int(x) for x in v.split(","))
    if a.stop:
        for kind in ("runner", "job"):
            for pid, _ in hosted_processes(kind):
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                print(f"killed {kind} {pid}")
        return
    if a.dry_run:
        for j in jobs:
            p = progress(j)
            print(f"[{j.phase:9s}] {j.name:55s} {len(run_dirs(j)):2d} docs  {p['answered']:5d}/{p['expected']:5d}"
                  + (f"  err {p['errors']}" if p["errors"] else "") + ("  done" if done(j) else ""))
        print(f"spend so far: ${spend()}")
        return
    (LOGS / "hosted").mkdir(parents=True, exist_ok=True)
    status(event="hosted_start", phases=a.phase, models=a.models, systems=a.systems, exclude=a.exclude,
           limits=limits, n_jobs=len(jobs), spend_usd=spend(), pid=os.getpid())
    for j in jobs:
        if j.system.startswith("otf") and (n := drop_transient_tool_errors(j)):
            status(event="dropped_transient_tool_errors", job=j.name, n=n)
    # an OTF job counts as finished only once its end-of-split library re-check ran (a stop can fall in between)
    finished: set[str] = {j.key for j in jobs if done(j) and (not needs_library_pass(j) or library_pass_logged(j))}
    running: dict[str, threading.Thread] = {}
    pending = [j for j in jobs if j.key not in finished]
    keys = {j.key for j in jobs}

    def worker(job):
        try:
            run_job(job, limits[job.model][1])
        except Exception as e:               # one job's failure does not stop the others
            status(event="job_failed", job=job.name, error=f"{type(e).__name__}: {e}")
        with _lock:
            finished.add(job.key)

    while pending or running:
        for k in [k for k, t in running.items() if not t.is_alive()]:
            del running[k]
        # jobs another runner (or an orphaned run.py) is answering right now are left alone until it ends
        elsewhere = [c for _, c in hosted_processes("job")]
        if HALT.exists() and not running:
            status(event="hosted_halted", pending=len(pending))
            return
        for job in list(pending):
            if HALT.exists():
                break
            busy = sum(1 for k in running if k.endswith(f"|{job.model}"))
            if busy >= limits[job.model][0]:
                continue
            if any(owns(job, c) for c in elsewhere):
                continue
            # shards 1..n-1 wait until shard 0 has built and cached the document's PageIndex index
            if job.shard and not job.shard.startswith("0/") and not (
                    ROOT / "runs" / job.pattern / "systems" / f"{job.folder}__{job.model}" / "work" /
                    "pageindex_index.json").exists():
                continue
            if job.after and (job.after not in finished if job.after in keys
                              else not done(Job("main", "e1", "otf", job.model))):
                continue
            pending.remove(job)
            t = threading.Thread(target=worker, args=(job,), daemon=True)
            running[job.key] = t
            t.start()
        time.sleep(20)
    status(event="hosted_done", spend_usd=spend())


if __name__ == "__main__":
    main()
