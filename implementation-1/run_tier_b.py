"""One command for the Tier B experiments (GraphRAG, ReAct-R, ReAct-C, ReCode on Qwen3.6-27B then Gemma-4-31B):

    python run_tier_b.py              # run or resume everything
    python run_tier_b.py --status     # where it is

Standard library only, so Windows Python 3.11 can start it before anything is installed. It creates the experiment
environment (.venv-tierb, pinned by requirements-tierb.lock), then runs tierb/pipeline.py inside it: data import
(checksums verified), preflight (WSL2 + GPU + vLLM, pinned checkpoints), pilot20 smoke tests and dev selection,
freeze (SPEC sec. 11), E1-core, validation and the delivery manifest (runs/tier_b/). Interrupt with Ctrl+C at any
time; running the same command again resumes without repeating finished work.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv-tierb"
LOCK = ROOT / "requirements-tierb.lock"


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_env() -> Path:
    py = venv_python()
    if not py.exists():
        print(f"[setup] creating the experiment environment {VENV.name} ...", flush=True)
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    want = hashlib.sha256(LOCK.read_bytes()).hexdigest()
    stamp = VENV / ".lock-sha256"
    if not stamp.exists() or stamp.read_text().strip() != want:
        print("[setup] installing pinned dependencies (first run only, a few minutes) ...", flush=True)
        subprocess.check_call([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q",
                               "-r", str(LOCK)])
        stamp.write_text(want)
    return py


def main() -> int:
    if sys.version_info[:2] != (3, 11):
        print(f"run_tier_b.py needs Python 3.11 (this is {sys.version.split()[0]}). On Windows: "
              f"py -3.11 run_tier_b.py", file=sys.stderr)
        return 2
    try:
        py = ensure_env()
    except subprocess.CalledProcessError as e:
        print(f"[setup] failed: {e}. Check the internet connection and run the command again.", file=sys.stderr)
        return 2
    env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    p = subprocess.Popen([str(py), "-m", "tierb.pipeline", *sys.argv[1:]], cwd=ROOT, env=env)
    while True:
        try:
            return p.wait()
        except KeyboardInterrupt:      # the pipeline gets Ctrl+C too and shuts down cleanly; wait for it
            continue


if __name__ == "__main__":
    sys.exit(main())
