"""ReAct baselines (Yao et al., ICLR 2023) with the chat API's native tool calling.

variant="retrieve" (react_r): search (RAG's index: same sections, 512/64-token chunks, bge-small, cosine, k=5),
                              read_section, list_sections, finish.
variant="code" (react_c):     the same plus python(code), run by otf.sandbox.run_script with the same Navigation
                              Map `doc` and helpers as OTF's generated tools.

Each question is its own conversation (no state or code is carried across questions). The shared answer contract
is the system prompt, followed by the method instructions and the document's front matter; the user turn is the
shared question prompt. At most 12 model calls per question; a valid finish on call 12 counts, otherwise the
question is recorded as call-cap exhaustion (unparseable). Native tool-call messages, observations and finish
reasons are kept in the trace.
"""
from __future__ import annotations

import json
import time

from otf import sandbox

from ..data import QAItem
from . import baseline_prompts as P
from .base import Document, SetupResult
from .metered import MAX_CALLS_PER_QUESTION, CallCapReached, ContextOverflow, MeteredChat
from .rag import RAGSystem
from .tierb_common import ROOT, TierBSystem, file_sha, front_matter, load_nav, outline, render_node

RAG_CACHE = ROOT / ".cache" / "tierb_rag_index"

OBS_CHARS = 16000            # longest observation passed back to the model (the trace keeps the same text)


def _json_object_or_empty(s: str | None) -> str:
    try:
        return s if isinstance(json.loads(s or ""), dict) else "{}"
    except ValueError:
        return "{}"


def _fn(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": props,
                                                            "required": required}}}


def tool_schemas(variant: str) -> list[dict]:
    tools = [
        _fn("list_sections", P.TOOL_DOCS["list_sections"],
            {"node_id": {"type": "string", "description": "optional node id"}}, []),
        _fn("read_section", P.TOOL_DOCS["read_section"], {"node_id": {"type": "string"}}, ["node_id"]),
        _fn("search", P.TOOL_DOCS["search"],
            {"query": {"type": "string"}, "k": {"type": "integer", "default": 5}}, ["query"]),
    ]
    if variant == "code":
        tools.append(_fn("python", P.TOOL_DOCS["python"].replace("{modules}",
                                                                 ", ".join(sorted(sandbox.ALLOWED_MODULES))),
                         {"code": {"type": "string"}}, ["code"]))
    tools.append(_fn("finish", P.TOOL_DOCS["finish"], {"answer_json": {"type": "string"}}, ["answer_json"]))
    return tools


