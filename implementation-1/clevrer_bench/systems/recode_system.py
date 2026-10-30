"""Baseline ReCode (Yu et al., ICML 2026; docs/new_baselines_design.md sec. 5.3; SPEC sec. 11).

ReCode writes code recursively: the root call solve(instruction, observation) is a placeholder function; the model
EXPANDS each placeholder into either primitive actions (run("<action>")) or smaller placeholder functions, and each
expanded block runs at once. The tree, the expand prompt, the block splitting and checking, the variable display and
the executor are ReCode's own code, vendored unchanged except for import paths in third_party/recode
(FoundationAgents/ReCode @ 6e7223f, MIT). The agent loop below is ReCodeAgent.act / _handle_stub / _expand ported
from async to sync, with the same logic.

The `docqa` environment (this file) gives ReCode the same tools as ReAct-C (list_sections, read_section, search,
python in OTF's sandbox) plus answer[<json>]. First observation: the question; the document's front matter and its
chapter list. Few-shots (third_party/recode/docqa/fewshots.txt) use pilot20 (dev) only.

Caps (pre-registered): max depth 6, at most MAX_CALLS model calls per question (rewrites included), ReCode's own
max 5 rewrites per expansion. Additions for this harness: each block passes OTF's sandbox static check before it
runs in ReCode's in-process executor (a rejected block is an error, which ends the episode as in ReCode), and blocks
run one at a time across worker threads, because ReCode's executor redirects sys.stdout.
"""
from __future__ import annotations

import asyncio
import re
import threading
import time
from pathlib import Path

from otf import sandbox

from third_party.recode.environment import Env
from third_party.recode.executor import Executor
from third_party.recode.prompts import EXPAND_PROMPT
from third_party.recode.tree import CodeNode, NodeStatus, get_variables, split_blocks, validate_blocks

from ..data import QAItem
from ..llm import chat_sampling, chat_usage
from ..prompts import _last_json_object
from .base import Prediction, SetupResult, Usage
from .react_system import EMPTY_RESPONSE_RETRIES, MAX_CALLS, ReActSystem, chat_create

RESOURCES = Path(__file__).resolve().parents[2] / "third_party" / "recode" / "docqa"
MAX_DEPTH = 6
MAX_REWRITE = 5          # ReCode's DEFAULT_MAX_REWRITE
TREE_CODE_CHARS = 600    # code of each tree node kept in the trace
REPLY_CHARS = 1500       # start of each expand reply kept in the trace

ACTIONS_EXTRA = """
ANSWER RULES (for answer[...]):
{instructions}

{document}"""

_EXEC_LOCK = threading.Lock()   # ReCode's Executor swaps sys.stdout while a block runs


def _parse_xml_tag(response: str, xml_tag: str) -> str:
    """ReCode's utils.common.parse_xml_tag (copied: that module imports packages the harness does not need)."""
    m = re.search(rf"<{xml_tag}>(.*?)</{xml_tag}>", response, re.DOTALL)
    return m.group(1).strip() if m else ""


class DocQAEnv(Env):
    """ReCode environment over one document question. Actions: name[argument]."""

    def __init__(self, system: "ReCodeSystem", uid: str):
        self.id, self.system = uid, system
        self._step_count, self._done, self._success = 0, False, False
        self.answer: str | None = None
        self.code_runs = self.code_errors = 0

    def reset(self, running_config: dict, id=None) -> dict:
        return {}

    def report(self) -> dict:
        return {"answer": self.answer, "steps": self._step_count}

    async def _run(self, action: str):
        self._step_count += 1
        if action == "[FINISH]":
            self._done = True
            return ""
        m = re.match(r"\s*([A-Za-z_]+)\[(.*)\]\s*$", action or "", flags=re.S)
        if not m:
            return ("Unknown action. Use list_sections[...], read_section[...], search[...], python[...] or "
                    "answer[...].")
        name, arg = m.group(1), m.group(2)
        s = self.system
        if name == "answer":
            if _last_json_object(arg) is None:
                return "answer[...] needs the JSON object that the answer rules ask for. Give the answer again."
            self.answer, self._success, self._done = arg.strip(), True, True
            return "Answer recorded."
        if name == "list_sections":
            return s._list_sections(arg.strip())
        if name == "read_section":
            title, _, start = arg.partition("|")
            return s._read_section(title.strip(), int(start) if start.strip().isdigit() else 0)
        if name == "search":
            return s._search(arg.strip(), 5)
        if name == "python":
            out, failed = s._python(arg)
            self.code_runs += 1
            self.code_errors += failed
            return out
        return f"Unknown action {name!r}."


