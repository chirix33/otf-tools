"""ReCode (Yu et al., ICML 2026; FoundationAgents/ReCode @ 6e7223f, vendored in third_party/ReCode) as a QA system.

The upstream agent is used unchanged (EXPAND prompt, recursive placeholder expansion, block splitting and
validation, NeedExpansion handling); this adapter supplies:
- a `docqa` environment whose primitive actions are search[...], list_sections[...], read_section[...] and
  answer[...] (the ReAct-C primitives; `doc` and the OTF helpers are Python variables of the code itself);
- an Executor whose code blocks all run in the OTF sandbox: one isolated `python -I` process per question,
  every block checked by otf.sandbox.check (import whitelist, forbidden names, no dunder attributes) and limited
  to otf.sandbox.TIMEOUT_S of compute; `run(...)` inside the sandbox is relayed to the environment;
- model calls through the metered client (frozen sampling; every recursive expansion and re-expansion counts
  toward the 12-call cap); max recursion depth 6.
The environment's success flag means "an answer was submitted"; it never looks at gold labels.
Few-shot examples come from pilot20 only (baseline_prompts.RECODE_FEWSHOTS, filled at run time).
"""
from __future__ import annotations

import ast
import asyncio
import json
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from otf import sandbox

from ..data import QAItem
from ..prompts import ANSWER_INSTRUCTIONS
from . import baseline_prompts as P
from .base import Document, SetupResult
from .metered import CallCapReached, ContextOverflow, MeteredChat
from .rag import RAGSystem
from .tierb_common import ROOT, TierBSystem, file_sha, front_matter, load_nav, outline, render_node

RECODE_DIR = ROOT / "third_party" / "ReCode"
RECODE_COMMIT = "6e7223f71281d914762e78d7bbcf6446d362ecbc"
MAX_DEPTH = 6
MAX_REWRITE = 5               # upstream default
MAX_AGENT_STEPS = 400         # guard against a tree that never finishes (each step runs one code node)
OBS_CHARS = 16000
RAG_CACHE = ROOT / ".cache" / "tierb_rag_index"
BASE_NAMES = ("doc", "run", "re", "node_by_title", "children", "scope_nodes")

SESSION = r'''
import contextlib, io, json, re, sys
sys.stdout.reconfigure(encoding="utf-8"); sys.stdin.reconfigure(encoding="utf-8")
_out, _in = sys.stdout, sys.stdin
with open(sys.argv[1], encoding="utf-8") as _f:
    _doc = json.load(_f)
ns = {"__name__": "recode_block", "doc": _doc, "re": re}
exec(HELPERS, ns)                                       # OTF sandbox helpers (prepended to this script)
_base = set(ns) | {"run", "__builtins__"}

def _send(o):
    _out.write(json.dumps(o, default=str) + "\n")
    _out.flush()

def _recv():
    line = _in.readline()
    if not line:
        sys.exit(0)
    return json.loads(line)

def run(action):
    _send({"op": "call", "action": str(action)})
    res = _recv().get("result", "")
    if res is not None:
        print(res)                                      # upstream Executor prints every observation
    return res

ns["run"] = run
while True:
    msg = _recv()
    ns.update(msg.get("vars") or {})
    buf, ok, err = io.StringIO(), True, ""
    try:
        with contextlib.redirect_stdout(buf):
            exec(msg["code"], ns)
    except NameError as e:
        ok = False
        m = re.search(r"name '(.+?)' is not defined", str(e))
        err = (f"NeedExpansion: `{m.group(1)}` needs to be expanded." if m and f"{m.group(1)}(" in msg["code"]
               else f"NameError: {e}")
    except Exception as e:
        ok, err = False, f"{e.__class__.__name__}: {e}"
    out = {}
    for k, v in list(ns.items()):
        if k in _base or k.startswith("_") or callable(v) or type(v).__name__ == "module":
            continue
        try:
            json.dumps(v)
            out[k] = v
        except (TypeError, ValueError):
            out[k] = repr(v)[:4000]
    _send({"op": "done", "ok": ok, "stdout": [l for l in buf.getvalue().splitlines() if l.strip()],
           "error": err, "vars": out})
'''


