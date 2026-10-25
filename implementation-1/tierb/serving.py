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
# Scripts go to bash on stdin, never on the command line: `wsl -- bash -c "..."` runs the line through a shell first,
# which expands $PATH (Windows PATH entries like "Program Files (x86)") before bash sees the script.
WSL_BASH = ["wsl", "-d", DISTRO, "--exec", "bash", "-s"]
# Kernel choice only (like serve.sh's TRITON_ATTN): vLLM >= 0.30 samples with FlashInfer's top-k/top-p kernel, which
# JIT-compiles with nvcc on first use; WSL has no CUDA toolkit (SPEC sec. 1-2). vLLM's own PyTorch sampler applies
# the same top-k/top-p/temperature.
SERVE_ENV = {"VLLM_USE_FLASHINFER_SAMPLER": "0"}
# If the KV cache for one full 131,072-token request does not fit next to the weights, serve with this context
# instead. Tier B requests stay far below it (longest: 12-call ReAct, ~70k tokens incl. the 16,384 output cap), so
# answers are unaffected; a longer request would be scored as context overflow. Recorded in provenance.
REDUCED_MAX_MODEL_LEN = 98304


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
        self.max_model_len: int | None = None
        self.model: str | None = None
        self.external = False

    # ------------------------------------------------------------------ WSL helpers
    def wsl(self, cmd: str, timeout: float = 600, check: bool = True) -> str:
        if not shutil.which("wsl") and not shutil.which("wsl.exe"):
            raise ServingError("WSL is not available. Install WSL2 with Ubuntu-24.04 from an administrator "
                               "PowerShell: `wsl --install -d Ubuntu-24.04`, reboot, open Ubuntu once to create "
                               "your user, then run `python run_tier_b.py` again.")
        try:
            p = subprocess.run(WSL_BASH, input=cmd.encode(), capture_output=True, timeout=timeout)
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
        self.ensure_build_tools()
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
        return {"gpu": gpu, **info, "wsl_free_gb": free_gb, "distro": DISTRO, "serve_sh": "scripts/serve.sh",
                "serve_env": SERVE_ENV}

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
            p = subprocess.run(WSL_BASH, input=script.encode(), stdout=f, stderr=subprocess.STDOUT, timeout=7200)
        if p.returncode != 0:
            raise ServingError(f"vLLM installation in WSL failed; see {log}:\n{_tail(log)}")

    def ensure_build_tools(self) -> None:
        """Triton JIT-compiles a C helper when vLLM starts: it needs gcc and the venv Python's headers. A fresh
        Ubuntu has neither; install them as root (`wsl -u root` needs no password)."""
        check = (f"command -v gcc >/dev/null && test -f \"$({VLLM_VENV}/bin/python -c "
                 "'import sysconfig; print(sysconfig.get_paths()[\"include\"])')/Python.h\" && echo yes || echo no")
        if self.wsl(check, timeout=120).strip().endswith("yes"):
            return
        self.log("[serving] installing the C compiler and Python headers in WSL (build-essential, python3-dev)")
        log = self.logs / "build_tools_install.log"
        script = ("set -e; export DEBIAN_FRONTEND=noninteractive; apt-get update; "
                  "apt-get install -y build-essential python3-dev")
        with log.open("ab") as f:
            p = subprocess.run(["wsl", "-d", DISTRO, "-u", "root", "--exec", "bash", "-s"], input=script.encode(),
                               stdout=f, stderr=subprocess.STDOUT, timeout=3600)
        if p.returncode != 0 or not self.wsl(check, timeout=120).strip().endswith("yes"):
            raise ServingError(f"could not install build-essential/python3-dev in WSL; see {log}. Manually: "
                               f"wsl -d {DISTRO} -u root -- apt-get install -y build-essential python3-dev\n{_tail(log)}")

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
            p = subprocess.run(WSL_BASH, input=f"{VLLM_VENV}/bin/python -c {_q(code)} 2>>/tmp/tierb_download.err"
                               .encode(), stdout=subprocess.PIPE, stderr=f, timeout=4 * 3600)
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

    def gpu_memory(self) -> str:
        out = self.wsl("nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader", check=False)
        return out.strip() or "unknown"

    def start(self, model: str, extra: tuple[str, ...] = ()) -> None:
        spec = get_model(model)
        log = self.logs / f"server__{model}.log"
        pidf = f"/tmp/tierb_vllm_{os.getpid()}.pid"
        # CRLF-safe (a Windows checkout may convert line endings); exec keeps the PID through serve.sh's own exec
        sh = _q(wsl_path(ROOT / "scripts" / "serve.sh"))
        env = " ".join(f"export {k}={v};" for k, v in SERVE_ENV.items())
        args = " ".join(_q(a) for a in (model, *extra))
        cmd = f"{env} echo $$ > {pidf}; exec bash -c \"$(sed 's/\\r$//' {sh})\" serve.sh {args}"
        used = self.gpu_memory()
        self.log(f"[serving] starting vLLM for {model} (GPU memory already in use: {used}; log: {log})")
        f = log.open("ab")
        offset = log.stat().st_size               # read only this attempt's lines when diagnosing a failure
        self.proc = subprocess.Popen(WSL_BASH, stdin=subprocess.PIPE, stdout=f, stderr=subprocess.STDOUT)
        self.proc.stdin.write((cmd + "\n").encode())
        self.proc.stdin.close()
        self.model, self.external = model, False
        self.max_model_len = REDUCED_MAX_MODEL_LEN if extra else 131072
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
                tail = log.read_bytes()[offset:].decode("utf-8", "replace")
                if "larger than the available KV cache memory" in tail and not extra:
                    self.log(f"[serving] the KV cache for a full 131,072-token request does not fit; restarting "
                             f"{model} with --max-model-len {REDUCED_MAX_MODEL_LEN} (Tier B requests stay well "
                             "below this; recorded in provenance)")
                    self.proc, self.pid = None, None
                    self.max_model_len = REDUCED_MAX_MODEL_LEN
                    return self.start(model, ("--max-model-len", str(REDUCED_MAX_MODEL_LEN)))
                if "larger than the available KV cache memory" in tail:
                    need = next((l.split("ValueError: ", 1)[1][:300] for l in tail.splitlines()
                                 if "ValueError: To serve" in l), "")
                    raise ServingError(
                        f"vLLM for {model} loaded but has too little GPU memory left for its KV cache at the frozen "
                        f"131,072-token context ({need}). Other programs were already using {used} of GPU memory "
                        "before the start. Close GPU users (Ollama / LM Studio models, Docker Desktop, browsers and "
                        "other GPU-accelerated apps; `nvidia-smi` in cmd lists them), then run the same command again.")
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


