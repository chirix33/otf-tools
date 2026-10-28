"""A small OpenAI-compatible stand-in for the vLLM server, used by the Tier B tests (no GPU needed).

    python tests/mock_vllm.py --port 8000 --served nvidia/Qwen3.6-27B-NVFP4

It answers /v1/models and /v1/chat/completions with deterministic, well-formed replies for each system:
ReAct (native tool calls ending in finish), ReCode (EXPAND replies), GraphRAG (extraction records, community
report JSON, local-search answers) and plain answers. Usage includes cached/reasoning details like vLLM's.
Behaviour switches (env, for failure tests): MOCK_NEVER_FINISH=1 (agent never calls finish), MOCK_FINISH_AT=N (finish
on call N), MOCK_RECODE=deep|wide|os|loop (ReCode expansions that recurse, branch, import os, loop), MOCK_BAD_ARGS=1
(malformed tool arguments first), MOCK_NO_USAGE=1 (omit usage), MOCK_FAIL_FIRST=N (first N requests -> HTTP 500),
MOCK_EXTRACT_FAIL=1 (GraphRAG extraction returns no records), MOCK_LENGTH=1 (finish_reason=length, no JSON),
MOCK_FINISH_WRONG_KEY=1 (finish called without answer_json once), MOCK_PROVIDER_ERROR_FIRST=N (first N requests end
with finish_reason "error", as OpenRouter reports a provider failure).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {"served": "mock", "requests": 0, "log": None}
LOCK = threading.Lock()


def _answer_for(text: str) -> str:
    ids = re.findall(r"^\s+(\d+): ", text, flags=re.M)
    if "multiple-choice JSON format" in text and ids:
        return json.dumps({"choices": {i: (k == 0) for k, i in enumerate(ids)}})
    return json.dumps({"answer": "yes"})


def _question(messages) -> str:
    users = [m.get("content") or "" for m in messages if m.get("role") == "user"]
    return users[0] if users else ""


def _content(m) -> str:
    c = m.get("content") or ""
    if isinstance(c, list):
        c = "".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c


def react_reply(body) -> dict:
    msgs = body["messages"]
    names = {t["function"]["name"] for t in body["tools"]}
    q = _question(msgs)
    turns = sum(1 for m in msgs if m.get("role") == "assistant")
    last_tool = next((_content(m) for m in reversed(msgs) if m.get("role") == "tool"), "")
    video = re.search(r"Video (\d+)", q)
    plan = ["list_sections", "read_scope", "read_child", "search"] + (["python"] if "python" in names else [])
    if os.environ.get("MOCK_NEVER_FINISH"):
        step = "list_sections"
    elif os.environ.get("MOCK_FINISH_AT"):
        step = "finish" if turns + 1 >= int(os.environ["MOCK_FINISH_AT"]) else "list_sections"
    elif os.environ.get("MOCK_BAD_ARGS") and turns == 0:
        return {"tool_calls": [{"name": "read_section", "arguments": "{not json"}]}
    else:
        step = plan[turns] if turns < len(plan) else "finish"
    if step == "list_sections":
        return {"tool_calls": [{"name": "list_sections", "arguments": "{}"}]}
    if step in ("read_scope", "read_child"):
        m = re.search(r"^(n\d{4}) \| [^\n|]*" + (video.group(1) if video and step == "read_scope" else ""),
                      last_tool, flags=re.M)
        return {"tool_calls": [{"name": "read_section", "arguments": json.dumps({"node_id": m.group(1) if m else "n0000"})}]}
    if step == "search":
        return {"tool_calls": [{"name": "search", "arguments": json.dumps({"query": q[:200], "k": 3})}]}
    if step == "python":
        return {"tool_calls": [{"name": "python", "arguments": json.dumps(
            {"code": "print(len(doc['nodes']), node_by_title(doc, doc['nodes'][1]['title'])['node_id'])"})}]}
    if os.environ.get("MOCK_FINISH_WRONG_KEY") and "requires the argument answer_json" not in last_tool:
        return {"tool_calls": [{"name": "finish", "arguments": json.dumps(json.loads(_answer_for(q)))}]}
    return {"tool_calls": [{"name": "finish", "arguments": json.dumps({"answer_json": _answer_for(q)})}]}


def recode_reply(prompt: str) -> str:
    mode = os.environ.get("MOCK_RECODE")
    if mode == "wide":                    # the root fans out into 13 placeholders, each resolved by one call
        is_root = "solve(" in prompt.rsplit("The current function to expand is:", 1)[1][:200]
        code = "\n".join(f"p{i} = part_{i}(instruction)" for i in range(13)) if is_root else "value = 1"
        return f"<think>\nwide\n</think>\n<execute>\n{code}\n</execute>"
    if mode:
        code = {"deep": "x = go_one_level_deeper(instruction)",
                "os": "import os\nprint(os.getcwd())",
                "loop": "while True:\n    pass"}[mode]
        return f"<think>\n{mode}\n</think>\n<execute>\n{code}\n</execute>"
    task = prompt.rsplit("The current function to expand is:", 1)[1].split("The variables you can use is:")[0].strip()
    variables = prompt.rsplit("The variables you can use is:", 1)[1]
    if task.startswith("solve("):
        code = ('toc = run("list_sections[]")\n'
                'first = toc.splitlines()[0].split(" | ")[0]\n'
                'detail = run("read_section[" + first + "]")\n'
                'hits = run("search[" + instruction[-120:] + "]")\n'
                'n = len(doc["nodes"])\n'
                'result = choose_answer(instruction, detail)\n'
                'run("answer[" + result + "]")')
    else:
        code = f"result = {json.dumps(_answer_for(variables))}"
    return f"<think>\nPlan the step.\n</think>\n<execute>\n{code}\n</execute>"


def _instance(schema: dict, defs: dict):
    """A small value that satisfies a JSON schema (structured-output requests)."""
    if "$ref" in schema:
        return _instance(defs[schema["$ref"].rsplit("/", 1)[1]], defs)
    t = schema.get("type")
    if "anyOf" in schema:
        return _instance(schema["anyOf"][0], defs)
    if t == "object" or "properties" in schema:
        return {k: _instance(v, defs) for k, v in schema.get("properties", {}).items()}
    if t == "array":
        return [_instance(schema.get("items", {"type": "string"}), defs)]
    if t == "number":
        return 5.0
    if t == "integer":
        return 1
    if t == "boolean":
        return True
    return "thing"


def graphrag_reply(body, prompt: str) -> str:
    rf = body.get("response_format")
    if rf:   # structured output (community reports, prompt-tuning): satisfy the requested schema
        schema = (rf.get("json_schema") or {}).get("schema") or {}
        out = _instance(schema, schema.get("$defs", {})) if schema else {"result": "ok"}
        if os.environ.get("MOCK_REPORT_EXTRA") and isinstance(out, dict):
            out["date_range"] = ["0", "127"]          # an extra key a hosted model may add
        return json.dumps(out)
    if "<|COMPLETE|>" in prompt or "<|>" in prompt and "entity" in prompt.lower():
        if os.environ.get("MOCK_EXTRACT_FAIL"):
            return "I cannot do that."
        if os.environ.get("MOCK_EXTRACT_EMPTY") and sum(map(ord, prompt[-400:])) % 2 == 0:
            return "No entities of the requested types are present in this text.\n<|COMPLETE|>"
        text = prompt.rsplit("Text:", 1)[-1] if "Text:" in prompt else prompt
        names = list(dict.fromkeys(re.findall(r"Video \d+|Object \d+", text)))[:8] or ["DOCUMENT"]
        recs = [f'("entity"<|>{n.upper()}<|>THING<|>{n} appears in the text)' for n in names]
        recs += [f'("relationship"<|>{a.upper()}<|>{b.upper()}<|>{a} is mentioned with {b}<|>2)'
                 for a, b in zip(names, names[1:])]
        return "##".join(recs) + "##<|COMPLETE|>"
    if "Answer Y if there are still entities" in prompt or "answer Y or N" in prompt.lower():
        return "N"
    if "MANY entities" in prompt:
        return "<|COMPLETE|>"
    if "---Role---" in prompt or "Data tables" in prompt or "---Data tables---" in prompt:
        return "Based on the data, here is the answer.\n" + _answer_for(_question(body["messages"]) or prompt)
    return "A short summary of the entity description."


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._send(200, {"object": "list", "data": [{"id": STATE["served"], "object": "model"}]})
        if self.path.rstrip("/").endswith("/health"):
            return self._send(200, {})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        with LOCK:
            STATE["requests"] += 1
            n = STATE["requests"]
        if STATE["log"]:
            with LOCK, open(STATE["log"], "a", encoding="utf-8") as f:
                f.write(json.dumps({k: body.get(k) for k in ("model", "temperature", "top_p", "max_tokens",
                                                              "top_k", "chat_template_kwargs", "tools")
                                    if k != "tools"} | {"has_tools": bool(body.get("tools"))}) + "\n")
        if os.environ.get("MOCK_CREDITS"):
            return self._send(402, {"error": {"code": 402, "message": "This request would exceed your available "
                                              "credits given your current in-flight requests. Add credits."}})
        if n <= int(os.environ.get("MOCK_RATE_LIMIT_FIRST", "0")):
            return self._send(429, {"error": {"code": 429, "message": "temporarily rate-limited upstream"}})
        if n <= int(os.environ.get("MOCK_FAIL_FIRST", "0")):
            return self._send(500, {"error": {"message": "mock failure"}})
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._send(404, {"error": "not found"})
        if body.get("model") != STATE["served"]:
            return self._send(404, {"error": {"message": f"model {body.get('model')} not served"}})
        for m in body["messages"]:          # like vLLM: tool-call arguments sent back must be valid JSON
            for tc in m.get("tool_calls") or []:
                try:
                    json.loads(tc["function"]["arguments"])
                except ValueError:
                    return self._send(400, {"error": {"message": "invalid tool call arguments"}})
        prompt = "\n".join(_content(m) for m in body["messages"])
        msg = {"role": "assistant", "content": None, "reasoning_content": "thinking..."}
        finish = "stop"
        if os.environ.get("MOCK_LENGTH"):
            msg["content"], finish = "partial output without json", "length"
        elif body.get("tools"):
            r = react_reply(body)
            msg["tool_calls"] = [{"id": f"call_{n}_{i}", "type": "function",
                                  "function": {"name": c["name"], "arguments": c["arguments"]}}
                                 for i, c in enumerate(r["tool_calls"])]
            finish = "tool_calls"
        elif "You are the EXPAND step" in prompt:
            msg["content"] = recode_reply(prompt)
        elif "---Role---" in prompt or "<|>" in prompt or body.get("response_format") or "entit" in prompt.lower():
            msg["content"] = graphrag_reply(body, prompt)
        else:
            msg["content"] = "Answer: " + _answer_for(prompt)
        if n <= int(os.environ.get("MOCK_PROVIDER_ERROR_FIRST", "0")):   # 200 with finish_reason "error"
            msg, finish = {"role": "assistant", "content": None}, "error"
        out = {"id": f"cmpl-{n}", "object": "chat.completion", "created": int(time.time()),
               "model": STATE["served"], "choices": [{"index": 0, "message": msg, "finish_reason": finish}]}
        if not os.environ.get("MOCK_NO_USAGE"):
            pt = len(prompt) // 4 + 1
            ct = len(json.dumps(msg)) // 4 + 5
            out["usage"] = {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct,
                            "prompt_tokens_details": {"cached_tokens": pt // 2},
                            "completion_tokens_details": {"reasoning_tokens": 5}}
        if body.get("stream"):
            return self._stream(out, (body.get("stream_options") or {}).get("include_usage"))
        self._send(200, out)

    def _stream(self, out, include_usage):
        text = out["choices"][0]["message"].get("content") or ""
        base = {"id": out["id"], "object": "chat.completion.chunk", "created": out["created"], "model": out["model"]}
        events = [dict(base, choices=[{"index": 0, "delta": {"role": "assistant", "content": text[i:i + 40]},
                                       "finish_reason": None}]) for i in range(0, max(len(text), 1), 40)]
        events.append(dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": out["choices"][0]["finish_reason"]}]))
        if include_usage and "usage" in out:
            events.append(dict(base, choices=[], usage=out["usage"]))
        data = "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode() + b"data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class DualStack(ThreadingHTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def serve(port: int, served: str, log: str | None = None) -> DualStack:
    STATE.update(served=served, log=log, requests=0)
    try:
        srv = DualStack(("::", port), H)
    except OSError:                       # no IPv6 on this host
        srv = ThreadingHTTPServer(("127.0.0.1", port), H)
        srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--served", default="mock")
    ap.add_argument("--log", default=None)
    a = ap.parse_args()
    serve(a.port, a.served, a.log)
    print(f"mock vLLM on :{a.port} serving {a.served}", flush=True)
    while True:
        time.sleep(3600)