def _import_recode():
    if str(RECODE_DIR) not in sys.path:
        sys.path.insert(0, str(RECODE_DIR))
    from agents.recode.agent import ReCodeAgent
    from base.environment import Env
    from utils.executor import Executor
    return ReCodeAgent, Env, Executor


def _normalize_answer(arg: str) -> str:
    """answer[...] may carry JSON or a Python dict literal (code often builds a dict); store it as JSON."""
    s = arg.strip()
    for parse in (json.loads, ast.literal_eval):
        try:
            return json.dumps(parse(s))
        except (ValueError, SyntaxError, TypeError):
            continue
    return s


class SandboxSession:
    """A persistent sandboxed interpreter for one question. Variables persist between blocks (as in upstream's
    Executor); `run(action)` calls are answered by `handler` on the host."""

    def __init__(self, map_path: Path, handler):
        self.map_path, self.handler = Path(map_path), handler
        self.proc = None
        self.td = tempfile.TemporaryDirectory()
        self.script = Path(self.td.name) / "session.py"
        self.script.write_text(f"HELPERS = {sandbox.HELPERS!r}\n" + SESSION, encoding="utf-8")

    def _start(self):
        self.proc = subprocess.Popen([sys.executable, "-I", str(self.script), str(self.map_path.resolve())],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, encoding="utf-8", cwd=self.td.name)
        self.q: queue.Queue = queue.Queue()
        proc, q = self.proc, self.q

        def pump():
            for line in proc.stdout:
                q.put(line)
            q.put(None)
        threading.Thread(target=pump, daemon=True).start()

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self.proc = None

    def execute(self, code: str, new_vars: dict) -> dict:
        try:
            sandbox.check(code)
        except sandbox.CodeRejected as e:
            return {"ok": False, "stdout": [], "error": f"rejected: {e}", "vars": {}}
        if self.proc is None or self.proc.poll() is not None:
            self._start()
        self.proc.stdin.write(json.dumps({"code": code, "vars": new_vars}) + "\n")
        self.proc.stdin.flush()
        budget = float(sandbox.TIMEOUT_S)              # sandbox compute time; host-side actions are not counted
        while True:
            t = time.time()
            try:
                line = self.q.get(timeout=max(budget, 0.01))
            except queue.Empty:
                self.close()
                return {"ok": False, "stdout": [], "error": f"timeout after {sandbox.TIMEOUT_S}s", "vars": {},
                        "restarted": True}
            budget -= time.time() - t
            if line is None:
                err = (self.proc.stderr.read() or "").strip().splitlines()[-5:] if self.proc else []
                self.close()
                return {"ok": False, "stdout": [], "error": "sandbox exited: " + " | ".join(err), "vars": {},
                        "restarted": True}
            msg = json.loads(line)
            if msg.get("op") == "call":
                result = self.handler(msg["action"])
                self.proc.stdin.write(json.dumps({"result": result}) + "\n")
                self.proc.stdin.flush()
            elif msg.get("op") == "done":
                return msg

    def __del__(self):
        try:
            self.close()
            self.td.cleanup()
        except Exception:
            pass


