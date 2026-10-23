"""Model serving for the Tier B pipeline: vLLM inside WSL2 Ubuntu-24.04, started with the repository's own
scripts/serve.sh (flags are never translated to another stack). One model on the GPU at a time.

The pipeline only ever stops a server it started itself (tracked by the PID that serve.sh runs as). A server it
did not start is reused if it serves the expected model, and otherwise left alone with an actionable error.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from clevrer_bench.llm import get_model

ROOT = Path(__file__).resolve().parent.parent
DISTRO = "Ubuntu-24.04"
VLLM_VENV = "~/venvs/vllm"
VLLM_VERSION = "0.32.0"               # installed only when the WSL venv is missing; an existing >= 0.19 is kept
MIN_VLLM = (0, 19)
# SPEC sec. 2: checkpoint revisions. serve.sh serves the repo's default branch, so it must resolve to these.
CHECKPOINTS = {"qwen3.6-27b": ("nvidia/Qwen3.6-27B-NVFP4", "0893e1606ff3d5f97a441f405d5fc541a6bdf404"),
               "gemma-4-31b-think": ("RedHatAI/gemma-4-31B-it-NVFP4", "5df75ccad9b74546f5be758a2a68acc2e16bbc9b")}
READY_TIMEOUT_S = 3600


class ServingError(RuntimeError):
    """Stops the pipeline with an actionable message."""


def served_models(base_url: str) -> list[str] | None:
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/models", timeout=5) as r:
            return [m["id"] for m in json.load(r)["data"]]
    except Exception:
        return None


def _tail(p: Path, n: int = 25) -> str:
    try:
        return "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def wsl_path(p: Path) -> str:
    """C:\\a b\\c -> /mnt/c/a b/c (what `wslpath -a` returns for a drive path)."""
    s = str(Path(p).resolve())
    if len(s) > 1 and s[1] == ":":
        return "/mnt/" + s[0].lower() + s[2:].replace("\\", "/")
    return s


def _q(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


class WSLServer:
    def __init__(self, logs: Path, log=print):
        self.logs, self.log = logs, log
        self.proc: subprocess.Popen | None = None
        self.pid: int | None = None        # PID (inside WSL) of the vLLM server this run started
        self.model: str | None = None
        self.external = False

    # ------------------------------------------------------------------ WSL helpers
    def wsl(self, cmd: str, timeout: float = 600, check: bool = True) -> str:
        if not shutil.which("wsl") and not shutil.which("wsl.exe"):
            raise ServingError("WSL is not available. Install WSL2 with Ubuntu-24.04 from an administrator "
                               "PowerShell: `wsl --install -d Ubuntu-24.04`, reboot, open Ubuntu once to create "
                               "your user, then run `python run_tier_b.py` again.")
        try:
            p = subprocess.run(["wsl", "-d", DISTRO, "--", "bash", "-c", cmd], capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ServingError(f"WSL did not answer within {timeout:.0f}s ({cmd[:80]}). If {DISTRO} was never "
                               "opened, open it once from the Start menu to finish its first-run setup, then re-run.")
        out = p.stdout.decode("utf-8", "replace")
        if check and p.returncode != 0:
            raise ServingError(f"WSL command failed ({p.returncode}): {cmd[:200]}\n"
                               f"{(out + p.stderr.decode('utf-8', 'replace'))[-2000:]}")
        return out

    def distros(self) -> list[str]:
        p = subprocess.run(["wsl", "-l", "-q"], capture_output=True, timeout=60)
        raw = p.stdout
        text = raw.decode("utf-16-le", "replace") if raw[:2] == b"\xff\xfe" or b"\x00" in raw[:20] else raw.decode()
        return [d.strip().strip("\x00") for d in text.replace("\x00", "").splitlines() if d.strip()]

    # ------------------------------------------------------------------ preflight
    def preflight(self, models: list[str]) -> dict:
        """WSL, GPU, vLLM (installed if missing) and disk. Returns what was found, for provenance."""
        if os.name != "nt":
            raise ServingError("The serving stack is vLLM inside WSL2 (SPEC sec. 1); run this on the Windows PC.")
        if not shutil.which("wsl"):
            self.wsl("true")                                    # raises the install instructions
        if DISTRO not in self.distros():
            raise ServingError(f"WSL distribution {DISTRO} not found (have: {self.distros()}). Install it with "
                               f"`wsl --install -d {DISTRO}`, open it once to create your user, then re-run.")
        gpu = self.wsl("nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader",
                       check=False).strip()
        if not gpu or "failed" in gpu.lower():
            raise ServingError("No NVIDIA GPU visible inside WSL (`nvidia-smi` failed). Update the Windows NVIDIA "
                               "driver (WSL support is built in), run `wsl --update`, then re-run.")
        self.ensure_vllm()
        info = json.loads(self.wsl(f"{VLLM_VENV}/bin/python -c \"import json, vllm, torch; print(json.dumps("
                                   "{'vllm': vllm.__version__, 'torch': torch.__version__, "
                                   "'cuda': torch.version.cuda, 'gpu_ok': torch.cuda.is_available()}))\"",
                                   timeout=600).strip().splitlines()[-1])
        if tuple(int(x) for x in info["vllm"].split(".")[:2]) < MIN_VLLM:
            raise ServingError(f"vLLM {info['vllm']} in {VLLM_VENV} is older than 0.19 (SPEC sec. 1). Upgrade it: "
                               f"wsl -d {DISTRO} -- {VLLM_VENV}/bin/pip install -U vllm=={VLLM_VERSION}")
        if not info["gpu_ok"]:
            raise ServingError("torch inside the WSL vLLM venv cannot see the GPU (torch.cuda.is_available() is "
                               "False). Update the NVIDIA driver and run `wsl --update`.")
        free_gb = int(self.wsl("df -BG --output=avail ~ | tail -1").strip().rstrip("G") or 0)
        return {"gpu": gpu, **info, "wsl_free_gb": free_gb, "distro": DISTRO, "serve_sh": "scripts/serve.sh"}

    def ensure_vllm(self) -> None:
        if self.wsl(f"test -x {VLLM_VENV}/bin/vllm && echo yes || echo no", timeout=60).strip() == "yes":
            return
        self.log(f"[serving] {VLLM_VENV} not found in WSL: installing vLLM {VLLM_VERSION} (several GB, ~10-20 min)")
        script = (f"set -e; export PATH=$HOME/.local/bin:$PATH; "
                  f"command -v uv >/dev/null || (curl -LsSf https://astral.sh/uv/install.sh | sh); "
                  f"uv venv {VLLM_VENV} --python 3.12 --seed; "
                  f"uv pip install --python {VLLM_VENV}/bin/python vllm=={VLLM_VERSION} --torch-backend=auto")
        log = self.logs / "vllm_install.log"
        with log.open("ab") as f:
            p = subprocess.run(["wsl", "-d", DISTRO, "--", "bash", "-c", script], stdout=f, stderr=subprocess.STDOUT,
                               timeout=7200)
        if p.returncode != 0:
            raise ServingError(f"vLLM installation in WSL failed; see {log}:\n{_tail(log)}")

    def ensure_checkpoint(self, model: str) -> dict:
        """Download the model (if not cached) and check the default branch resolves to the SPEC revision."""
        if model not in CHECKPOINTS:
            raise ServingError(f"no pinned checkpoint for {model}")
        repo, rev = CHECKPOINTS[model]
        free_gb = int(self.wsl("df -BG --output=avail ~ | tail -1").strip().rstrip("G") or 0)
        self.log(f"[serving] checking checkpoint {repo} (download if needed; WSL disk free {free_gb} GB)")
        code = ("import json, sys; from pathlib import Path; from huggingface_hub import snapshot_download; "
                f"p = snapshot_download({repo!r}); print(json.dumps({{'path': p, 'revision': Path(p).name}}))")
        log = self.logs / f"download__{model}.log"
        with log.open("ab") as f:
            p = subprocess.run(["wsl", "-d", DISTRO, "--", "bash", "-c",
                                f"{VLLM_VENV}/bin/python -c {_q(code)} 2>>/tmp/tierb_download.err"],
                               stdout=subprocess.PIPE, stderr=f, timeout=4 * 3600)
        out = p.stdout.decode("utf-8", "replace").strip().splitlines()
        if p.returncode != 0 or not out:
            err = self.wsl("tail -20 /tmp/tierb_download.err", check=False)
            raise ServingError(f"could not download {repo}. Check the internet connection and Hugging Face access "
                               f"(`huggingface-cli login` inside WSL if the model needs it).\n{err}")
        got = json.loads(out[-1])
        if got["revision"] != rev:
            raise ServingError(f"{repo} resolves to revision {got['revision']}, but SPEC sec. 2 pins {rev}. "
                               "The upstream model changed; ask the experiment owner before continuing.")
        return {"repo": repo, "revision": got["revision"], "verified_against_spec": True}

    # ------------------------------------------------------------------ start / stop
    def ensure(self, model: str) -> None:
        """Make sure `model` is being served (start it if needed); check identity and readiness."""
        spec = get_model(model)
        ids = served_models(spec.base_url)
        if ids is not None and spec.served_name in ids:
            if self.model != model and not self.owns_running():
                self.external, self.model = True, model
                self.log(f"[serving] reusing a server already serving {spec.served_name} (not started by this run;"
                         " it will not be stopped)")
            return
        if ids is not None:                         # something else answers on the port
            if self.owns_running():
                self.stop()
            else:
                raise ServingError(f"{spec.base_url} is serving {ids}, not {spec.served_name}, and this run did not "
                                   "start that server. Stop it yourself (it is not ours to stop), then re-run.")
        elif self.owns_running():                   # our server is up but not answering: restart it
            self.stop()
        self.start(model)

    def owns_running(self) -> bool:
        return self.pid is not None and self.proc is not None and self.proc.poll() is None

    def start(self, model: str) -> None:
        spec = get_model(model)
        log = self.logs / f"server__{model}.log"
        pidf = f"/tmp/tierb_vllm_{os.getpid()}.pid"
        # CRLF-safe (a Windows checkout may convert line endings); exec keeps the PID through serve.sh's own exec
        sh = _q(wsl_path(ROOT / "scripts" / "serve.sh"))
        cmd = f"echo $$ > {pidf}; exec bash -c \"$(sed 's/\\r$//' {sh})\" serve.sh {model}"
        self.log(f"[serving] starting vLLM for {model} (log: {log})")
        f = log.open("ab")
        self.proc = subprocess.Popen(["wsl", "-d", DISTRO, "--", "bash", "-c", cmd], stdout=f,
                                     stderr=subprocess.STDOUT)
        self.model, self.external = model, False
        t0 = time.time()
        while time.time() - t0 < READY_TIMEOUT_S:
            if self.pid is None:
                got = self.wsl(f"cat {pidf} 2>/dev/null", check=False).strip()
                self.pid = int(got) if got.isdigit() else None
            ids = served_models(spec.base_url)
            if ids:
                if spec.served_name not in ids:
                    raise ServingError(f"server answers but serves {ids}, expected {spec.served_name}")
                self.log(f"[serving] {model} ready after {time.time() - t0:.0f}s")
                return
            if self.proc.poll() is not None:
                raise ServingError(f"vLLM for {model} exited with code {self.proc.returncode}. Last log lines "
                                   f"({log}):\n{_tail(log)}")
            time.sleep(10)
        self.stop()
        raise ServingError(f"vLLM for {model} was not ready after {READY_TIMEOUT_S}s; see {log}")

    def stop(self) -> None:
        """Stop the server this run started (never anything else)."""
        if self.external or self.pid is None:
            self.proc, self.pid, self.model = None, None, (None if not self.external else self.model)
            return
        spec = get_model(self.model) if self.model else None
        self.log(f"[serving] stopping our vLLM server (WSL pid {self.pid})")
        self.wsl(f"kill -INT {self.pid} 2>/dev/null", check=False, timeout=60)
        for _ in range(60):
            alive = self.wsl(f"kill -0 {self.pid} 2>/dev/null && echo up || echo down", check=False).strip()
            if alive == "down" and (spec is None or served_models(spec.base_url) is None):
                break
            time.sleep(2)
        else:
            self.wsl("killtree() { for c in $(pgrep -P $1); do killtree $c; done; kill -9 $1 2>/dev/null; }; "
                     f"killtree {self.pid}", check=False, timeout=60)
        if self.proc is not None:
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc, self.pid, self.model = None, None, None


class MockServer:
    """tests/mock_vllm.py in place of vLLM (end-to-end tests of the pipeline without a GPU)."""

    def __init__(self, logs: Path, log=print):
        self.logs, self.log = logs, log
        self.proc: subprocess.Popen | None = None
        self.model: str | None = None

    def preflight(self, models):
        return {"mock": True}

    def ensure_checkpoint(self, model):
        return {"mock": True}

    def ensure(self, model: str) -> None:
        spec = get_model(model)
        ids = served_models(spec.base_url)
        if ids and spec.served_name in ids:
            return
        self.stop()
        port = spec.base_url.split(":")[-1].split("/")[0]
        f = (self.logs / f"server__{model}.log").open("ab")
        self.proc = subprocess.Popen([sys.executable, str(ROOT / "tests" / "mock_vllm.py"), "--port", port,
                                      "--served", spec.served_name], stdout=f, stderr=subprocess.STDOUT)
        for _ in range(100):
            if served_models(spec.base_url):
                self.model = model
                return
            time.sleep(0.1)
        raise ServingError("mock server did not start")

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        self.proc, self.model = None, None
