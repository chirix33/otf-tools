"""Run model-written code in a separate, isolated Python process.

Before running, the code is checked statically: only whitelisted modules may be imported, and names that
reach the filesystem, processes or the interpreter (open, exec, eval, __import__, ...) are rejected. The
code then runs in `python -I` (isolated mode: no user site-packages, no PYTHON* env vars, no script dir on
sys.path) with a wall-clock timeout. Inside, it sees the Navigation Map as `doc` and the helpers below.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ALLOWED_MODULES = {"math", "json", "re", "itertools", "collections", "statistics", "functools", "heapq",
                   "bisect", "dataclasses", "typing", "numpy", "fractions", "decimal", "copy", "operator"}
FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "input",
                   "breakpoint", "getattr", "setattr", "delattr", "memoryview", "exit", "quit"}
TIMEOUT_S = 20

# Helpers available to generated code (kept tiny on purpose; the model writes everything else).
HELPERS = r'''
def node_by_title(doc, title):
    for n in doc["nodes"]:
        if n["title"] == title:
            return n
    return None

def children(doc, node):
    ids = set(node.get("children", []))
    return [n for n in doc["nodes"] if n["node_id"] in ids]

def scope_nodes(doc, scope):
    """All nodes under the top-level node titled `scope` (its children), in document order."""
    root = node_by_title(doc, scope)
    return children(doc, root) if root else []
'''

RUNNER = r'''
import contextlib, io, json, sys
spec = json.load(open(sys.argv[1]))
doc = json.load(open(spec["map_path"]))
ns = {"__name__": "generated"}
exec(spec["helpers"], ns)
if spec["func"] == "__script__":          # exploration: run as a script with `doc` defined, capture prints
    ns["doc"] = doc
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(spec["code"], ns)
            if callable(ns.get("explore")):
                r = ns["explore"](doc)
                if r is not None:
                    print(r if isinstance(r, str) else json.dumps(r, default=str))
        out = buf.getvalue()
    except Exception as e:
        import traceback
        out = buf.getvalue() + "\nERROR:\n" + "".join(traceback.format_exception(e)[-4:])
else:
    exec(spec["code"], ns)
    out = ns[spec["func"]](doc, *spec["args"], **spec["kwargs"])
sys.stdout.write("\n@@RESULT@@" + json.dumps(out, default=str))
'''


class CodeRejected(Exception):
    pass


def check(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise CodeRejected(f"syntax error: {e}") from e
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_MODULES:
                    raise CodeRejected(f"import of '{a.name}' is not allowed (allowed: {sorted(ALLOWED_MODULES)})")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_MODULES:
                raise CodeRejected(f"import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise CodeRejected(f"use of '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__") \
                and node.attr not in ("__init__", "__name__"):
            raise CodeRejected(f"dunder attribute '{node.attr}' is not allowed")


def run_script(code: str, map_path: Path, timeout_s: int = TIMEOUT_S) -> tuple[bool, str]:
    """Run an exploration snippet as a script (`doc` defined; an `explore(doc)` function is called if
    defined); returns its printed output, including the traceback if it raised."""
    return run(code, "__script__", map_path, timeout_s=timeout_s)


def run(code: str, func: str, map_path: Path, args: list | None = None, kwargs: dict | None = None,
        timeout_s: int = TIMEOUT_S):
    """Returns (ok, result_or_error_text)."""
    try:
        check(code)
    except CodeRejected as e:
        return False, f"rejected: {e}"
    with tempfile.TemporaryDirectory() as td:
        spec_p = Path(td) / "spec.json"
        spec_p.write_text(json.dumps({"map_path": str(Path(map_path).resolve()), "helpers": HELPERS, "code": code, "func": func,
                                      "args": args or [], "kwargs": kwargs or {}}))
        runner_p = Path(td) / "runner.py"
        runner_p.write_text(RUNNER)
        try:
            p = subprocess.run([sys.executable, "-I", str(runner_p), str(spec_p)], capture_output=True, text=True,
                               timeout=timeout_s, cwd=td)
        except subprocess.TimeoutExpired:
            return False, f"timeout after {timeout_s}s"
    if p.returncode != 0 or "@@RESULT@@" not in p.stdout:
        err = (p.stderr or p.stdout).strip().splitlines()
        return False, "\n".join(err[-12:])
    return True, json.loads(p.stdout.split("@@RESULT@@", 1)[1])
