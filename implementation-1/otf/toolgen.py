"""Generate the executable process model for one document, and check it before trusting it.

The check runs the model's factual replay (nothing removed) on a few scopes and compares the interaction
events it produces with the events the document records (same participants, close in time). A failed
check is fed back to the model with the mismatches, up to `max_tries` attempts.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import prompts, sandbox
from .navmap import schema_summary

PASS_F1 = 0.4          # mean event-match F1 over the checked scopes; calibrated on the pilot20 dev set (2026-10-22)
TIME_TOL_FRAC = 0.05   # events match if their times differ by at most this fraction of the recorded period


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


def event_f1(observed: list[dict], simulated: list[dict], tol: float) -> tuple[float, list, list]:
    def key(e):
        return frozenset(map(str, e.get("participants", [])))
    obs = [e for e in observed if len(e.get("participants", [])) >= 2]
    sim = [e for e in simulated if len(e.get("participants", [])) >= 2]
    used, matched = set(), 0
    missed = []
    for o in obs:
        j = next((j for j, s in enumerate(sim) if j not in used and key(s) == key(o)
                  and abs(float(s["time"]) - float(o["time"])) <= tol), None)
        if j is None:
            missed.append(o)
        else:
            used.add(j)
            matched += 1
    extra = [s for j, s in enumerate(sim) if j not in used]
    if not obs and not sim:
        return 1.0, [], []
    p = matched / len(sim) if sim else 0.0
    r = matched / len(obs) if obs else 0.0
    return (2 * p * r / (p + r) if p + r else 0.0), missed, extra


def _is_num(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def blind_scope(nav: dict, scope: str, descriptions: list[str], cut: float = float("-inf")) -> dict:
    """A copy of the map in which `scope` keeps only what a forward model may use: in every table, the rows
    up to time `cut` (time = the first numeric column) plus the first two rows of each entity (its entrance);
    in every list, no line that mentions two or more entities (the recorded interactions). Other scopes are
    untouched, so constants can still be estimated there."""
    blinded = json.loads(json.dumps(nav))
    root = next(n for n in blinded["nodes"] if n["title"] == scope)
    # surface forms of each entity: its full description and the part before any bracket or comma
    forms = []
    for d in descriptions:
        d = d.lower().strip()
        short = re.split(r"[(\[,;]", d)[0].strip()
        forms.append(sorted({f for f in (d, short) if len(f) >= 3}, key=len, reverse=True))
    for n in blinded["nodes"]:
        if n["node_id"] not in root.get("children", []):
            continue
        if n["kind"] == "table":
            seen, kept = {}, []
            for row in n["table"]["rows"]:
                key = next((c for c in row if c and not _is_num(c)), "")
                seen[key] = seen.get(key, 0) + 1
                tcell = next((c for c in row if _is_num(c)), None)
                if seen[key] <= 2 or (tcell is not None and float(tcell) <= cut):
                    kept.append(row)
            n["table"]["rows"] = kept
        elif n["kind"] == "list":
            def mentions(line: str) -> int:
                low, count = line.lower(), 0
                for fs in sorted(forms, key=lambda f: -len(f[0]) if f else 0):
                    hit = next((f for f in fs if f in low), None)
                    if hit:
                        count += 1
                        low = low.replace(hit, " ", 1)
                return count
            n["lines"] = [l for l in n["lines"] if mentions(l) < 2]
        else:
            n["text"] = ""
    return blinded


def check_model(code: str, nav: dict, map_path: Path, n_scopes: int = 6) -> dict:
    """Forecast check: for each checked scope, start just before its first recorded interaction, hide every
    later record (blinded copy), and compare the model's predicted interactions after `start` with the
    recorded ones. Replaying the records cannot pass: they are hidden."""
    report = {"scopes": [], "mean_f1": 0.0, "passed": False, "error": None}
    for sc in scopes(nav)[:n_scopes]:
        ok_o, obs = sandbox.run(code, "observed_events", map_path, [sc])
        ok_e, end = sandbox.run(code, "recorded_end", map_path, [sc])
        ok_n, ents = sandbox.run(code, "entities", map_path, [sc])
        for ok, res, fn in ((ok_o, obs, "observed_events"), (ok_e, end, "recorded_end"), (ok_n, ents, "entities")):
            if not ok:
                report["error"] = f"{fn}('{sc}') failed: {res}"
                return report
        try:
            inter = sorted((e for e in obs if len(e.get("participants", [])) >= 2), key=lambda e: float(e["time"]))
            if not inter:
                continue
            eps = 0.01 * float(end)
            start = float(inter[0]["time"]) - eps
            blind_p = map_path.with_name(f"blind_{abs(hash(sc)) % 10**8}.json")
            blind_p.write_text(json.dumps(blind_scope(nav, sc, [str(e.get("description", "")) for e in ents], start)))
            ok_s, sim = sandbox.run(code, "simulate", blind_p, [sc], {"horizon": float(end), "start": start})
            blind_p.unlink(missing_ok=True)
            if not ok_s:
                report["error"] = f"simulate('{sc}', start={start:g}) failed: {sim}"
                return report
            after = [e for e in inter if float(e["time"]) > start]
            sim = [e for e in sim if float(e["time"]) > start]
            ids = {str(e["id"]) for e in ents}
            bad = sorted({str(p) for e in sim for p in e.get("participants", []) if str(p) not in ids})
            if bad:
                report["error"] = (f"simulate('{sc}') returned participants {bad[:5]} that are not ids from "
                                   f"entities() (the ids are {sorted(ids)}); use the same ids")
                return report
            f1, missed, extra = event_f1(after, sim, TIME_TOL_FRAC * float(end))
        except Exception as e:  # malformed output
            report["error"] = f"malformed output on '{sc}': {type(e).__name__}: {e}"
            return report
        report["scopes"].append({"scope": sc, "start": round(start, 3), "f1": round(f1, 3), "observed": len(after),
                                 "simulated": sum(len(e.get("participants", [])) >= 2 for e in sim),
                                 "missed": missed[:4], "extra": extra[:4]})
    if not report["scopes"]:
        report["error"] = ("observed_events returned no interaction events (events with two or more participants) "
                           "for any checked scope, so the model cannot be checked.")
        return report
    report["mean_f1"] = round(sum(s["f1"] for s in report["scopes"]) / len(report["scopes"]), 3)
    report["passed"] = report["mean_f1"] >= PASS_F1
    return report


def short_report(rep: dict) -> str:
    if rep["error"]:
        return rep["error"]
    lines = [f"mean event-match F1 = {rep['mean_f1']} (need {PASS_F1})"]
    for s in rep["scopes"]:
        lines.append(f"- scope '{s['scope']}' (start {s['start']}): F1 {s['f1']}, recorded {s['observed']} interaction events after start, model "
                     f"produced {s['simulated']}; missed (recorded but not produced): {s['missed']}; "
                     f"extra (produced but not recorded): {s['extra']}")
    return "\n".join(lines)


def check_parsers(code: str, nav: dict, map_path: Path, n_scopes: int = 4) -> dict:
    """Step-1 check: entities / recorded_end / observed_events run, agree on ids, and find interactions."""
    problems, n_inter = [], 0
    for sc in scopes(nav)[:n_scopes]:
        ok_n, ents = sandbox.run(code, "entities", map_path, [sc])
        ok_e, end = sandbox.run(code, "recorded_end", map_path, [sc])
        ok_o, obs = sandbox.run(code, "observed_events", map_path, [sc])
        for ok, res, fn in ((ok_n, ents, "entities"), (ok_e, end, "recorded_end"), (ok_o, obs, "observed_events")):
            if not ok:
                return {"passed": False, "error": f"{fn}('{sc}') failed: {res}"}
        try:
            ids = {str(e["id"]) for e in ents}
            if not ids:
                problems.append(f"entities('{sc}') returned no entities")
            for e in obs:
                parts = [str(x) for x in e["participants"]]
                if len(parts) >= 2:
                    n_inter += 1
                bad = [x for x in parts if x not in ids]
                if bad:
                    problems.append(f"observed_events('{sc}') uses participants {bad} that are not ids from "
                                    f"entities() (ids are {sorted(ids)}); event: {e}")
                if not (0 <= float(e["time"]) <= float(end) + 1e-9):
                    problems.append(f"observed_events('{sc}') time {e['time']} outside [0, recorded_end={end}]")
        except Exception as ex:
            return {"passed": False, "error": f"malformed output on '{sc}': {type(ex).__name__}: {ex}"}
    if n_inter == 0:
        problems.append("observed_events found no interaction events (two or more participants) in any checked "
                        "scope; parse the records of interactions between entities")
    return {"passed": not problems, "error": "; ".join(problems[:6]) or None}


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


def generate_model(llm, nav: dict, map_path: Path, max_tries: int = 3, log=None,
                   parser_tries: int = 3, sim_tries: int = 5, n_explore: int = 8, restarts: int = 3,
                   library: list[dict] | None = None) -> dict:
    """Two checked steps: (1) parsers, (2) a forward simulator built on the checked parsers, written by a
    code-executing agent that can explore the data first. llm(messages) -> reply text.
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
    # show the checked parsers' real output on one scope that is NOT among the checked scopes
    ex = scopes(nav)[-1]
    ex_vals = [sandbox.run(parsers, fn, map_path, [ex])[1] for fn in ("entities", "recorded_end", "observed_events")]
    ex_fields = {"example_scope": ex, "example_entities": json.dumps(ex_vals[0])[:1500],
                 "example_end": ex_vals[1], "example_events": json.dumps(ex_vals[2])[:1500]}
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
    best = max(sims, key=lambda a: (a["report"]["error"] is None, a["report"]["mean_f1"]))
    return {"code": best["code"], "passed": best["report"]["passed"], "mean_f1": best["report"]["mean_f1"],
            "tries": len(attempts), "attempts": attempts, "failed_step": None if best["report"]["passed"] else "simulate"}