class ReCodeSystem(TierBSystem):
    base_name = "recode"

    def __init__(self, model: str, reasoning_effort=None, slot: int = 1, out_name: str | None = None,
                 runs_root: str | None = None, **kwargs):
        super().__init__(model, reasoning_effort, slot, out_name)
        self.llm = MeteredChat(self.spec, self.reasoning_effort)
        self.actions_text = P.RECODE_ACTIONS[self.slot].replace("{modules}", ", ".join(sorted(sandbox.ALLOWED_MODULES)))
        self.fewshots = build_fewshots(Path(runs_root or ROOT / "runs") / "pilot20")

    def method_config(self) -> dict:
        return {"actions": self.actions_text, "fewshots_sha": file_sha_text(self.fewshots), "max_depth": MAX_DEPTH,
                "max_rewrite": MAX_REWRITE, "search_top_k": 5, "observation_chars": OBS_CHARS,
                "sandbox_timeout_s": sandbox.TIMEOUT_S, "sandbox_modules": sorted(sandbox.ALLOWED_MODULES),
                "expand_prompt_sha": file_sha_text(_expand_prompt())}

    def upstream(self) -> dict:
        return {"repo": "https://github.com/FoundationAgents/ReCode", "commit": RECODE_COMMIT,
                "vendored": str(RECODE_DIR.relative_to(ROOT).as_posix())}

    def setup(self, doc: Document) -> SetupResult:
        t = time.time()
        self.open_ledger(doc)
        self.rag = RAGSystem(self.model, self.reasoning_effort)
        shared = RAG_CACHE / file_sha(doc.pdf_path)[:16]
        shared.mkdir(parents=True, exist_ok=True)
        info = self.rag.setup(Document(doc.pdf_path, doc.manifest, shared)).info
        self.nav, self.map_path = load_nav(doc)
        self.front = front_matter(self.nav)
        u, unknown = self.ledger.setup_usage()
        return SetupResult(u, time.time() - t, {**info, "nodes": len(self.nav["nodes"]), "max_depth": MAX_DEPTH,
                                                "usage_unknown_calls": unknown, "config_hash": self.config_hash()})

    def _episode(self, instructions: str, prompt: str) -> tuple[str, dict]:
        ReCodeAgent, Env, Executor = _import_recode()
        system = self
        observation = f"{P.FRONT_MATTER.format(front=self.front)}\n\nOUTLINE (top-level nodes):\n{outline(self.nav)}"
        instruction = f"{instructions}\n\n{prompt}"

        class DocQAEnv(Env):
            id = "docqa"

            def __init__(self):
                self.answer, self.actions = None, []

            def reset(self, running_config=None, id=None):
                return {"observations": [observation], "env_name": "docqa", "env": self}

            async def _run(self, action: str):
                self._step_count += 1
                if action == "[FINISH]":
                    self._done = True
                    return ""
                m = re.match(r"^\s*(\w+)\s*\[(.*)\]\s*$", action or "", flags=re.S)
                if not m:
                    obs = ("error: unknown action format; use search[...], list_sections[...], read_section[...] "
                           "or answer[...]")
                else:
                    name, arg = m.group(1), m.group(2)
                    if name == "answer":
                        self.answer = _normalize_answer(arg)
                        self._done = self._success = True     # submitted; never compared with gold here
                        obs = "answer submitted"
                    elif name == "search":
                        obs = system.rag.retrieve(arg, 5)[1]
                    elif name == "list_sections":
                        obs = outline(system.nav, arg.strip() or None)
                    elif name == "read_section":
                        obs = render_node(system.nav, arg)
                    else:
                        obs = f"error: unknown action {name!r}"
                obs = obs[:OBS_CHARS]
                self.actions.append({"action": action[:2000], "observation": obs[:2000]})
                return obs

            def report(self):
                return {"steps": self._step_count, "answered": self.answer is not None}

        class SandboxExecutor(Executor):
            def __init__(self, env):
                super().__init__(env=env, if_run_print=False)
                self.session = SandboxSession(system.map_path, self._host_run)
                self._dirty: dict = {}
                self.blocks: list = []

            def set_var(self, key, value):
                super().set_var(key, value)
                self._dirty[key] = value

            def _host_run(self, action: str) -> str:
                result = self._submit_coro(self.env.run(action))
                self.actions.append(action)
                return "\n".join(result) if isinstance(result, list) else str(result)

            def execute(self, code: str) -> dict:
                new, self._dirty = self._dirty, {}
                r = self.session.execute(code, new)
                if r.get("restarted"):        # variables of a killed session are re-sent with the next block
                    self._dirty = {**self._variables}
                for k, v in (r.get("vars") or {}).items():
                    self._variables[k] = v
                self.blocks.append({"code": code[:4000], "ok": r["ok"], "error": r.get("error", "")[:1000]})
                return {"code": code, "stdout": r.get("stdout", []), "error": r.get("error", ""),
                        "success": bool(r["ok"])}

        class Logger:
            def info(self, *a, **k):
                pass
            warning = error = debug = info

        class LLMAdapter:
            spent = 0.0

            async def __call__(self, prompt: str, **kw):
                resp = await asyncio.to_thread(system.llm.chat, [{"role": "user", "content": prompt}],
                                               source="recode")
                return (resp.choices[0].message.content or ""), 0.0

        class DocQAAgent(ReCodeAgent):
            def __init__(self):            # upstream __init__ builds its own LLM client from a profile file
                self.logger, self.llm, self.task_type = Logger(), LLMAdapter(), None
                self.root = self.current_node = self.previous_node = None
                self.is_start = False

            def _load_resources(self):
                self.available_actions, self.fewshots = system.actions_text, system.fewshots

            def _init_code_tree(self, obs):
                from agents.recode.utils import CodeNode
                self.executor.set_var("observation", observation)
                self.executor.set_var("instruction", instruction)
                self.root = CodeNode(code="solve(instruction, observation)")
                self.current_node = self.root

        env = DocQAEnv()
        agent = DocQAAgent()
        agent.executor = SandboxExecutor(env)
        init = env.reset()
        agent.reset({"max_depth": MAX_DEPTH, "max_rewrite": MAX_REWRITE}, init)
        outcome = "no_answer"

        async def drive():
            obs = init["observations"]
            for _ in range(MAX_AGENT_STEPS):
                if env.is_done():
                    return
                actions = await agent.act(obs)
                obs = await env.run(actions or [])
            raise RuntimeError("agent step guard reached")

        try:
            asyncio.run(drive())
            outcome = "answered" if env.answer is not None else "no_answer"
        except CallCapReached:
            outcome = "call_cap_exhausted"
        except ContextOverflow:
            outcome = "context_overflow"
        finally:
            agent.executor.session.close()
            agent.executor.close()
        tree = agent._get_formatted_tree() if agent.root else None
        trace = {"slot": self.slot, "outcome": outcome, "call_cap_exhausted": outcome == "call_cap_exhausted",
                 "max_depth_reached": agent._get_max_depth(agent.root) if agent.root else 0,
                 "actions": env.actions, "blocks": agent.executor.blocks, "tree": tree}
        return env.answer or "", trace

    def answer(self, item: QAItem, instructions: str, prompt: str):
        return self.metered_answer(item.uid, lambda: self._episode(instructions, prompt))


