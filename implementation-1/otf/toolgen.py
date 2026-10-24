"""Generate the executable process model for one document, and check it before trusting it.

Step 1 writes the reading functions (entities, recorded_end, inputs, outcomes, params) and checks them: they
run, agree on ids, say where every record was read from, and keep inputs and outcomes apart, so that hiding
the outcomes leaves the inputs intact and the outcomes unrecoverable. Step 2 writes `simulate`, a forward
model, and checks it by forecast: on a blinded copy of a scope (outcomes after a cut hidden, inputs kept) it
must reproduce the hidden outcomes. Copying the record cannot pass: what it would copy is hidden.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import prompts, records, sandbox
from .navmap import schema_summary

PASS_F1 = 0.4          # mean record-match F1 over the checked scopes; calibrated on the pilot20 dev set (2026-10-22)
TIME_TOL_FRAC = 0.05   # records match if their times differ by at most this fraction of the recorded period
REPLAY_MAX_F1 = 0.05   # step 1: the outcome reader may recover at most this much of the hidden outcomes
READERS = ("entities", "recorded_end", "inputs", "outcomes", "params")


def scopes(nav: dict) -> list[str]:
    return [n["title"] for n in nav["nodes"] if n["level"] == 0 and n.get("children")]


def intro_text(nav: dict) -> str:
    """The document's own description: text before the outline, else the first top-level node without
    children (front matter)."""
    if nav["intro_text"].strip():
        return nav["intro_text"]
    for n in nav["nodes"]:
        if n["level"] == 0 and not n.get("children"):
            return "\n".join(n.get("lines", [])) or n.get("text", "")
    return ""


def extract_code(reply: str) -> str:
    m = re.findall(r"```(?:python)?\s*\n(.*?)```", reply or "", flags=re.S)
    return max(m, key=len) if m else (reply or "")


class ReadError(Exception):
    pass


def read_scope(code: str, map_path: Path, scope: str) -> dict:
    """Run the reading functions on one scope: {entities, end, inputs, outcomes, params, t0, period}."""
    funcs = [f for f in READERS if f != "params" or "def params(" in code]
    ok, res = sandbox.run_many(code, [(f, [scope], {}) for f in funcs], map_path)
    if not ok:
        raise ReadError(f"the code does not run: {res}")
    out = {}
    for f, (ok_f, val) in zip(funcs, res):
        if not ok_f:
            raise ReadError(f"{f}('{scope}') failed: {val}")
        out[f] = val
    try:
        ents = [{"id": str(e["id"]), "description": str(e.get("description", ""))} for e in out["entities"]]
        end = None if out["recorded_end"] is None else float(out["recorded_end"])
        ins, outs = list(out["inputs"]), list(out["outcomes"])
        for r in ins + outs:
            r["entities"] = [str(e) for e in r.get("entities") or []]
        prm = {str(k): v for k, v in (out.get("params") or {}).items()}
    except (TypeError, ValueError, KeyError, AttributeError) as e:
        raise ReadError(f"malformed output on '{scope}': {type(e).__name__}: {e}")
    times = [t for t in (records.rtime(r) for r in ins + outs) if t is not None]
    t0 = min(times) if times else 0.0
    return {"entities": ents, "end": end, "inputs": ins, "outcomes": outs, "params": prm, "t0": t0,
            "period": max((end - t0) if end is not None else 1.0, 1e-9)}


def hidden_outcomes(r: dict, cut: float | None) -> list[dict]:
    if r["end"] is None:
        return r["outcomes"]
    return [o for o in r["outcomes"] if records.rtime(o) is None or (cut is not None and records.rtime(o) > cut)]


def after(recs: list[dict], cut: float | None) -> list[dict]:
    return recs if cut is None else [x for x in recs if records.rtime(x) is None or records.rtime(x) > cut]


def blinded_map(nav: dict, map_path: Path, scope: str, r: dict, cut: float | None) -> Path:
    p = map_path.with_name(f"blind_{abs(hash(scope)) % 10**8}.json")
    p.write_text(json.dumps(records.blind(nav, scope, r["inputs"], r["outcomes"], cut)))
    return p


def _cut(r: dict) -> float | None:
    return records.first_outcome_cut(r["outcomes"], r["t0"], r["end"])


def diagnose(nav: dict, scope: str, r: dict) -> str:
    """What the reading functions returned on one scope, and list lines / table rows that no record was read
    from, so a failed attempt can see why (e.g. a pattern that matches no line)."""
    idx = {n["node_id"]: n for n in nav["nodes"]}
    clip = lambda v: json.dumps(v, default=str)[:300]
    out = [f"WHAT YOUR FUNCTIONS RETURNED on scope '{scope}': {len(r['entities'])} entities "
           f"(first: {clip(r['entities'][:1])}), recorded_end = {r['end']}, {len(r['inputs'])} inputs "
           f"(first: {clip(records.strip_src(r['inputs'][:1]))}), {len(r['outcomes'])} outcomes "
           f"(first: {clip(records.strip_src(r['outcomes'][:1]))}), params = {clip(r['params'])}"]
    try:
        used = records.units(r["inputs"] + r["outcomes"], idx)
    except ValueError:
        used = set()
    for n in records.descendants(nav, scope):
        if n["kind"] == "list":
            unread = [line for k, line in enumerate(n["lines"]) if (n["node_id"], k, None) not in used]
            if unread:
                out.append(f"- {len(unread)} of {len(n['lines'])} lines of '{n['title']}' are not the src of any "
                           f"input or outcome, e.g.: " + " | ".join(repr(l[:160]) for l in unread[:4]))
        elif n["kind"] == "table":
            rows = {k for (m, k, _) in used if m == n["node_id"]}
            if len(rows) < len(n["table"]["rows"]):
                out.append(f"- {len(n['table']['rows']) - len(rows)} of {len(n['table']['rows'])} rows of table "
                           f"'{n['title']}' are not the src of any input or outcome")
    return "\n".join(out)


def check_parsers(code: str, nav: dict, map_path: Path, n_scopes: int = 4) -> dict:
    """Step-1 check. On a few scopes: the functions run; ids agree; outcome times lie in the recorded range;
    every src points to a real cell or line; and on the blinded copy the inputs read the same while the
    outcomes are no longer found. A failure report shows what the functions returned on one scope."""
    problems, n_out, first = [], 0, None
    idx = {n["node_id"]: n for n in nav["nodes"]}
    for sc in scopes(nav)[:n_scopes]:
        try:
            r = read_scope(code, map_path, sc)
        except ReadError as e:
            return {"passed": False, "error": str(e)}
        first = first or (sc, r)
        ids = {e["id"] for e in r["entities"]}
        if not ids:
            problems.append(f"entities('{sc}') returned no entities")
        n_out += len(r["outcomes"])
        for fn, recs in (("inputs", r["inputs"]), ("outcomes", r["outcomes"])):
            for x in recs:
                bad = [e for e in x["entities"] if e not in ids]
                if bad:
                    problems.append(f"{fn}('{sc}') uses entities {bad[:3]} that are not ids from entities() "
                                    f"(ids are {sorted(ids)[:12]}); record: {json.dumps(x)[:200]}")
                    break
                if not x.get("src"):
                    problems.append(f"{fn}('{sc}') returned a record without src (every record must say which "
                                    f"cells or lines it was read from): {json.dumps(x)[:200]}")
                    break
        for o in r["outcomes"]:
            t = records.rtime(o)
            if r["end"] is None and t is not None:
                problems.append(f"recorded_end('{sc}') is None (no time) but an outcome has time {t}")
                break
            if r["end"] is not None and t is not None and not (r["t0"] - 1e-9 <= t <= r["end"] + 1e-9):
                problems.append(f"outcomes('{sc}') time {t} outside the recorded range [{r['t0']:g}, {r['end']:g}]")
                break
        try:
            records.units(r["inputs"] + r["outcomes"], idx)
        except ValueError as e:
            problems.append(f"'{sc}': bad src: {e}")
            continue
        cut = _cut(r)
        hidden = hidden_outcomes(r, cut)
        if problems or not hidden:
            continue
        bp = blinded_map(nav, map_path, sc, r, cut)
        ok, res = sandbox.run_many(code, [("inputs", [sc], {}), ("outcomes", [sc], {})], bp)
        bp.unlink(missing_ok=True)
        if not ok or not res[0][0]:
            problems.append(f"'{sc}': inputs() fails on the copy in which the outcomes are hidden (hidden cells are "
                            "empty strings '', hidden rows and lines are removed); read only the cells your src lists. "
                            f"Error: {(res if not ok else res[0][1])[-600:]}")
            continue
        b_in = res[0][1]
        b_out = res[1][1] if res[1][0] else []
        if records.canon(b_in) != records.canon(r["inputs"]):
            problems.append(f"'{sc}': inputs() reads differently once the outcomes are hidden (cells after time "
                            f"{cut} not listed in any input's src are hidden). Include in `src` every cell your "
                            "inputs() reads, also its time and entity cells")
            continue
        try:
            for x in b_out:
                x["entities"] = [str(e) for e in x.get("entities") or []]
            f1, _, _ = records.record_f1(hidden, after(b_out, cut), TIME_TOL_FRAC * r["period"],
                                         records.value_tols(r["outcomes"]))
        except (TypeError, ValueError, AttributeError):
            f1 = 0.0
        if f1 > REPLAY_MAX_F1:
            problems.append(f"'{sc}': with the outcomes hidden, outcomes() still finds them (F1 {f1:.2f}): the copy "
                            "still shows them, so some outcome data is being read from cells marked as inputs, or "
                            "outcomes are read from cells not listed in their src")
    if n_out == 0:
        problems.append("outcomes() found no records in any checked scope; parse what the process produces")
    if not problems:
        return {"passed": True, "error": None}
    return {"passed": False, "error": "; ".join(problems[:6]) + ("\n" + diagnose(nav, *first) if first else "")}


def check_model(code: str, nav: dict, map_path: Path, n_scopes: int = 6, max_scan: int = 12) -> dict:
    """Forecast check: for each checked scope, cut just before its first recorded outcome, hide every later
    outcome (blinded copy, inputs kept), run simulate from the cut with the recorded inputs, and compare its
    outcomes with the hidden ones. Timeless scopes hide every outcome and must recompute them. simulate must
    also react to its inputs (sensitivity guard)."""
    report = {"scopes": [], "mean_f1": 0.0, "passed": False, "error": None, "sensitive": False}
    for sc in scopes(nav)[:max_scan]:
        if len(report["scopes"]) >= n_scopes:
            break
        try:
            r = read_scope(code, map_path, sc)
        except ReadError as e:
            report["error"] = str(e)
            return report
        cut = _cut(r)
        hidden = hidden_outcomes(r, cut)
        if not hidden:
            continue
        kw = {"inputs": r["inputs"], "params": r["params"], "start": cut, "horizon": r["end"]}
        bp = blinded_map(nav, map_path, sc, r, cut)
        ok_s, sim = sandbox.run(code, "simulate", bp, [sc], kw)
        try:
            if not ok_s:
                report["error"] = f"simulate('{sc}', start={cut}) failed: {sim}"
                return report
            ids = {e["id"] for e in r["entities"]}
            for x in sim:
                x["entities"] = [str(e) for e in x.get("entities") or []]
            bad = sorted({e for x in sim for e in x["entities"] if e not in ids})
            if bad:
                report["error"] = (f"simulate('{sc}') returned entities {bad[:5]} that are not ids from entities() "
                                   f"(the ids are {sorted(ids)[:12]}); use the same ids")
                return report
            pred = after(sim, cut)
            f1, missed, extra = records.record_f1(hidden, pred, TIME_TOL_FRAC * r["period"],
                                                  records.value_tols(r["outcomes"]))
            if not report["sensitive"]:
                report["sensitive"] = _reacts(code, bp, sc, r, hidden, kw, sim)
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            report["error"] = f"malformed output on '{sc}': {type(e).__name__}: {e}"
            return report
        finally:
            bp.unlink(missing_ok=True)
        report["scopes"].append({"scope": sc, "start": None if cut is None else round(cut, 3), "f1": round(f1, 3),
                                 "hidden": len(hidden), "predicted": len(pred),
                                 "missed": records.strip_src(missed[:4]), "extra": records.strip_src(extra[:4])})
    if not report["scopes"]:
        report["error"] = "outcomes() returned no records for any checked scope, so the model cannot be checked."
        return report
    report["mean_f1"] = round(sum(s["f1"] for s in report["scopes"]) / len(report["scopes"]), 3)
    report["passed"] = report["mean_f1"] >= PASS_F1 and report["sensitive"]
    return report


def _reacts(code: str, bp: Path, sc: str, r: dict, hidden: list[dict], kw: dict, sim: list[dict]) -> bool:
    """Does simulate's output change when its inputs change? Timed: the inputs of the entities in the first
    hidden outcome are removed. Timeless: every numeric input field is doubled."""
    if r["end"] is None:
        changed = json.loads(json.dumps(r["inputs"]))
        for x in changed:
            for k, v in (x.get("fields") or {}).items():
                if records.num(v) is not None:
                    x["fields"][k] = records.num(v) * 2
    else:
        first = min(hidden, key=lambda o: records.rtime(o) if records.rtime(o) is not None else records.INF)
        gone = records.ents(first)
        changed = [x for x in r["inputs"] if not records.ents(x) & gone]
        if len(changed) == len(r["inputs"]):
            return False
    ok, sim2 = sandbox.run(code, "simulate", bp, [sc], {**kw, "inputs": changed})
    if not ok or not isinstance(sim2, list):
        return True                    # it failed on the changed inputs, so it does read them
    return records.canon(sim2) != records.canon(sim)


def short_report(rep: dict) -> str:
    if rep["error"]:
        return rep["error"]
    lines = [f"mean record-match F1 = {rep['mean_f1']} (need {PASS_F1})"]
    if not rep.get("sensitive", True):
        lines.append("simulate ignores its `inputs` argument: changing the inputs did not change its output "
                     "on any checked scope. Read the given inputs only from the `inputs` argument.")
    for s in rep["scopes"]:
        lines.append(f"- scope '{s['scope']}' (start {s['start']}): F1 {s['f1']}, {s['hidden']} hidden outcomes, model "
                     f"produced {s['predicted']}; missed (hidden but not produced): {json.dumps(s['missed'])[:600]}; "
                     f"extra (produced but not hidden): {json.dumps(s['extra'])[:600]}")
    return "\n".join(lines)


EXPLORE_OUTPUT_CHARS = 3000


def _blocks(reply: str) -> list[tuple[str, str]]:
    """All fenced blocks of a reply as (language tag, code); an untagged block counts as python."""
    return [((lang.lower() or "python"), code)
            for lang, code in re.findall(r"```(\w*)[ \t]*\n(.*?)```", reply or "", flags=re.S)]


def _simulator_agent(llm, nav, map_path, context, parsers, ex_fields, attempts, log, sim_tries, n_explore,
                     min_explore=3):
    """Step 2 as a conversation: the model may run exploration snippets on the real data (the checked parsers
    and `doc` are available; printed output is returned) and submits simulate() blocks that go through
    check_model; check failures come back into the same conversation. At most `sim_tries` submissions and
    `n_explore` exploration runs (all explore blocks of one reply run together as one run)."""
    messages = [{"role": "system", "content": prompts.AGENT_SYSTEM},
                {"role": "user", "content": prompts.SIMULATOR_USER.format(
                    context=context, parsers=parsers, **ex_fields,
                    feedback=prompts.EXPLORE_HOWTO.format(n_explore=n_explore))}]
    sims, explored, nudges = [], 0, 0
    while len(sims) < sim_tries and nudges < 6:
        reply = llm(messages)
        messages.append({"role": "assistant", "content": reply or "(empty reply)"})
        blocks = _blocks(reply)
        submit = [c for lang, c in blocks if lang != "explore" and "def simulate(" in c]
        explore = [c for lang, c in blocks if lang == "explore" or ("def simulate(" not in c and lang != "explore")]
        if not blocks:
            nudges += 1
            messages.append({"role": "user", "content": "Reply with an ```explore block or a final ```python block."})
            continue
        if not submit or explored < min_explore:
            if not explore or explored >= n_explore:
                nudges += 1
                messages.append({"role": "user", "content": (
                    f"Before submitting, run at least {min_explore} ```explore blocks to measure the data "
                    f"({explored} so far)." if explored < min_explore else
                    "No explore runs are left; submit the final ```python block with simulate().")})
                continue
            explored += 1
            ok, out = sandbox.run_script(parsers + "\n\n" + "\n\n".join(explore), map_path)
            text = (out if ok else f"ERROR: {out}") or "(nothing was printed; use print() to see values)"
            text = text[:EXPLORE_OUTPUT_CHARS]
            log(f"explore {explored}: {'ok' if ok else 'error'}, {len(text)} chars")
            attempts.append({"step": "explore", "try": explored, "code": "\n\n".join(explore), "output": text})
            messages.append({"role": "user", "content": prompts.EXPLORE_OUTPUT.format(left=n_explore - explored,
                                                                                       output=text)})
            continue
        code = submit[-1]
        full = parsers + "\n\n# ---- step 2: forward model ----\n" + code
        rep = check_model(full, nav, map_path)
        attempts.append({"step": "simulate", "try": len(sims) + 1, "report": rep, "code": full,
                         "explore_runs_before": explored})
        sims.append(attempts[-1])
        log(f"simulate attempt {len(sims)} (after {explored} explore runs): {short_report(rep)}")
        if rep["passed"]:
            break
        messages.append({"role": "user", "content": prompts.CHECK_FAILED.format(
            left_submits=sim_tries - len(sims), left_explore=n_explore - explored, report=short_report(rep))})
    return sims


def _example_fields(parsers: str, map_path: Path, scope: str) -> dict:
    """The checked parsers' real output on one scope that is not among the checked ones."""
    try:
        r = read_scope(parsers, map_path, scope)
    except ReadError as e:
        r = {"entities": str(e), "end": None, "inputs": [], "outcomes": [], "params": {}}
    clip = lambda v: json.dumps(v, default=str)[:1500]
    return {"example_scope": scope, "example_entities": clip(r["entities"]), "example_end": r["end"],
            "example_inputs": clip(r["inputs"]), "example_outcomes": clip(r["outcomes"]),
            "example_params": clip(r["params"])}