class ReActSystem(TierBSystem):
    base_name = "react"

    def __init__(self, model: str, reasoning_effort=None, variant: str = "retrieve", slot: int = 1,
                 out_name: str | None = None, **kwargs):
        if variant not in ("retrieve", "code"):
            raise ValueError("variant must be 'retrieve' or 'code'")
        self.variant = variant
        self.base_name = "react_r" if variant == "retrieve" else "react_c"
        super().__init__(model, reasoning_effort, slot, out_name)
        self.llm = MeteredChat(self.spec, self.reasoning_effort)
        self.tools = tool_schemas(variant)

    def method_prompt(self) -> str:
        text = P.REACT_SYSTEM[self.slot]
        return text.replace("{code_step}", P.REACT_CODE_STEP if self.variant == "code" else "")

    def method_config(self) -> dict:
        return {"variant": self.variant, "method_prompt": self.method_prompt(), "tools": self.tools,
                "search": {"top_k": 5, "chunk_tokens": 512, "overlap_tokens": 64},
                "observation_chars": OBS_CHARS, "sandbox_timeout_s": sandbox.TIMEOUT_S,
                "sandbox_modules": sorted(sandbox.ALLOWED_MODULES)}

    def setup(self, doc: Document) -> SetupResult:
        t = time.time()
        self.open_ledger(doc)
        self.rag = RAGSystem(self.model, self.reasoning_effort)
        # RAG's own index (no LLM calls: chunking + CPU embeddings), cached once per PDF for all candidates
        shared = RAG_CACHE / file_sha(doc.pdf_path)[:16]
        shared.mkdir(parents=True, exist_ok=True)
        info = self.rag.setup(Document(doc.pdf_path, doc.manifest, shared)).info
        self.nav, self.map_path = load_nav(doc)
        self.front = front_matter(self.nav)
        u, unknown = self.ledger.setup_usage()              # always zero model calls for ReAct
        return SetupResult(u, time.time() - t, {**info, "nodes": len(self.nav["nodes"]),
                                                "usage_unknown_calls": unknown, "config_hash": self.config_hash()})

    # --- tools ----------------------------------------------------------------------------------------
    def run_tool(self, name: str, args: dict) -> str:
        if name == "list_sections":
            return outline(self.nav, args.get("node_id") or None)
        if name == "read_section":
            return render_node(self.nav, args.get("node_id", ""))
        if name == "search":
            k = args.get("k", 5)
            k = max(1, min(int(k), 20)) if str(k).strip().lstrip("-").isdigit() else 5
            return self.rag.retrieve(str(args.get("query", "")), k)[1]
        if name == "python" and self.variant == "code":
            ok, out = sandbox.run_script(str(args.get("code", "")), self.map_path)
            text = out if isinstance(out, str) else json.dumps(out, default=str)
            return text if ok else f"error: {text}"
        return f"error: unknown tool {name!r}"

    # --- loop -----------------------------------------------------------------------------------------
    def _loop(self, instructions: str, prompt: str) -> tuple[str, dict]:
        system = f"{instructions}\n\n{self.method_prompt()}\n\n{P.FRONT_MATTER.format(front=self.front)}"
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        steps, final, outcome = [], None, "no_answer"
        try:
            for call_no in range(1, MAX_CALLS_PER_QUESTION + 1):
                resp = self.llm.chat(messages, source="react", tools=self.tools, tool_choice="auto")
                msg = resp.choices[0].message
                finish = resp.choices[0].finish_reason
                calls = list(msg.tool_calls or [])
                step = {"call": call_no, "finish_reason": finish, "content": msg.content,
                        "reasoning": getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None),
                        "tool_calls": [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments}
                                       for c in calls], "observations": []}
                steps.append(step)
                if not calls:                       # a plain reply is the model's final answer
                    final, outcome = msg.content or "", "answered_without_finish"
                    break
                # vLLM parses the arguments we send back; malformed ones are replaced by {} (raw text is in the trace)
                messages.append({"role": "assistant", "content": msg.content or "",
                                 "tool_calls": [{"id": c.id, "type": "function",
                                                 "function": {"name": c.function.name,
                                                              "arguments": _json_object_or_empty(c.function.arguments)}}
                                                for c in calls]})
                for c in calls:
                    try:
                        args = json.loads(c.function.arguments or "{}")
                        if not isinstance(args, dict):
                            raise ValueError("arguments must be a JSON object")
                    except ValueError as e:
                        obs = f"error: tool arguments are not valid JSON ({e})"
                        args = None
                    if args is not None and c.function.name == "finish" and "answer_json" not in args:
                        # schema violation: say so and let the model call again (within the call cap)
                        obs = "error: finish requires the argument answer_json (the answer object as a JSON string)"
                    elif args is not None and c.function.name == "finish":
                        a = args.get("answer_json", "")
                        final = a if isinstance(a, str) else json.dumps(a)
                        outcome = "finish"
                        obs = "submitted"
                    elif args is not None:
                        try:
                            obs = self.run_tool(c.function.name, args)
                        except Exception as e:      # a tool error is an observation, not a crash
                            obs = f"error: {type(e).__name__}: {e}"
                    obs = obs[:OBS_CHARS]
                    step["observations"].append({"id": c.id, "name": c.function.name, "content": obs})
                    messages.append({"role": "tool", "tool_call_id": c.id, "content": obs})
                if final is not None:
                    break
            else:
                outcome = "call_cap_exhausted"
        except CallCapReached:
            outcome = "call_cap_exhausted"
        except ContextOverflow as e:
            outcome = "context_overflow"
            steps.append({"error": str(e)})
        if final is None:
            final = ""
        return final, {"variant": self.variant, "slot": self.slot, "outcome": outcome,
                       "call_cap_exhausted": outcome == "call_cap_exhausted", "steps": steps}

    def answer(self, item: QAItem, instructions: str, prompt: str):
        return self.metered_answer(item.uid, lambda: self._loop(instructions, prompt))
