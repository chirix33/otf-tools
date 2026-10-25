"""Baselines ReAct-R and ReAct-C (docs/new_baselines_design.md sec. 5.2; SPEC sec. 11).

A ReAct loop (Yao et al., ICLR 2023) with the chat API's native tool calling: the model reasons, calls a tool,
reads the result and repeats until it calls `finish`. At most MAX_CALLS model calls per question; the last call
is told that it is the last. A question that ends without an answer scores as a parse error.

variant="retrieve" (ReAct-R): list_sections, read_section, search, finish.
variant="code"     (ReAct-C): the same tools plus python(code), which runs in OTF's sandbox (otf/sandbox.py) with
                              the same Navigation Map `doc`, helpers and map description as OTF's generated tools.
                              Code is written for each question, never checked against the record or reused.

setup(): builds the Navigation Map (no LLM) and RAG's chunk index (same chunks and embedder as the `rag` system).
         No LLM tokens are spent.
"""
from __future__ import annotations

import json
import re
import time

import numpy as np
from openai import OpenAI, RateLimitError

from otf import sandbox
from otf.navmap import build_map, schema_summary
from otf.prompts import DOC_CONTEXT
from otf.toolgen import intro_text

from ..data import QAItem
from ..prompts import _last_json_object
from ..llm import chat_sampling, chat_usage, endpoint_key
from .base import Document, Prediction, QASystem, SetupResult, Usage
from .rag import RAGSystem

MAX_CALLS = 12          # model calls per question (SPEC sec. 11)
OBS_CHARS = 20000       # max characters of one list / read / search result
CODE_OUT_CHARS = 4000   # max printed characters of one python run
SEARCH_K_MAX = 10
TRACE_ARG_CHARS = 4000  # tool arguments kept in the trace (python code for the code-reliability table)
EMPTY_RESPONSE_RETRIES = 3
RATE_LIMIT_WAITS = (15, 30, 60, 120, 240)   # s; hosted shared pools return 429 in bursts


def chat_create(client, **kwargs):
    """chat.completions.create with long waits on 429 (after the client's own short retries)."""
    for wait in RATE_LIMIT_WAITS + (None,):
        try:
            return client.chat.completions.create(**kwargs)
        except RateLimitError:
            if wait is None:
                raise
            time.sleep(wait)

SYSTEM = """You answer a question about a document by using tools, step by step. Decide what you need to know, \
call a tool, read its result, and repeat. When you know the answer, call finish with the answer.

You may make at most {max_calls} model calls for this question. Each tool result says how many are left.

TOOLS
- list_sections(scope): the titles of the sections in one chapter; without a scope, the titles of all chapters.
- read_section(title, start): the content of a section, from line `start` (default 0). A long section comes in \
parts; the result says where the next part starts. A chapter title returns all the sections of the chapter.
- search(query, k): the k passages of the document that are most similar to the query (k at most {k_max}).
{python_tool}- finish(answer): your final answer: the JSON object that the answer rules below ask for, as a string.

ANSWER RULES
{instructions}

{document}"""

PYTHON_TOOL = """- python(code): runs Python code on the document's data and returns what it prints (at most \
{out_chars} characters). The document is available as `doc`, described below, with the helpers listed there. \
Allowed imports: math, json, re, itertools, collections, statistics, functools, heapq, bisect, dataclasses, \
typing, numpy, fractions, decimal, copy, operator. No file, network or process access. Each run starts fresh \
(nothing is kept between runs) and has a {timeout} s time limit.
"""

READ_DOC = """DOCUMENT DESCRIPTION (the document's own front matter):
{intro}"""

LAST_CALL = "This is your last model call. Call finish now with your best answer."
NUDGE = "Continue: call a tool, or call finish with your answer."
FINISH_NOT_JSON = ("finish needs the JSON object that the answer rules ask for, as a string, not a bare value. "
                   "Call finish again.")


