"""OTF engine: Navigation Map -> generated, checked process model -> per-question-type tools -> answer.

prepare(pdf) builds the map (no LLM) and generates + checks the process model (LLM; one-time cost).
answer(question) routes the question to a type, runs that type's tool in the sandbox, and makes one final
LLM call with the tool's evidence. If the model failed its check, or a tool run fails, the question falls
back to reading the scope's sections (recorded in the trace).
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from . import library, prompts, sandbox
from .navmap import build_map
from .toolgen import generate_model, scopes


def _json(text: str) -> dict:
    for m in reversed(list(re.finditer(r"\{.*?\}", text or "", flags=re.S))):
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
    return {}


class OTFEngine:
    def __init__(self, llm, work_dir: Path, max_tries: int = 3, log=None):
        """llm(messages) -> reply text; the caller meters its tokens."""
        self.llm, self.work, self.max_tries, self.log = llm, work_dir, max_tries, log or (lambda s: None)
        self._cache, self._lock = {}, threading.Lock()

    # ---------- one-time preparation ----------
    def prepare(self, pdf_path: Path, cached_model: dict | None = None, library_dir: Path | None = None) -> dict:
        """library_dir: where verified models are shared between documents of the same structure (None: off)."""
        self.nav = build_map(pdf_path)
        self.map_path = self.work / "navmap.json"
        self.map_path.write_text(json.dumps(self.nav))
        self.scopes = sorted(scopes(self.nav), key=len, reverse=True)
        self.model = cached_model or generate_model(self.llm, self.nav, self.map_path, log=self.log,
                                                    library=library.load(library_dir, self.nav))
        if cached_model is None and not self.model.get("reused_from"):
            library.store(library_dir, self.nav, self.model, source=pdf_path.parent.name)
        return {"nodes": len(self.nav["nodes"]), "scopes": len(self.scopes), "model_passed": self.model["passed"],
                "model_f1": self.model["mean_f1"], "model_tries": self.model["tries"],
                "model_reused_from": self.model.get("reused_from")}

    # ---------- per question ----------
    def _run(self, func: str, *args, **kwargs):
        key = (func, json.dumps(args, default=str), json.dumps(kwargs, sort_keys=True, default=str))
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        res = sandbox.run(self.model["code"], func, self.map_path, list(args), kwargs)
        with self._lock:
            self._cache[key] = res
        return res

    def _scope_of(self, question: str) -> str | None:
        return next((s for s in self.scopes if re.search(rf"(?<!\w){re.escape(s)}(?!\w)", question)), None)

    def _scope_text(self, scope: str) -> str:
        root = next(n for n in self.nav["nodes"] if n["title"] == scope)
        out = []
        for n in self.nav["nodes"]:
            if n["node_id"] not in root.get("children", []):
                continue
            out.append(f"## {n['title']} (pages {n['pages'][0]}-{n['pages'][1]})")
            if n["kind"] == "table":
                out.append("\t".join(n["table"]["columns"]))
                out += ["\t".join(r) for r in n["table"]["rows"]]
            elif n["kind"] == "list":
                out += n["lines"]
            else:
                out.append(n.get("text", ""))
        return "\n".join(out)

    def route(self, question: str) -> str:
        t = _json(self.llm([{"role": "system", "content": prompts.ROUTER}, {"role": "user", "content": question}]))
        qt = str(t.get("type", "")).strip().lower()
        return qt if qt in prompts.QUESTION_TYPES else "descriptive"

    def _fmt_events(self, events: list[dict], names: dict) -> str:
        if not events:
            return "(none)"
        return "\n".join(f"time {float(e['time']):g}: {e.get('kind', 'event')} between "
                         + " and ".join(f"{names.get(str(p), p)} (id {p})" for p in e.get("participants", []))
                         for e in sorted(events, key=lambda e: float(e["time"])))

    def _with_removed(self, scope: str, removed: list[str], obs: list[dict], end: float) -> tuple[list[dict], float | None]:
        """Interaction events of the scope with `removed` absent from the start: the record holds until the
        first recorded interaction involving a removed entity (nothing differs before it); from just before
        that point the generated model is run forward. Returns (events, divergence start or None)."""
        inter = [e for e in obs if len(e.get("participants", [])) >= 2]
        touched = [float(e["time"]) for e in inter if set(map(str, e["participants"])) & set(removed)]
        if not touched:
            return inter, None                       # the removed entities never interacted: nothing changes
        start = min(touched) - 0.01 * end
        before = [e for e in inter if float(e["time"]) <= start]
        ok, sim = self._run("simulate", scope, removed=removed, start=start, horizon=end)
        if not ok:
            raise RuntimeError(f"simulate failed: {sim}")
        return before + [e for e in sim if float(e["time"]) > start], start

    def _evidence(self, qtype: str, scope: str, question: str) -> tuple[str, dict]:
        ok, ents = self._run("entities", scope)
        if not ok:
            raise RuntimeError(f"entities failed: {ents}")
        names = {str(e["id"]): e["description"] for e in ents}
        ent_txt = "\n".join(f"id {e['id']}: {e['description']}" for e in ents)
        ok, obs = self._run("observed_events", scope)
        ok2, end = self._run("recorded_end", scope)
        if not (ok and ok2):
            raise RuntimeError(f"parsers failed: {obs if not ok else end}")
        end = float(end)
        rec = f"ENTITIES:\n{ent_txt}\n\nRECORDED INTERACTION EVENTS:\n{self._fmt_events(obs, names)}"
        if qtype == "counterfactual":
            args = _json(self.llm([{"role": "user", "content": prompts.ARGS.format(entities=ent_txt, question=question)}]))
            removed = [str(r) for r in args.get("removed", []) if str(r) in names]
            events, start = self._with_removed(scope, removed, obs, end)
            how = ("they never interacted, so the record is unchanged" if start is None else
                   f"the record is unchanged until time {start:g}; after that the model of the process was re-run")
            return (f"{rec}\n\nCOUNTERFACTUAL RUN with {', '.join(names[r] for r in removed) or 'nothing'} removed "
                    f"from the start ({how}):\n{self._fmt_events(events, names)}"), {"removed": removed, "start": start}
        if qtype == "predictive":
            ok, fut = self._run("simulate", scope, start=end, horizon=end * 1.5)
            if not ok:
                raise RuntimeError(f"simulate failed: {fut}")
            after = [e for e in fut if float(e["time"]) > end]
            return (f"{rec}\n\nThe record ends at time {end:g}. EVENTS THE MODEL PREDICTS AFTER THAT (run forward "
                    f"from the last recorded states):\n{self._fmt_events(after, names)}"), {"predicted_after_end": len(after)}
        if qtype == "explanatory":
            inter = [e for e in obs if len(e.get("participants", [])) >= 2]
            rows = []
            for e in ents:
                alt, _ = self._with_removed(scope, [str(e["id"])], obs, end)
                keyset = [(frozenset(map(str, a["participants"])), float(a["time"])) for a in alt]
                gone = [b for b in inter if not any(k == frozenset(map(str, b["participants"]))
                                                    and abs(t - float(b["time"])) <= 0.05 * end for k, t in keyset)]
                rows.append(f"- without {e['description']} (id {e['id']}): these recorded events disappear: "
                            + ("; ".join(f"time {float(b['time']):g} " + " and ".join(names.get(str(p), p) for p in b["participants"])
                                         for b in gone) or "none"))
            return f"{rec}\n\nDEPENDENCY TABLE:\n" + "\n".join(rows), {"entities": len(ents)}
        return self._scope_text(scope), {}

    def answer(self, question: str, instructions: str) -> tuple[str, dict]:
        trace = {"scope": self._scope_of(question)}
        qtype = self.route(question)
        trace["routed_type"] = qtype
        evidence, used_tool = None, False
        if trace["scope"] and qtype != "descriptive" and self.model["passed"]:
            try:
                evidence, info = self._evidence(qtype, trace["scope"], question)
                used_tool, trace["tool"] = True, info
            except Exception as e:
                trace["tool_error"] = str(e)[:500]
        if evidence is None:
            evidence = self._scope_text(trace["scope"]) if trace["scope"] else "(question scope not found)"
        trace["used_tool"] = used_tool
        trace["fallback"] = qtype != "descriptive" and not used_tool
        guide = prompts.ANSWER[qtype] if used_tool or qtype == "descriptive" else prompts.ANSWER["descriptive"]
        reply = self.llm([{"role": "system", "content": instructions},
                          {"role": "user", "content": f"{guide}\n\n{evidence}\n\n{question}"}])
        return reply, trace