class _Episode:
    """ReCodeAgent's state and loop for one question (agents/recode/agent.py, sync)."""

    def __init__(self, system: "ReCodeSystem", env: DocQAEnv, instruction: str, observation: str,
                 available_actions: str):
        self.system, self.env, self.available_actions = system, env, available_actions
        self.executor = Executor(if_run_print=True)
        self.executor.set_env(env)
        self.executor.set_var("observation", observation)
        self.executor.set_var("instruction", instruction)
        self.root = CodeNode(code="solve(instruction, observation)")
        self.current_node = self.root
        self.usage, self.calls, self.end_reason, self.replies = Usage(), 0, None, []

    # ---- ReCodeAgent.act ----
    def act(self) -> list[str] | None:
        if self.current_node.status == NodeStatus.STUB:
            self._handle_stub()
        elif self.current_node.status == NodeStatus.ERROR:
            self.end_reason = self.end_reason or "error"
            return ["[FINISH]"]
        if not self.current_node:
            return ["[FINISH]"]
        result = self._execute(self.current_node.code)
        self.current_node.observations.extend(result["stdout"]) if result["stdout"] else None
        if result["success"]:
            self.current_node.status = NodeStatus.COMPLETED
            self.current_node = self.current_node.next()
            if not self.current_node:
                self.end_reason = self.end_reason or "tree_done"
                return ["[FINISH]"]
        else:
            if "NeedExpansion" in result["error"]:
                self.current_node.status = NodeStatus.STUB
            else:
                self.current_node.status = NodeStatus.ERROR
                self.current_node.error = result["error"]
        return None

    # ---- ReCodeAgent._handle_stub ----
    def _handle_stub(self) -> None:
        if self.current_node and self.current_node.depth >= MAX_DEPTH:
            self.end_reason = "max_depth"
            self.current_node = None
            return
        new_blocks = self._expand()
        if self.current_node:
            if new_blocks is None:
                self.current_node = None
                return
            if new_blocks:
                for block in new_blocks:
                    self.current_node.children.append(CodeNode(code=block, parent=self.current_node))
            else:
                self.current_node.status = NodeStatus.SKIP
        self.current_node = self.current_node.next()

    # ---- ReCodeAgent._expand (plus the per-question call cap) ----
    def _expand(self) -> list[str] | None:
        attempt, retry_hint_added = 0, False
        while True:
            if self.calls >= MAX_CALLS:
                self.end_reason = "call_cap"
                return None
            user_prompt = self._build_expand_prompt()
            if retry_hint_added:
                user_prompt += (
                    "\n\n[Important] Your previous expansion produced syntactically invalid code and/or included "
                    "disallowed constructs (e.g., def/async def). "
                    "Strictly follow the rules: output a single valid Python code block, and do not use def or async def."
                )
            response = self._llm(user_prompt)
            self.replies.append(response[:REPLY_CHARS])
            self.current_node.thought = _parse_xml_tag(response, "think").strip()
            expanded_code = _parse_xml_tag(response, "execute").strip()
            try:
                blocks = split_blocks(expanded_code)
                validate_blocks(blocks)
                return blocks
            except (SyntaxError, ValueError):
                attempt += 1
                retry_hint_added = True
                if attempt >= MAX_REWRITE:
                    self.end_reason = "rewrite_limit"
                    return None

    def _llm(self, prompt: str) -> str:
        s = self.system
        for retry in range(EMPTY_RESPONSE_RETRIES + 1):
            resp = chat_create(s.client, model=s.spec.served_name, messages=[{"role": "user", "content": prompt}],
                               **chat_sampling(s.spec, s.reasoning_effort))
            if resp.choices:
                self.calls += 1
                self.usage += chat_usage(resp.usage)
                return resp.choices[0].message.content or ""
            time.sleep(2 * (retry + 1))
        raise RuntimeError(f"no choices in the response: {getattr(resp, 'error', None) or resp.model_extra}")

    def _execute(self, code: str) -> dict:
        try:
            sandbox.check(code)
        except sandbox.CodeRejected as e:
            return {"code": code, "stdout": [], "error": f"Rejected: {e}", "success": False}
        with _EXEC_LOCK:
            return self.executor.execute(code)

    def _build_expand_prompt(self) -> str:
        examples = self.system.fewshots or "(No Examples)"
        task = self.current_node.code
        variables = get_variables(self.executor, self.current_node.code) or "(No Variables)"
        return EXPAND_PROMPT.format(available_actions=self.available_actions, examples=examples, task=task,
                                    variables=variables)

    def tree(self) -> list[dict]:
        out, stack = [], [self.root]
        while stack:
            n = stack.pop()
            out.append({"depth": n.depth, "status": n.status.value, "code": n.code[:TREE_CODE_CHARS],
                        **({"error": str(n.error)[:300]} if n.error else {})})
            stack += list(reversed(n.children))
        return out


class ReCodeSystem(ReActSystem):
    """Setup and tools come from ReAct-C (same map, chunk index, sandbox and map description)."""
    name = "recode"

    def __init__(self, model: str, reasoning_effort=None, **kwargs):
        super().__init__(model, reasoning_effort, variant="code")
        self.name = "recode"
        self.actions = (RESOURCES / "actions.txt").read_text(encoding="utf-8")
        self.fewshots = (RESOURCES / "fewshots.txt").read_text(encoding="utf-8")

    def setup(self, doc) -> SetupResult:
        res = super().setup(doc)
        self.first_obs_tail = "CHAPTERS:\n" + self._list_sections()
        res.info.update(max_depth=MAX_DEPTH, max_rewrite=MAX_REWRITE, variant=None, recode_commit="6e7223f")
        return res

    def answer(self, item: QAItem, instructions: str, prompt: str) -> Prediction:
        t = time.time()
        intro = self.document.split("NAVIGATION MAP SCHEMA")[0].strip()   # the front matter part
        observation = f"{intro}\n\n{self.first_obs_tail}"
        actions = self.actions + ACTIONS_EXTRA.replace("{instructions}", instructions).replace(
            "{document}", self.document)
        env = DocQAEnv(self, item.uid)
        ep = _Episode(self, env, prompt, observation, actions)
        try:
            while not env.is_done():   # run.py's episode loop
                acts = ep.act()
                asyncio.run(env.run(acts or []))
        finally:
            ep.executor.close()
        end = "answered" if env.answer is not None else (ep.end_reason or "no_answer")
        trace = {"model_calls": ep.calls, "end": end, "env_steps": env._step_count, "code_runs": env.code_runs,
                 "code_errors": env.code_errors, "max_depth_reached": max((n["depth"] for n in ep.tree()), default=0),
                 "tree": ep.tree(), "replies": ep.replies}
        return Prediction(env.answer or "", ep.usage, time.time() - t, trace=trace)