def is_hosted(model: str) -> bool:
    """Hosted OpenAI-compatible endpoint (e.g. OpenRouter): the model entry names an API-key env var."""
    return bool(get_model(model).api_key_env)


class Servers:
    """Routes each model to its serving: hosted aliases (or-*) need no local server; everything else goes to
    the local vLLM server (WSL, or the mock in tests)."""

    def __init__(self, local):
        self.local = local
        self.log = local.log

    @property
    def max_model_len(self):
        return getattr(self.local, "max_model_len", None)

    def preflight(self, models: list[str]) -> dict:
        from clevrer_bench.llm import endpoint_key
        info = {}
        for m in [m for m in models if is_hosted(m)]:
            try:
                endpoint_key(get_model(m))
            except RuntimeError as e:
                raise ServingError(f"{e}. Put the key in implementation-1\\.env, e.g. OPENROUTER_API_KEY=sk-or-...")
            info[m] = {"hosted": get_model(m).base_url}
        local = [m for m in models if not is_hosted(m)]
        if local:
            info.update(self.local.preflight(local))
        return info

    def ensure_checkpoint(self, model: str) -> dict:
        if not is_hosted(model):
            return self.local.ensure_checkpoint(model)
        spec = get_model(model)
        return {"hosted": spec.base_url, "served_name": spec.served_name,
                "provider": spec.extra_body.get("provider"), "max_model_len": spec.context_len}

    def ensure(self, model: str) -> None:
        if not is_hosted(model):
            return self.local.ensure(model)
        spec = get_model(model)
        for attempt in range(6):                     # transient network trouble: wait, then give up clearly
            ids = served_models(spec.base_url)
            if ids is not None:
                if spec.served_name not in ids:
                    raise ServingError(f"{spec.base_url} does not list {spec.served_name}")
                return
            time.sleep(30)
        raise ServingError(f"cannot reach {spec.base_url} (checked for 3 minutes); check the internet connection")

    def stop(self) -> None:
        self.local.stop()