def generate_model(llm, nav: dict, map_path: Path, max_tries: int = 3, log=None,
                   parser_tries: int = 3, sim_tries: int = 5, n_explore: int = 8, restarts: int = 3,
                   library: list[dict] | None = None) -> dict:
    """Two checked steps: (1) reading functions, (2) a forward model built on the checked reading functions,
    written by a code-executing agent that can explore the data first. llm(messages) -> reply text.
    Returns {code, passed, mean_f1, tries, attempts}."""
    log = log or (lambda s: None)
    for k, entry in enumerate(library or [], 1):   # verified models for documents of the same structure
        rep = check_model(entry["code"], nav, map_path)
        log(f"library model {k} (from {entry.get('source')}): {short_report(rep)}")
        if rep["passed"]:
            return {"code": entry["code"], "passed": True, "mean_f1": rep["mean_f1"], "tries": 0,
                    "attempts": [{"step": "library", "report": rep, "source": entry.get("source")}],
                    "failed_step": None, "reused_from": entry.get("source")}
    context = prompts.DOC_CONTEXT.format(intro=intro_text(nav), schema=schema_summary(nav))
    system = {"role": "system", "content": prompts.GENERATOR_SYSTEM}
    attempts, feedback, parsers = [], "", None
    for t in range(1, parser_tries + 1):
        code = extract_code(llm([system, {"role": "user", "content": prompts.PARSERS_USER.format(
            context=context, feedback=feedback)}]))
        rep = check_parsers(code, nav, map_path)
        attempts.append({"step": "parsers", "try": t, "report": rep, "code": code})
        log(f"parsers attempt {t}: {'passed' if rep['passed'] else rep['error']}")
        if rep["passed"]:
            parsers = code
            break
        feedback = prompts.FEEDBACK.format(report=rep["error"], code=code)
    if parsers is None:
        return {"code": "", "passed": False, "mean_f1": 0.0, "tries": len(attempts), "attempts": attempts,
                "failed_step": "parsers"}
    ex_fields = _example_fields(parsers, map_path, scopes(nav)[-1])
    sims = []
    for r in range(1, restarts + 1):          # fresh conversations: a stuck one does not poison the next
        got = _simulator_agent(llm, nav, map_path, context, parsers, ex_fields, attempts, log, sim_tries, n_explore)
        sims += got
        log(f"simulator conversation {r}: best F1 {max((a['report']['mean_f1'] for a in got), default=0.0)}")
        if any(a["report"]["passed"] for a in got):
            break
    if not sims:
        return {"code": parsers, "passed": False, "mean_f1": 0.0, "tries": len(attempts), "attempts": attempts,
                "failed_step": "simulate"}
    best = max(sims, key=lambda a: (a["report"]["error"] is None, a["report"]["passed"], a["report"]["mean_f1"]))
    return {"code": best["code"], "passed": best["report"]["passed"], "mean_f1": best["report"]["mean_f1"],
            "tries": len(attempts), "attempts": attempts, "failed_step": None if best["report"]["passed"] else "simulate"}