def _tool(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": props, "required": required}}}


TOOLS = {
    "list_sections": _tool("list_sections", "List the sections of a chapter, or all chapters if no scope is given.",
                           {"scope": {"type": "string", "description": "a chapter title"}}, []),
    "read_section": _tool("read_section", "Read a section (or a whole chapter) by its exact title.",
                          {"title": {"type": "string"},
                           "start": {"type": "integer", "description": "first line to return (default 0)"}},
                          ["title"]),
    "search": _tool("search", "Find the passages most similar to a query.",
                    {"query": {"type": "string"}, "k": {"type": "integer", "description": "number of passages"}},
                    ["query"]),
    "python": _tool("python", "Run Python code on the document data `doc` and return what it prints.",
                    {"code": {"type": "string"}}, ["code"]),
    "finish": _tool("finish", "Give the final answer.",
                    {"answer": {"type": "string", "description": "the answer JSON object, as a string"}},
                    ["answer"]),
}


def _node_lines(n: dict) -> list[str]:
    """A node as text lines, in the same layout as OTF's section reading (otf/engine.py _scope_text)."""
    out = [f"## {n['title']} (pages {n['pages'][0]}-{n['pages'][1]})"]
    if n["kind"] == "table":
        out.append("\t".join(n["table"]["columns"]))
        out += ["\t".join(r) for r in n["table"]["rows"]]
    elif n["kind"] == "list":
        out += n["lines"]
    elif n.get("text"):
        out += n["text"].splitlines()
    return out


class ReActSystem(QASystem):
    name = "react"

    def __init__(self, model: str, reasoning_effort=None, variant: str = "retrieve", **kwargs):
        super().__init__(model, reasoning_effort)
        if variant not in ("retrieve", "code"):
            raise ValueError("variant must be 'retrieve' or 'code'")
        self.variant = variant
        self.name = "react_r" if variant == "retrieve" else "react_c"
        self.client = (OpenAI(base_url=self.spec.base_url, api_key=endpoint_key(self.spec), max_retries=6,
                              timeout=1800)
                       if self.spec.is_local else OpenAI(max_retries=6, timeout=600))
        self.rag = RAGSystem(model, reasoning_effort)   # only its chunk index and embedder are used
        names = ["list_sections", "read_section", "search"] + (["python"] if variant == "code" else []) + ["finish"]
        self.tools = [TOOLS[n] for n in names]

    def setup(self, doc: Document) -> SetupResult:
        t = time.time()
        self.nav = build_map(doc.pdf_path)
        self.map_path = doc.work_dir / "navmap.json"
        self.map_path.write_text(json.dumps(self.nav))
        self.by_title = {n["title"]: n for n in self.nav["nodes"]}
        self.by_id = {n["node_id"]: n for n in self.nav["nodes"]}
        rag_info = self.rag.setup(doc).info
        if self.variant == "code":   # the same map description OTF's tool generator gets
            document = DOC_CONTEXT.format(intro=intro_text(self.nav), schema=schema_summary(self.nav))
            python_tool = PYTHON_TOOL.format(out_chars=CODE_OUT_CHARS, timeout=sandbox.TIMEOUT_S)
        else:
            document, python_tool = READ_DOC.format(intro=intro_text(self.nav)), ""
        # plain replace, not str.format: the document and the answer rules contain literal braces
        self.system_head = (SYSTEM.replace("{max_calls}", str(MAX_CALLS)).replace("{k_max}", str(SEARCH_K_MAX))
                            .replace("{python_tool}", python_tool))
        self.document = document
        return SetupResult(Usage(), time.time() - t, {"nodes": len(self.nav["nodes"]), "variant": self.variant,
                                                      "max_calls": MAX_CALLS, **rag_info})

    # ---------- tools ----------
    def _find(self, title: str) -> dict | None:
        title = (title or "").strip()
        if title in self.by_title:
            return self.by_title[title]
        if title in self.by_id:
            return self.by_id[title]
        low = {k.lower(): v for k, v in self.by_title.items()}
        return low.get(title.lower())

    def _list_sections(self, scope: str | None = None) -> str:
        if not scope:
            top = [n for n in self.nav["nodes"] if n["level"] == 0]
            return "\n".join(f"{n['title']} ({len(n.get('children', []))} sections)" if n.get("children")
                             else f"{n['title']} (front matter)" for n in top)
        root = self._find(scope)
        if root is None:
            return f"No chapter titled {scope!r}. Call list_sections() without a scope to see the chapter titles."
        if not root.get("children"):
            return f"{root['title']} has no sections. Read it with read_section."
        out = []
        for cid in root["children"]:
            n = self.by_id[cid]
            size = (f"{len(n['table']['rows'])} rows" if n["kind"] == "table" else
                    f"{len(n['lines'])} lines" if n["kind"] == "list" else f"{len(n.get('text', ''))} characters")
            out.append(f"{n['title']} ({n['kind']}, {size}, pages {n['pages'][0]}-{n['pages'][1]})")
        return "\n".join(out)

    def _read_section(self, title: str, start: int = 0) -> str:
        n = self._find(title)
        if n is None:
            return f"No section titled {title!r}. Call list_sections to see the titles."
        lines = _node_lines(n)
        for cid in n.get("children", []):
            lines += _node_lines(self.by_id[cid])
        start = max(0, int(start or 0))
        if start >= len(lines):
            return f"{n['title']} has {len(lines)} lines; start {start} is past the end."
        end, used = start, 0
        while end < len(lines) and (end == start or used + len(lines[end]) + 1 <= OBS_CHARS):
            used += len(lines[end]) + 1
            end += 1
        out = "\n".join(lines[start:end])
        if start > 0 or end < len(lines):
            out += f"\n(lines {start}-{end - 1} of {len(lines)}"
            out += f"; call read_section with start={end} for more)" if end < len(lines) else ")"
        return out

    def _search(self, query: str, k: int = 5) -> str:
        k = min(max(int(k or 5), 1), SEARCH_K_MAX)
        q = self.rag._embed([query or ""])[0]
        top = np.argsort(-(self.rag.vectors @ q))[:k]
        out = "\n\n".join(f"PASSAGE {i + 1} (pages {self.rag.chunks[j]['pages']}):\n{self.rag.chunks[j]['text']}"
                          for i, j in enumerate(top))
        return out[:OBS_CHARS]

    def _python(self, code: str) -> tuple[str, bool]:
        ok, out = sandbox.run_script(code or "", self.map_path)
        text = out if isinstance(out, str) else json.dumps(out, default=str)
        failed = not ok or "\nERROR:\n" in text
        if len(text) > CODE_OUT_CHARS:
            text = text[:CODE_OUT_CHARS] + f"\n(output cut at {CODE_OUT_CHARS} characters)"
        return text or "(no output: print() what you want to see)", failed

    def _run_tool(self, name: str, args: dict) -> tuple[str, bool]:
        """(observation, failed)."""
        if name == "list_sections":
            return self._list_sections(args.get("scope")), False
        if name == "read_section":
            return self._read_section(args.get("title", ""), args.get("start", 0)), False
        if name == "search":
            return self._search(args.get("query", ""), args.get("k", 5)), False
        if name == "python" and self.variant == "code":
            return self._python(args.get("code", ""))
        return f"Unknown tool {name!r}.", True

    # ---------- the loop ----------
    def _call(self, messages: list[dict], usage: list) -> object:
        """One model call. A response without choices (a provider error inside a 200 reply) is retried; it is
        not a model step and does not count against MAX_CALLS."""
        for attempt in range(EMPTY_RESPONSE_RETRIES + 1):
            resp = chat_create(self.client, model=self.spec.served_name, messages=messages, tools=self.tools,
                               **chat_sampling(self.spec, self.reasoning_effort))
            if resp.choices:
                usage[0] += chat_usage(resp.usage)
                return resp.choices[0]
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"no choices in the response: {getattr(resp, 'error', None) or resp.model_extra}")

    def _parse_call(self, c) -> tuple[str, dict, bool]:
        """(tool name, arguments, arguments valid). Some servers leave the model's channel tokens in the name
        ("read_section<|channel|>commentary"); the name is its leading identifier. gpt-oss sends raw code to a
        tool called `python` (its built-in tool format), and some models send a bare answer to `finish`: the raw
        text is then the argument."""
        m = re.match(r"[A-Za-z_]+", c.function.name or "")
        name, raw = (m.group(0) if m else ""), c.function.arguments or ""
        try:
            args = json.loads(raw or "{}")
            if isinstance(args, dict):
                return name, args, True
        except json.JSONDecodeError:
            pass
        if name in ("python", "finish") and raw.strip():
            return name, {"code" if name == "python" else "answer": raw}, True
        return name, {}, False

    def answer(self, item: QAItem, instructions: str, prompt: str) -> Prediction:
        t = time.time()
        system = self.system_head.replace("{instructions}", instructions).replace("{document}", self.document)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        usage, steps, final, finished_by, finish = [Usage()], [], None, None, None
        code_runs = code_errors = 0
        for call in range(1, MAX_CALLS + 1):
            if call == MAX_CALLS:
                messages.append({"role": "user", "content": LAST_CALL})
            choice = self._call(messages, usage)
            msg, finish = choice.message, choice.finish_reason
            calls = msg.tool_calls or []
            if not calls:
                if (msg.content or "").strip():          # a reply without a tool call is the final answer
                    final, finished_by = msg.content, "message"
                    break
                steps.append({"empty_reply": True, "finish_reason": finish})
                messages.append({"role": "user", "content": NUDGE})
                continue
            parsed = [(c, *self._parse_call(c)) for c in calls]
            messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": name or (c.function.name or ""),
                                                              "arguments": c.function.arguments or "{}"}}
                for c, name, _, _ in parsed]})
            for c, name, args, valid in parsed:
                step = {"tool": name}
                if name != c.function.name:
                    step["raw_tool"] = (c.function.name or "")[:80]
                if name == "finish" and valid:
                    a = args.get("answer", "")
                    a = a if isinstance(a, str) else json.dumps(a)
                    if _last_json_object(a) is not None:
                        final, finished_by = a, "finish"
                        steps.append(step)
                        break
                    obs, failed = FINISH_NOT_JSON, True
                elif not valid:
                    obs, failed = "The tool arguments are not valid JSON. Call the tool again.", True
                else:
                    try:
                        obs, failed = self._run_tool(name, args)
                    except Exception as e:                # a bad argument value must not end the question
                        obs, failed = f"Tool error: {type(e).__name__}: {e}"[:500], True
                if name == "python":
                    code_runs += 1
                    code_errors += failed
                    step["obs_head"] = obs[:300]
                step.update(args={k: str(v)[:TRACE_ARG_CHARS] for k, v in args.items()}, obs_chars=len(obs),
                            failed=failed)
                steps.append(step)
                messages.append({"role": "tool", "tool_call_id": c.id,
                                 "content": f"{obs}\n[model calls left: {MAX_CALLS - call}]"})
            if final is not None:
                break
        trace = {"model_calls": usage[0].llm_calls, "tool_calls": sum("tool" in s for s in steps),
                 "finished_by": finished_by, "cap_hit": final is None, "last_finish_reason": finish,
                 "steps": steps}
        if self.variant == "code":
            trace.update(code_runs=code_runs, code_errors=code_errors)
        return Prediction(final or "", usage[0], time.time() - t, trace=trace)