def file_sha_text(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _expand_prompt() -> str:
    _import_recode()
    from agents.recode.resources.prompts.default_new import EXPAND_PROMPT
    return EXPAND_PROMPT


def build_fewshots(pilot_dir: Path) -> str:
    """Fill the two generic examples from pilot20 (dev set) only: its first multiple-choice question, the
    document's front matter and outline, and that question's part of the outline."""
    q = next(json.loads(l) for l in (pilot_dir / "items.jsonl").read_text(encoding="utf-8").splitlines()
             if json.loads(l)["choices"])
    from ..data import QAItem as _QA
    from ..prompts import build_question_prompt
    item = _QA(**{**q, "gold_choices": {}})
    prompt = build_question_prompt(item.stripped())
    nav = json.loads((pilot_dir / "navmap.json").read_text(encoding="utf-8"))
    scope_title = prompt.splitlines()[0]
    scope = next(n for n in nav["nodes"] if n["title"] == scope_title)
    observation = f"{P.FRONT_MATTER.format(front=front_matter(nav))}\n\nOUTLINE (top-level nodes):\n{outline(nav)}"
    return P.RECODE_FEWSHOTS.format(instruction=f"{ANSWER_INSTRUCTIONS}\n\n{prompt}", observation=observation,
                                    scope_title=scope_title, scope_id=scope["node_id"])
