"""OTF engine: Navigation Map -> generated, checked process model -> per-question-type tools -> answer.

prepare(pdf) builds the map (no LLM) and generates + checks the process model (LLM; one-time cost).
answer(question) routes the question to a type, runs that type's tool in the sandbox, and makes one final
LLM call with the tool's evidence. What-if questions become patches on the recorded inputs or constants,
applied here (not by the generated code) before the checked `simulate` is re-run from the point where the
change can first matter. If the model failed its check, or a tool run fails, the question falls back to
reading the scope's sections (recorded in the trace).
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from . import library, prompts, records, sandbox
from .navmap import build_map
from .toolgen import TIME_TOL_FRAC, ReadError, generate_model, read_scope, scopes

MAX_DEPENDENCY_ENTITIES = 12
MAX_LISTED = 150
MAX_DIFF_LINES = 60


def _json(text: str) -> dict:
    """The last top-level JSON object in a reply (nested objects included)."""
    text = re.sub(r"```(?:json)?", "", text or "")
    decoder, found, i = json.JSONDecoder(), {}, 0
    while (i := text.find("{", i)) != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(obj, dict):
            found = obj
        i = end
    return found


class ToolError(Exception):
    pass


class OTFEngine:
    def __init__(self, llm, work_dir: Path, max_tries: int = 3, log=None, ablation: str | None = None):
        """llm(messages) -> reply text; the caller meters its tokens.
        ablation: None, "reading_only" (never use the model) or "no_replay" (re-run from the scope's start)."""
        self.llm, self.work, self.max_tries, self.log = llm, work_dir, max_tries, log or (lambda s: None)
        self.ablation = ablation
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

    # ---------- sandbox runs, cached ----------
    def _cached(self, key, fn):
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        res = fn()
        with self._lock:
            self._cache[key] = res
        return res

    def _records(self, scope: str) -> dict:
        """The scope's records; outcome kinds that only follow a fixed recording schedule are left out, as in
        the check (records.schedule_kinds)."""
        def read():
            try:
                r = read_scope(self.model["code"], self.map_path, scope)
            except ReadError as e:
                return e
            r["outcomes"] = r["informative"]
            return r
        r = self._cached(("read", scope), read)
        if isinstance(r, Exception):
            raise ToolError(str(r))
        return r

    def _simulate(self, scope: str, inputs: list, params: dict, start, horizon) -> list[dict]:
        kw = {"inputs": inputs, "params": params, "start": start, "horizon": horizon}
        key = ("simulate", scope, json.dumps(kw, sort_keys=True, default=str))
        ok, res = self._cached(key, lambda: sandbox.run(self.model["code"], "simulate", self.map_path, [scope], kw))
        if not ok or not isinstance(res, list):
            raise ToolError(f"simulate failed: {res}"[:500])
        for x in res:
            x["entities"] = [str(e) for e in x.get("entities") or []]
        return records.drop_kinds(res, self._records(scope)["schedule_kinds"])

    # ---------- helpers ----------
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

    @staticmethod
    def _names(r: dict) -> dict:
        return {e["id"]: e["description"] for e in r["entities"]}

    @staticmethod
    def _named_in(question: str, names: dict) -> set:
        """Entities a question mentions: by description, or by an id that is not a bare number."""
        low = question.lower()
        hit = {i for i, d in names.items() if len(d) >= 3 and d.lower() in low}
        hit |= {i for i in names if not i.isdigit() and len(i) >= 2 and re.search(rf"(?<!\w){re.escape(i)}(?!\w)", question)}
        return hit

    @staticmethod
    def _examples(r: dict) -> str:
        by = {}
        for x in r["inputs"]:
            by.setdefault(records.kind(x), {k: v for k, v in x.items() if k != "src"})
        return "\n".join(json.dumps(v, default=str) for v in by.values()) or "(no inputs)"

    def _tol(self, r: dict) -> float:
        return TIME_TOL_FRAC * r["period"]

    def _value_tols(self, r: dict) -> tuple[dict, float]:
        """(per-kind tolerance, relative tolerance) for comparing a what-if with the record. Paired what-ifs
        (v3.4) leave recorded values untouched except where the change acts, so any difference is real: exact.
        The unpaired no-replay ablation mixes in the model's own errors, so it keeps the record's tolerance."""
        return (records.value_tols(r["outcomes"]), 0.05) if self.ablation == "no_replay" else ({}, 0.0)

    def _recorded(self, r: dict, focus_ids: set) -> str:
        names = self._names(r)
        ent_txt = "\n".join(f"id {e['id']}: {e['description']}" for e in r["entities"])
        listed = records.focus(r["outcomes"], focus_ids, MAX_LISTED)
        more = len(r["outcomes"]) - len(listed)
        return (f"ENTITIES:\n{ent_txt}\n\nRECORDED OUTCOMES:\n{records.fmt_list(listed, names)}"
                + (f"\n({more} more recorded outcomes not listed)" if more > 0 else ""))

    def _fmt_diff(self, d: dict, names: dict, focus_ids: set) -> str:
        lines = [f"no longer happens: {records.fmt(x, names)}" for x in records.focus(d["gone"], focus_ids)]
        lines += [f"newly happens: {records.fmt(x, names)}" for x in records.focus(d["new"], focus_ids)]
        lines += [f"value changed: {records.fmt(a, names)} (was {b.get('value')})" for b, a in d["changed"]]
        more = len(lines) - MAX_DIFF_LINES
        return "\n".join(lines[:MAX_DIFF_LINES]) + (f"\n({more} more differences)" if more > 0 else "") \
            if lines else "(no differences)"

    # ---------- counterfactual runs ----------
    def _what_if(self, scope: str, r: dict, patches: list[dict]) -> dict:
        """The scope's outcomes with `patches` applied: the record up to t*, then the model re-run from just
        before t*. t* is the first recorded outcome, at or after the change, that involves an entity whose inputs
        changed (never, if there is none: the record stands), or the time of the change itself when no entity's
        inputs changed (a constant). Timeless scopes are recomputed in full."""
        names = self._names(r)
        ap = records.apply_patches(r["inputs"], r["params"], r["outcomes"], patches, names, r["t0"])
        if ap["errors"]:
            raise ToolError("; ".join(ap["errors"])[:500])
        if r["end"] is None:
            base = self._simulate(scope, r["inputs"], r["params"], None, None)
            new = self._simulate(scope, ap["inputs"], ap["params"], None, None)
            # paired: the record, with what the change alters between the two recomputations
            trace = records.apply_delta(r["outcomes"], base, new, self._tol(r), records.value_tols(r["outcomes"]),
                                        ap["overrides"], None, None)
            return {"trace": trace, "baseline": r["outcomes"], "t_star": None, "changed_inputs": ap,
                    "timeless": True}
        end, eps = r["end"], 0.01 * r["period"]
        t_c = r["t0"] if ap["t_c"] is None else ap["t_c"]
        if self.ablation == "no_replay":
            t_star = r["t0"]
        elif ap["touched"]:
            t_star = max(t_c, min((records.rtime(o) for o in r["outcomes"] if records.rtime(o) is not None
                                   and records.rtime(o) >= t_c - eps and records.ents(o) & ap["touched"]),
                                  default=records.INF))
        else:
            t_star = t_c
        if t_star == records.INF and not ap["overrides"]:
            return {"trace": r["outcomes"], "baseline": r["outcomes"], "t_star": None, "changed_inputs": ap,
                    "timeless": False}
        if t_star == records.INF:
            return {"trace": records.apply_overrides(r["outcomes"], ap["overrides"]), "baseline": r["outcomes"],
                    "t_star": None, "changed_inputs": ap, "timeless": False}
        s = t_star - eps
        run = [x for x in self._simulate(scope, ap["inputs"], ap["params"], s, end)
               if records.rtime(x) is None or records.rtime(x) > s]
        if self.ablation == "no_replay":         # the ablation keeps the unpaired run: the model alone from t0
            kept = [o for o in r["outcomes"] if records.rtime(o) is not None and records.rtime(o) <= s]
            return {"trace": records.apply_overrides(kept + run, ap["overrides"]) if ap["overrides"] else kept + run,
                    "baseline": r["outcomes"], "t_star": t_star, "changed_inputs": ap, "timeless": False}
        # paired (v3.4): the same model from the same point without the change; only the difference between the
        # two runs is applied to the record, so the model's own errors cancel out
        base = [x for x in self._simulate(scope, r["inputs"], r["params"], s, end)
                if records.rtime(x) is None or records.rtime(x) > s]
        trace = records.apply_delta(r["outcomes"], base, run, self._tol(r), records.value_tols(r["outcomes"]),
                                    ap["overrides"], s, r["period"])
        return {"trace": trace, "baseline": r["outcomes"], "t_star": t_star, "changed_inputs": ap, "timeless": False}

    def _patches(self, r: dict, question: str) -> list[dict]:
        time = ("no time (the records are figures, not a process over time)" if r["end"] is None else
                f"records run from {r['t0']:g} to {r['end']:g}")
        ent_txt = "\n".join(f"id {e['id']}: {e['description']}" for e in r["entities"])
        p = _json(self.llm([{"role": "user", "content": prompts.PATCH.format(
            entities=ent_txt, examples=self._examples(r), params=json.dumps(r["params"]), time=time,
            question=question)}])).get("patches")
        if not isinstance(p, list) or not p:
            raise ToolError("no change could be extracted from the question")
        return [x for x in p if isinstance(x, dict)]

    # ---------- per-type evidence ----------
    def _evidence(self, qtype: str, scope: str, question: str) -> tuple[str, dict]:
        r = self._records(scope)
        names = self._names(r)
        focus_ids = self._named_in(question, names)
        rec = self._recorded(r, focus_ids)
        if qtype == "counterfactual":
            patches = self._patches(r, question)
            w = self._what_if(scope, r, patches)
            d = records.diff(w["baseline"], w["trace"], self._tol(r), *self._value_tols(r))
            if (w["timeless"] or not r["outcomes"]) and not (d["gone"] or d["new"] or d["changed"]):
                # nothing the model computes depends on the change (a timeless scope, or one where it reads no
                # outcomes at all): the tool has nothing to add, so the question is read instead (v3.4.2)
                raise ToolError("the change alters nothing the model of the document computes")
            change = json.dumps(patches)
            if w["timeless"]:
                how = "the figures were recomputed by the model of the document with the changed inputs"
                ch = "\n".join(records.fmt(x, names) for x in w["changed_inputs"]["inputs"]
                               if x not in r["inputs"]) or "(none)"
                body = (f"CHANGED INPUTS:\n{ch}\n\nRECOMPUTED OUTCOMES:\n"
                        f"{records.fmt_list(records.focus(w['trace'], focus_ids, MAX_LISTED), names)}")
            else:
                how = ("the change never matters, so the record is unchanged" if w["t_star"] is None else
                       f"the record is unchanged until time {w['t_star']:g}; after that the model of the process was re-run")
                body = (f"COUNTERFACTUAL RUN:\n"
                        f"{records.fmt_list(records.focus(w['trace'], focus_ids, MAX_LISTED), names)}")
            return (f"{rec}\n\nTHE CHANGE: {change} ({how})\n\n{body}\n\nDIFFERENCES:\n"
                    f"{self._fmt_diff(d, names, focus_ids)}"), {"patches": patches, "t_star": w["t_star"]}
        if r["end"] is None:
            raise ToolError(f"{qtype} question on a scope without time")
        if qtype == "predictive":
            end = r["end"]
            future = [records.rtime(x) for x in r["inputs"] if records.rtime(x) is not None and records.rtime(x) > end]
            horizon = max(future) if future else end + 0.5 * (end - r["t0"])
            fut = [x for x in self._simulate(scope, r["inputs"], r["params"], end, horizon)
                   if records.rtime(x) is not None and records.rtime(x) > end]
            return (f"{rec}\n\nThe record ends at time {end:g}. OUTCOMES THE MODEL PREDICTS AFTER THAT (run forward "
                    f"from the last recorded states to time {horizon:g}):\n"
                    f"{records.fmt_list(records.focus(fut, focus_ids, MAX_LISTED), names)}"), \
                {"predicted_after_end": len(fut), "horizon": horizon}
        if qtype == "explanatory":
            return self._explanatory(scope, r, question, rec, names, focus_ids)
        return self._scope_text(scope), {}

    def _explanatory(self, scope, r, question, rec, names, focus_ids):
        tol = self._tol(r)
        who = [e["id"] for e in r["entities"]]
        if len(who) > MAX_DEPENDENCY_ENTITIES:
            who = [i for i in who if i in focus_ids][:MAX_DEPENDENCY_ENTITIES]
        rows = []
        for eid in who:
            w = self._what_if(scope, r, [{"op": "remove", "select": {"entity": eid}}])
            gone = records.diff(r["outcomes"], w["trace"], tol, records.value_tols(r["outcomes"]))["gone"]
            rows.append(f"- without {names[eid]} (id {eid}): these recorded outcomes disappear: "
                        + ("; ".join(records.fmt(g, names) for g in records.focus(gone, focus_ids, 12)) or "none"))
        checks = self._choice_checks(scope, r, question, names, tol)
        return (f"{rec}\n\nDEPENDENCY TABLE:\n" + ("\n".join(rows) or "(none)")
                + (f"\n\nCHOICE CHECKS (re-runs with that cause taken away):\n{checks}" if checks else "")), \
            {"entities": len(who), "choice_checks": bool(checks)}

    def _choice_checks(self, scope, r, question, names, tol) -> str:
        """Per-choice but-for test: re-run without each candidate cause; does the target outcome still happen?"""
        if not re.search(r"^\s*\d+:\s", question, flags=re.M):        # no numbered candidates listed
            return ""
        listed = records.focus(r["outcomes"], self._named_in(question, names), MAX_LISTED)
        numbered = "\n".join(f"{k}. {records.fmt(o, names)}" for k, o in enumerate(listed))
        ent_txt = "\n".join(f"id {e['id']}: {e['description']}" for e in r["entities"])
        try:
            got = _json(self.llm([{"role": "user", "content": prompts.CAUSES.format(
                entities=ent_txt, examples=self._examples(r), outcomes=numbered, question=question)}]))
            target = listed[int(got["target"])]
        except (KeyError, ValueError, TypeError, IndexError):
            return ""
        out = []
        for cid, patches in (got.get("choices") or {}).items():
            if not isinstance(patches, list) or not patches:
                out.append(f"- choice {cid}: not a cause that can be taken away by changing inputs")
                continue
            try:
                w = self._what_if(scope, r, [p for p in patches if isinstance(p, dict)])
            except ToolError as e:
                out.append(f"- choice {cid}: could not be checked ({str(e)[:120]})")
                continue
            same, _, _ = records.pairs([target], w["trace"], tol, None)
            if not same:
                res = "the outcome no longer happens"
            elif records.num(target.get("value")) is not None and \
                    not records._value_close(target, same[0][1], *self._value_tols(r)):
                res = f"the outcome changes: value {target.get('value')} becomes {same[0][1].get('value')}"
            else:
                res = "the outcome still happens"
            out.append(f"- choice {cid}: without it, {res}")
        return f"target outcome: {records.fmt(target, names)}\n" + "\n".join(out) if out else ""

    def answer(self, question: str, instructions: str) -> tuple[str, dict]:
        trace = {"scope": self._scope_of(question)}
        qtype = self.route(question)
        trace["routed_type"] = qtype
        evidence, used_tool = None, False
        if trace["scope"] and qtype != "descriptive" and self.model["passed"] and self.ablation != "reading_only":
            try:
                evidence, info = self._evidence(qtype, trace["scope"], question)
                used_tool, trace["tool"] = True, info
            except Exception as e:
                trace["tool_error"] = f"{type(e).__name__}: {e}"[:500]
        if evidence is None:
            evidence = self._scope_text(trace["scope"]) if trace["scope"] else "(question scope not found)"
        trace["used_tool"] = used_tool
        trace["fallback"] = qtype != "descriptive" and not used_tool
        guide = prompts.ANSWER[qtype] if used_tool or qtype == "descriptive" else prompts.ANSWER["descriptive"]
        if used_tool and self.ablation != "tool_only":
            # v3.4.3: the scope's own sections always come with the tool result, so the answer step sees at least
            # what the reading fallback sees (unchanged figures, conditions a what-if cannot take away). pilot20:
            # Qwen generated model explanatory 25 vs 20 of 36, gpt-oss oracle 20 vs 25; manufacturing (Qwen) needed it
            guide = f"{prompts.RECORD_AND_TOOL}\n\n{guide}"
            evidence = (f"THE DOCUMENT'S SECTIONS FOR THIS SCOPE:\n{self._scope_text(trace['scope'])}\n\n"
                        f"TOOL RESULT:\n{evidence}")
        reply = self.llm([{"role": "system", "content": instructions},
                          {"role": "user", "content": f"{guide}\n\n{evidence}\n\n{question}"}])
        return reply, trace
