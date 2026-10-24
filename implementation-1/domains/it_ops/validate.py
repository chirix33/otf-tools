"""Validate the IT operations benchmark and write domains/it_ops/VALIDATION.md.

    python -m domains.it_ops.validate          (from implementation-1/)

Checks, on every run folder runs/itops_*:
 1. determinism: sim.simulate run twice gives identical results and reproduces the task log, Events section and
    end-of-window queue printed in the PDF; one window's run takes well under 20 s of CPU;
 2. independent re-implementation: a second, separately written scheduler (below, `ref_engine`) fed only with
    the inputs parsed back from the PDF (Machines table, submit rows of the task log) reproduces every task log
    row and the queue at window end; run on from the printed end-of-window state alone it reproduces sim.py's
    continued run; and it re-derives every gold label (so the document alone holds everything a question needs);
 3. invariants on every printed log: capacity never exceeded on any machine at any time, no task on a down
    machine, each finish comes exactly one run time after its start, every task submitted in the window
    finishes in it or is listed in the queue at window end (and not both);
 4. printed inputs (submit time, priority, requests, run time, machine capacity, failure and return times)
    equal the raw trace records under the documented rules; trace files match the bucket's SHA256SUM;
 5. counts per type / template, true-false balance, no constant-answer template, simple baselines;
 6. prompt hygiene: scope title verbatim, only tasks/jobs/machines of that scope, no type or method words;
 7. 20 seeded random questions written out with the document excerpt and gold, for hand-checking.
"""
from __future__ import annotations

import json
import random
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import pypdfium2 as pdfium

from . import scopes as S
from .data import US, load_all, verify
from .questions import LONG_WAIT, first_start_in, n_evictions, running_at, stmt_truth
from .render import longest_waits, queue_rows
from .sim import events, simulate

RUNS = Path(__file__).resolve().parents[2] / "runs"
OUT = Path(__file__).resolve().parent / "VALIDATION.md"
FORBIDDEN = ("descriptive", "explanatory", "predictive", "counterfactual", "simulat", "gold", "but-for",
             "intervention", "benchmark")
TITLE = re.compile(r"Cell window (\d\d)")


# ------------------------------------------------------------------ parse the PDF back
def parse_pdf(path: Path) -> dict:
    pdf = pdfium.PdfDocument(str(path))
    lines = []
    for i in range(len(pdf)):
        lines += pdf[i].get_textpage().get_text_range().replace("\r", "").split("\n")
    scopes, cur, sec = {}, None, None
    for ln in lines:
        ln = ln.strip()
        if TITLE.fullmatch(ln):
            cur = scopes.setdefault(ln, {"machines": [], "log": [], "events": [], "waits": "", "running": [],
                                         "pending": [], "down": {}, "W": None})
            sec = "head"
            continue
        m = re.fullmatch(r"(Cell window \d\d): (Machines|Task log|Events|Queue at window end)", ln)
        if m:
            cur, sec = scopes[m[1]], m[2]
            continue
        if cur is None or not ln:
            continue
        tok = ln.split()
        if sec == "head":
            m = re.match(r"Times 0 to (\d+)\.", ln)
            if m:
                cur["W"] = int(m[1])
        elif sec == "Machines" and len(tok) == 5 and re.fullmatch(r"M\d\d", tok[0]):
            cur["machines"].append({"id": tok[0], "cpu": int(tok[1]), "mem": int(tok[2]),
                                    "down": None if tok[3] == "-" else int(tok[3]),
                                    "back": None if tok[4] in ("-", "never") else int(tok[4])})
        elif sec == "Task log" and len(tok) == 9 and tok[0].isdigit():
            cur["log"].append((int(tok[0]), tok[1], tok[2], int(tok[3]), int(tok[4]), int(tok[5]), int(tok[6]),
                               tok[7], tok[8]))
        elif sec == "Events":
            if ln.startswith("Time ") or ln.startswith("Longest waits") or ln.startswith("Every task") \
                    or ln.startswith("No machine"):
                cur["events"].append(ln)
            elif cur["events"]:
                cur["events"][-1] += " " + ln
        elif sec == "Queue at window end":
            if len(tok) == 8 and re.fullmatch(r"T\d{3}", tok[0]):
                cur["running"].append({"task": tok[0], "job": tok[1], "pri": int(tok[2]), "cpu": int(tok[3]),
                                       "mem": int(tok[4]), "machine": tok[5], "started": int(tok[6]),
                                       "remaining": int(tok[7])})
            elif len(tok) == 7 and re.fullmatch(r"T\d{3}", tok[0]):
                cur["pending"].append({"task": tok[0], "job": tok[1], "pri": int(tok[2]), "cpu": int(tok[3]),
                                       "mem": int(tok[4]), "submit": int(tok[5]), "run": int(tok[6])})
            m = re.match(r"Machine (M\d\d) is down at time \d+; it (does not return|returns at time (\d+))", ln)
            if m:
                cur["down"][m[1]] = None if m[3] is None else int(m[3])
    for sc in scopes.values():
        sc["tasks"] = {r[1]: {"job": r[2], "pri": r[3], "cpu": r[4], "mem": r[5], "submit": r[0], "run": r[6]}
                       for r in sc["log"] if r[7] == "submit"}
        for t in sc["log"]:          # every row repeats the task's attributes: they must agree with its submit row
            a = sc["tasks"].get(t[1])
            if a is None or (a["job"], a["pri"], a["cpu"], a["mem"], a["run"]) != t[2:7]:
                sc.setdefault("problems", []).append(f"row {t} disagrees with the task's submit row")
    return scopes


# ------------------------------------------------------------------ independent scheduler
class RRun:
    def __init__(self, submit):
        self.submit = submit
        self.starts: list[tuple[int, str]] = []
        self.stops: list[tuple[int, str, str, str | None]] = []
        self.finish = None

    @property
    def first_start(self):
        return self.starts[0][0] if self.starts else None

    @property
    def first_machine(self):
        return self.starts[0][1] if self.starts else None

    @property
    def evictions(self):
        return [(t, m, by) for t, m, k, by in self.stops if k == "evict"]


class RefView:
    """Holds a ref_engine result with the attribute names the statement predicates in questions.py read."""
    def __init__(self, log, runs, machines, end_state):
        self.log, self.runs, self.end_state = log, runs, end_state
        self.machines = [type("M", (), {"mid": m["id"]}) for m in machines]

    def wait(self, tid):
        r = self.runs[tid]
        return None if r.first_start is None else r.first_start - r.submit


def apply_ivs(machines: list[dict], tasks: dict, ivs) -> tuple[list[dict], dict]:
    machines = [dict(m) for m in machines]
    tasks = {k: dict(v) for k, v in tasks.items()}
    for iv in ivs:
        k = iv["kind"]
        if k == "remove_job":
            tasks = {t: a for t, a in tasks.items() if a["job"] != iv["job"]}
        elif k == "remove_task":
            tasks.pop(iv["task"], None)
        elif k == "set_priority":
            tasks[iv["task"]]["pri"] = iv["value"]
        elif k == "set_request":
            tasks[iv["task"]][iv["resource"]] = iv["value"]
        elif k == "remove_failure":
            for m in machines:
                if m["id"] == iv["machine"]:
                    m["down"] = m["back"] = None
        elif k == "remove_machine":
            machines = [m for m in machines if m["id"] != iv["machine"]]
    return machines, tasks


def ref_engine(machines: list[dict], tasks: dict, after: int, running: list[list], queue: list[str],
               until: int | None, W: int) -> RefView:
    """The policy as written in the front matter. `machines` in id order; `tasks` tid -> attributes; the run
    processes every event at times > `after`, starting from `running` ([tid, machine, started, ends]) and the
    waiting `queue`. Written separately from sim.py: state is a flat list of running records, free capacity is
    recomputed from it, and the reservation time is found by scanning candidate times."""
    up = {m["id"]: not (m["down"] is not None and m["down"] <= after and (m["back"] is None or m["back"] > after))
          for m in machines}
    cap = {m["id"]: (m["cpu"], m["mem"]) for m in machines}
    ids = [m["id"] for m in machines]
    running = [list(r) for r in running]
    queue = list(queue)
    runs = {t: RRun(a["submit"]) for t, a in tasks.items()}
    log = []
    snap = None

    def key(t):
        return (-tasks[t]["pri"], tasks[t]["submit"], t)

    def used(mid, at=None):
        rs = [r for r in running if r[1] == mid and (at is None or r[3] > at)]
        return sum(tasks[r[0]]["cpu"] for r in rs), sum(tasks[r[0]]["mem"] for r in rs)

    def room(mid, at=None):
        c, m = used(mid, at)
        return cap[mid][0] - c, cap[mid][1] - m

    def start(t, mid, now):
        running.append([t, mid, now, now + tasks[t]["run"]])
        runs[t].starts.append((now, mid))
        log.append((now, t, "start", mid))

    def remove(t, now, kind, by=None):
        r = next(r for r in running if r[0] == t)
        running.remove(r)
        runs[t].stops.append((now, r[1], kind, by))
        log.append((now, t, kind, r[1]))

    def scheduling_round(now):
        order = sorted(queue, key=key)
        resv = None                              # [machine, time, spare cpu, spare mem]
        i = 0
        while i < len(order):
            t = order[i]
            a = tasks[t]
            target = None
            for mid in ids:
                fc, fm = room(mid)
                if not up[mid] or fc < a["cpu"] or fm < a["mem"]:
                    continue
                if resv and mid == resv[0]:
                    if now + a["run"] <= resv[1]:
                        pass
                    elif a["cpu"] <= resv[2] and a["mem"] <= resv[3]:
                        resv[2] -= a["cpu"]
                        resv[3] -= a["mem"]
                    else:
                        continue
                target = mid
                break
            if target is None and resv is None and a["pri"] >= 9:
                for mid in ids:
                    if not up[mid] or cap[mid][0] < a["cpu"] or cap[mid][1] < a["mem"]:
                        continue
                    free_tier = sorted((r for r in running if r[1] == mid and tasks[r[0]]["pri"] <= 1),
                                       key=lambda r: (tasks[r[0]]["pri"], -r[2], [-ord(ch) for ch in r[0]]))
                    fc, fm = room(mid)
                    k = 0
                    while (fc < a["cpu"] or fm < a["mem"]) and k < len(free_tier):
                        fc += tasks[free_tier[k][0]]["cpu"]
                        fm += tasks[free_tier[k][0]]["mem"]
                        k += 1
                    if k and fc >= a["cpu"] and fm >= a["mem"]:
                        victims = [r[0] for r in free_tier[:k]]
                        for v in victims:
                            remove(v, now, "evict", t)
                            queue.append(v)
                        order = order[:i + 1] + sorted(order[i + 1:] + victims, key=key)
                        target = mid
                        break
            if target is not None:
                queue.remove(t)
                order.pop(i)
                start(t, target, now)
                continue
            if resv is None:
                best = None
                for mid in ids:
                    if not up[mid] or cap[mid][0] < a["cpu"] or cap[mid][1] < a["mem"]:
                        continue
                    for when in sorted({now} | {r[3] for r in running if r[1] == mid}):
                        fc, fm = room(mid, when)
                        if fc >= a["cpu"] and fm >= a["mem"]:
                            if best is None or when < best[1]:
                                best = [mid, when, fc - a["cpu"], fm - a["mem"]]
                            break
                resv = best
            i += 1

    subs = sorted((a["submit"], t) for t, a in tasks.items() if a["submit"] > after)
    downs = {m["id"]: m["down"] for m in machines if m["down"] is not None and m["down"] > after}
    backs = {m["id"]: m["back"] for m in machines if m["down"] is not None and m["back"] is not None
             and m["back"] > after}
    clock = after
    while True:
        cands = [x for x in [s for s, _ in subs] + [r[3] for r in running] + list(downs.values())
                 + list(backs.values()) if x > clock]
        if not cands:
            break
        now = min(cands)
        if until is not None and now > until:
            break
        if snap is None and now > W >= clock:
            snap = state(running, queue, up, W)
        clock = now
        for r in sorted((r for r in running if r[3] == now), key=lambda r: r[0]):
            running.remove(r)
            runs[r[0]].finish = now
            log.append((now, r[0], "finish", r[1]))
        for mid in ids:
            if downs.get(mid) == now:
                for r in sorted((r for r in running if r[1] == mid), key=lambda r: r[0]):
                    remove(r[0], now, "fail")
                    queue.append(r[0])
                up[mid] = False
        for mid in ids:
            if backs.get(mid) == now:
                up[mid] = True
        for s_, t in [x for x in subs if x[0] == now]:
            log.append((now, t, "submit", None))
            queue.append(t)
        scheduling_round(now)
    if snap is None and (until is None or until >= W):
        snap = state(running, queue, up, W)
    return RefView(log, runs, machines, snap)


def state(running, queue, up, W) -> dict:
    return {"running": {r[0]: {"machine": r[1], "started": r[2], "remaining": r[3] - W} for r in running},
            "pending": list(queue), "down": sorted(m for m, u in up.items() if not u)}


def window_run(ps: dict, ivs=(), until=None) -> RefView:
    machines, tasks = apply_ivs(ps["machines"], ps["tasks"], ivs)
    return ref_engine(machines, tasks, -1, [], [], until, ps["W"])


def continued_run(ps: dict) -> RefView:
    """Run on from the printed 'Queue at window end' state (submit time and run time of the running tasks,
    which the queue table does not repeat, come from their task log rows)."""
    W = ps["W"]
    tasks = {r["task"]: {"job": r["job"], "pri": r["pri"], "cpu": r["cpu"], "mem": r["mem"],
                         "submit": ps["tasks"][r["task"]]["submit"], "run": ps["tasks"][r["task"]]["run"]}
             for r in ps["running"]}
    tasks.update({r["task"]: {"job": r["job"], "pri": r["pri"], "cpu": r["cpu"], "mem": r["mem"],
                              "submit": r["submit"], "run": r["run"]} for r in ps["pending"]})
    running = [[r["task"], r["machine"], r["started"], W + r["remaining"]] for r in ps["running"]]
    machines = [dict(m) for m in ps["machines"]]
    return ref_engine(machines, tasks, W, running, [r["task"] for r in ps["pending"]], None, W)


# ------------------------------------------------------------------ gold re-derivation from the PDF alone
def rederive(item: dict, meta: dict, ps: dict, f: RefView, cont: RefView):
    W = ps["W"]
    t, q = item["question_subtype"], item["question"]
    if item["question_type"] == "descriptive":
        if t == "first_machine":
            return f.runs[re.search(r"did task (T\d+) first start", q)[1]].first_machine.lower()
        if t == "n_evictions":
            return str(n_evictions(f, W))
        if t == "wait":
            return str(f.wait(re.search(r"submission of task (T\d+)", q)[1]))
        if t == "finish_time":
            return str(f.runs[re.search(r"did task (T\d+) finish", q)[1]].finish)
        if t == "n_starts":
            tid = re.search(r"did task (T\d+) start", q)[1]
            return str(sum(1 for x, _ in f.runs[tid].starts if x <= W))
        if t == "running_on":
            m, tt = re.search(r"machine (M\d\d) at time (\d+)", q).groups()
            return str(sum(1 for x in running_at(f, int(tt)).values() if x == m))
    if item["question_type"] == "explanatory":
        tg = meta["target"]
        out = []
        for iv in meta["interventions"]:
            if tg["kind"] == "evicted_at":
                r = window_run(ps, [iv], until=tg["time"])
                out.append(not any(x == tg["time"] for x, _, _ in r.runs[tg["task"]].evictions))
            else:
                r = window_run(ps, [iv], until=tg["submit"] + LONG_WAIT)
                fs = r.runs[tg["task"]].first_start
                out.append(fs is not None and fs - tg["submit"] <= LONG_WAIT)
        return out
    if item["question_type"] == "predictive":
        def nxt(tid):
            return next((x, m) for x, m in cont.runs[tid].starts if x > W)
        if t == "next_start":
            tids = [c["choice"].split()[-1] for c in item["choices"]]
            e = min(nxt(x)[0] for x in tids)
            return [nxt(x)[0] == e for x in tids]
        if t == "start_machine":
            m = nxt(re.search(r"will task (T\d+) start", q)[1])[1]
            return [c["choice"].split()[-1] == m for c in item["choices"]]
        return [stmt_truth(k, a, cont, W) for k, a in zip(meta["kinds"], meta["args"])]
    if item["question_type"] == "counterfactual":
        r = window_run(ps, [meta["intervention"]], until=W)
        return [stmt_truth(k, a, r, W) for k, a in zip(meta["kinds"], meta["args"])]
    raise ValueError(t)


# ------------------------------------------------------------------ excerpt for hand-checking
def excerpt(item: dict, meta: dict, ps: dict, f: RefView, cont: RefView) -> list[str]:
    W = ps["W"]
    text = item["question"] + " " + " ".join(c["choice"] for c in item["choices"])
    tids = sorted(set(re.findall(r"\bT\d{3}\b", text)))
    mids = sorted(set(re.findall(r"\bM\d\d\b", text)))
    jobs = sorted(set(re.findall(r"\bJ\d\d\b", text)))
    out = ["machines (id cpu mem fails_at returns_at): " + "; ".join(
        f"{m['id']} {m['cpu']} {m['mem']} {m['down'] if m['down'] is not None else '-'} "
        f"{'-' if m['down'] is None else (m['back'] if m['back'] is not None else 'never')}" for m in ps["machines"])]
    st = item["question_subtype"]
    if st == "running_on":
        m, tt = re.search(r"machine (M\d\d) at time (\d+)", item["question"]).groups()
        on = sorted(x for x, y in running_at(f, int(tt)).items() if y == m)
        out.append(f"running on {m} after the events at time {tt}: {', '.join(on) or 'none'}")
        rows = [r for r in ps["log"] if r[8] == m and r[0] <= int(tt) and r[1] in on]
    elif st == "n_evictions":
        rows = [r for r in ps["log"] if r[7] == "evict"]
    else:
        rows = [r for r in ps["log"] if r[1] in tids or r[2] in jobs]
    if rows:
        out.append("task log rows (time task job priority cpu mem run_time event machine):")
        out += [" ".join(map(str, r)) for r in rows[:40]]
        if len(rows) > 40:
            out.append(f"... ({len(rows) - 40} more rows)")
    ev = [e for e in ps["events"] if e.startswith("Time ") and (st == "n_evictions" or
                                                               any(re.search(rf"\b{x}\b", e) for x in tids + mids))]
    if ev:
        out += ["events:"] + [f"  {e}" for e in ev[:12]]
    if item["question_type"] == "predictive":
        out.append(f"queue at time {W}, running: " + (", ".join(
            f"{r['task']}(p{r['pri']} {r['cpu']}/{r['mem']} on {r['machine']} rem {r['remaining']})"
            for r in ps["running"]) or "none"))
        out.append("waiting (queue order): " + (", ".join(
            f"{r['task']}(p{r['pri']} {r['cpu']}/{r['mem']} run {r['run']})" for r in ps["pending"]) or "none"))
        out.append(f"down at {W}: " + (", ".join(f"{m} (returns {b if b is not None else 'never'})"
                                                for m, b in ps["down"].items()) or "none"))
        for tid in tids:
            r = cont.runs.get(tid)
            if r:
                out.append(f"continued run, {tid}: starts {[(x, m) for x, m in r.starts if x > W]}, "
                           f"finish {r.finish}, evicted at {[x for x, _, _ in r.evictions]}")
    if item["question_type"] == "counterfactual":
        iv = meta["intervention"]
        r = window_run(ps, [iv], until=W)
        out.append(f"change: {json.dumps(iv)}")
        for k, a in zip(meta["kinds"], meta["args"]):
            out.append(f"  {k} {json.dumps(a)}: recorded={stmt_truth(k, a, f, W)} with change={stmt_truth(k, a, r, W)}")
    if item["question_type"] == "explanatory":
        out.append("but-for runs (outcome removed?):")
        out += [f"  {json.dumps(iv)} -> {g}" for iv, g in zip(meta["interventions"], rederive(item, meta, ps, f, cont))]
    return out


# ------------------------------------------------------------------ checks
def fmt_log(res, W):
    return [(t, tid, res.tasks[tid].job, res.tasks[tid].priority, res.tasks[tid].cpu, res.tasks[tid].mem,
             res.tasks[tid].duration, ev, mid or "-") for t, tid, ev, mid in res.log if t <= W]


def invariants(title: str, ps: dict) -> list[str]:
    """Checks on the printed log alone: capacity, down machines, run times, finished-or-queued."""
    P = []
    M = {m["id"]: m for m in ps["machines"]}
    on: dict[str, dict] = {m: {} for m in M}
    started: dict[str, int] = {}
    finished = set()
    for t, tid, job, pri, cpu, mem, run, ev, mid in ps["log"]:
        if ev == "start":
            m = M[mid]
            if m["down"] is not None and m["down"] <= t and (m["back"] is None or t < m["back"]):
                P.append(f"{title}: {tid} starts on {mid} at {t} while it is down")
            if tid in started or tid in finished:
                P.append(f"{title}: {tid} starts at {t} while running or after finishing")
            on[mid][tid] = (cpu, mem)
            started[tid] = t
            if sum(c for c, _ in on[mid].values()) > m["cpu"] or sum(x for _, x in on[mid].values()) > m["mem"]:
                P.append(f"{title}: capacity of {mid} exceeded at time {t}")
        elif ev in ("finish", "evict", "fail"):
            if tid not in on.get(mid, {}):
                P.append(f"{title}: {ev} of {tid} on {mid} at {t} but it is not running there")
                continue
            del on[mid][tid]
            if ev == "finish":
                if t - started[tid] != run:
                    P.append(f"{title}: {tid} finishes {t - started[tid]} s after its start, run time {run}")
                finished.add(tid)
            if ev == "fail" and M[mid]["down"] != t:
                P.append(f"{title}: {tid} fails at {t} but {mid} does not fail then")
            if ev == "evict" and pri > 1:
                P.append(f"{title}: {tid} (priority {pri}) evicted but is not free tier")
            del started[tid]
    for mid, m in M.items():                     # every task on a failing machine stops at the failure
        if m["down"] is None:
            continue
        live: set = set()
        for t, tid, *_rest, ev, mm in ps["log"]:
            if t >= m["down"] and ev != "finish":
                break
            if mm == mid:
                if ev == "start":
                    live.add(tid)
                elif ev in ("finish", "evict"):
                    live.discard(tid)
        stopped = {r[1] for r in ps["log"] if r[0] == m["down"] and r[7] == "fail" and r[8] == mid}
        if live != stopped:
            P.append(f"{title}: tasks on {mid} at its failure {sorted(live)} vs stopped {sorted(stopped)}")
    queued = {r["task"] for r in ps["running"]} | {r["task"] for r in ps["pending"]}
    for tid in ps["tasks"]:
        if (tid in finished) == (tid in queued):
            P.append(f"{title}: {tid} is " + ("both finished and in the end queue" if tid in finished
                                             else "neither finished nor in the end queue"))
    if {r["task"] for r in ps["running"]} != set(started):
        P.append(f"{title}: running table differs from the tasks still running in the log")
    for r in ps["running"]:
        if r["task"] in started and r["task"] not in on.get(r["machine"], {}):
            P.append(f"{title}: {r['task']} listed on {r['machine']} but runs elsewhere in the log")
        if r["task"] in started and r["started"] != started[r["task"]]:
            P.append(f"{title}: {r['task']} start time in the queue table differs from the log")
    for r in ps["pending"]:
        a = ps["tasks"].get(r["task"])
        if a is None or (a["job"], a["pri"], a["cpu"], a["mem"], a["submit"], a["run"]) != \
                (r["job"], r["pri"], r["cpu"], r["mem"], r["submit"], r["run"]):
            P.append(f"{title}: waiting row {r['task']} disagrees with its task log rows")
    return P


def raw_check(w, slices_by_parts, hist) -> list[str]:
    """The window's inputs equal the raw trace records under the documented rules."""
    P = []
    sl = slices_by_parts[tuple(w.meta["parts"])]
    w0 = w.meta["start_us"]
    by_key = {(t.job, t.index): t for ts in sl.tasks.values() for t in ts}
    for t in w.tasks:
        j, idx = w.meta["real_tasks"][t.tid]
        r = by_key.get((j, idx))
        if r is None or (r.priority, r.cpu, r.mem, r.duration, (r.submit_us - w0) // US) != \
                (t.priority, t.cpu, t.mem, t.duration, t.submit):
            P.append(f"{w.title} {t.tid}: differs from trace task {j}/{idx}")
        if w.meta["real_jobs"][t.job] != j:
            P.append(f"{w.title} {t.tid}: job id mapping inconsistent")
        if not w0 <= sl.job_submit_us[j] < w0 + w.length * US:
            P.append(f"{w.title} {t.tid}: job not submitted in the window")
    rmid, r_us, back_us = w.meta["removal"]
    for m, real in zip(w.machines, w.meta["real_machines"]):
        c, mm = hist[real].capacity_at(w0)
        if (m.cpu, m.mem) != (S._cap(c), S._cap(mm)):
            P.append(f"{w.title} {m.mid}: capacity differs from 1/{S.CAPACITY_DIVISOR} of real machine {real}")
        if real == rmid:
            b = (back_us - w0) // US if back_us is not None else None
            want = (r_us - w0) // US, (b if b is not None and b <= S.RETURN_HORIZON else None)
            if (m.down, m.back) != want:
                P.append(f"{w.title} {m.mid}: failure/return differ from the trace")
        elif m.down is not None or hist[real].outages(w0, w0 + w.length * US):
            P.append(f"{w.title} {m.mid}: unexpected failure")
    return P


def raw_counts(slices) -> list[str]:
    """Independent re-read of the raw task_events files: every eligible task's record, counted per slice."""
    import csv
    import gzip
    from .data import FINISH, SCHEDULE, SUBMIT, TERMINAL, part_file, units
    out = []
    for sl in slices:
        ev: dict = defaultdict(list)
        for p in sl.parts:
            with gzip.open(part_file("task_events", p), "rt") as fh:
                for r in csv.reader(fh):
                    ev[(int(r[2]), int(r[3]))].append((int(r[0]), int(r[5]), r[8], r[9], r[10]))
        n = 0
        for (job, idx), es in ev.items():
            if job not in sl.job_submit_us:
                continue
            es.sort(key=lambda e: e[0])
            if es[0][1] != SUBMIT:
                continue
            k = next((i for i, e in enumerate(es) if e[1] == SCHEDULE), None)
            if k is None:
                continue
            end = next((e for e in es[k + 1:] if e[1] in TERMINAL), None)
            if end and end[1] == FINISH and es[k][2] and units(es[k][3]) > 0 and units(es[k][4]) > 0:
                n += 1
        mine = sum(len(v) for v in sl.tasks.values())
        out.append((sl.parts, n, mine))
    return out


# ------------------------------------------------------------------ sensitivity: does every rule matter?
MUTATIONS = {
    "no backfilling of tasks that finish before the reserved time": ('if now + a["run"] <= resv[1]:', 'if False:'),
    "no backfilling into the reserved machine's spare room": ('elif a["cpu"] <= resv[2] and a["mem"] <= resv[3]:',
                                                            'elif False:'),
    "evict the oldest free-tier task first (instead of the most recent)": (
        'key=lambda r: (tasks[r[0]]["pri"], -r[2],', 'key=lambda r: (tasks[r[0]]["pri"], r[2],'),
    "no reservation at all (pure first fit)": ("                resv = best\n", "                resv = None\n"),
    "machines never return": ("                up[mid] = True\n", "                pass\n"),
    "no preemption": ('if target is None and resv is None and a["pri"] >= 9:', 'if False:'),
}


def sensitivity(parsed: dict) -> list[tuple[str, int]]:
    """Break one rule at a time in ref_engine (by editing its source) and count windows whose log changes."""
    import inspect
    import types
    src = inspect.getsource(ref_engine)
    out = []
    for name, (a, b) in MUTATIONS.items():
        mod = types.ModuleType("mutant")
        mod.__dict__.update({k: v for k, v in globals().items() if k != "ref_engine"})
        exec(src.replace(a, b, 1), mod.__dict__)
        diff = 0
        for ps in parsed.values():
            machines, tasks = apply_ivs(ps["machines"], ps["tasks"], [])
            r = mod.ref_engine(machines, tasks, -1, [], [], ps["W"], ps["W"])
            if [(t, x, e, m or "-") for t, x, e, m in r.log] != [(x[0], x[1], x[7], x[8]) for x in ps["log"]]:
                diff += 1
        out.append((name, diff))
    return out


# ------------------------------------------------------------------ main
def main() -> None:
    problems: list[str] = list(verify())
    slices, hist = load_all()
    t0 = time.process_time()
    cands = S.candidates(slices, hist)
    cpu_build = time.process_time() - t0
    windows = {c.window.title: c.window for c in cands if c.kept}
    slices_by_parts = {tuple(s.parts): s for s in slices}
    rc = raw_counts(slices)
    for parts, n, mine in rc:
        if n != mine:
            problems.append(f"slice {parts}: raw re-read finds {n} eligible tasks, data.py {mine}")
    run_dirs = sorted(p for p in RUNS.glob("itops_*") if (p / "items.jsonl").exists())
    report = ["# IT operations benchmark: validation report", "",
              "Generated by `python -m domains.it_ops.validate`. Every number below is recomputed from the files "
              "in `runs/itops_*` and the raw trace; nothing is hand-entered. Design decisions and deviations from "
              "the draft spec: `docs/domains/it_operations.md`, section \"As built\".", ""]
    totals = Counter()
    all_items = []
    doc_rows, win_rows = [], []
    cpu_sim, cpu_ref = [], []
    for rd in run_dirs:
        parsed = parse_pdf(rd / "document.pdf")
        cfg = json.loads((rd / "build_config.json").read_text())
        man = json.loads((rd / "manifest.json").read_text())
        items = [json.loads(l) for l in (rd / "items.jsonl").read_text().splitlines()]
        metas = {m["uid"]: m for m in map(json.loads, (rd / "gold_meta.jsonl").read_text().splitlines())}
        qs = {q["uid"]: q for q in map(json.loads, (rd / "questions.jsonl").read_text().splitlines())}
        golds = {g["uid"]: g for g in map(json.loads, (rd / "gold.jsonl").read_text().splitlines())}
        if [s["title"] for s in man["scopes"]] != cfg["scopes"] or set(parsed) != set(cfg["scopes"]):
            problems.append(f"{rd.name}: scope list differs between manifest, config and PDF")
        refs = {}
        n_rows = 0
        for title in cfg["scopes"]:
            w, ps = windows[title], parsed[title]
            W = w.length
            problems += ps.get("problems", [])
            if ps["W"] != W:
                problems.append(f"{title}: printed window length differs")
            t0 = time.process_time()
            a = simulate(w)
            cpu_sim.append(time.process_time() - t0)
            b = simulate(w)
            if a.log != b.log or a.end_state != b.end_state or \
                    any(vars(a.runs[k]) != vars(b.runs[k]) for k in a.runs):
                problems.append(f"{title}: simulate is not deterministic")
            # 1. sim.py reproduces what is printed
            n_rows += len(ps["log"])
            if fmt_log(a, W) != ps["log"]:
                problems.append(f"{title}: printed task log differs from sim.py")
            ev = [f"Time {t}: {txt}." for t, _, txt in events(a)]
            lw = longest_waits(a)
            ev += (["Longest waits (submission to first start, tasks started by the window end): " +
                    "; ".join(f"task {x} waited {d} s (submitted at {s_}, first started at {f_})"
                              for x, d, s_, f_ in lw) + "."] if lw else ["Every task started at its submission time."])
            if [e.replace(" ", "") for e in ev] != [e.replace(" ", "") for e in ps["events"]]:
                problems.append(f"{title}: printed Events section differs from sim.py")
            running, pending = queue_rows(a)
            if [list(map(str, (r["task"], r["job"], r["pri"], r["cpu"], r["mem"], r["machine"], r["started"],
                               r["remaining"]))) for r in ps["running"]] != running or \
                    [list(map(str, (r["task"], r["job"], r["pri"], r["cpu"], r["mem"], r["submit"], r["run"])))
                     for r in ps["pending"]] != pending:
                problems.append(f"{title}: printed queue at window end differs from sim.py")
            if {m: w.machine(m).back for m in a.end_state["down"]} != ps["down"]:
                problems.append(f"{title}: printed down machines differ")
            # 2. independent scheduler on the PDF's inputs
            t0 = time.process_time()
            r = window_run(ps)
            cpu_ref.append(time.process_time() - t0)
            rlog = [(t, x, ps["tasks"][x]["job"], ps["tasks"][x]["pri"], ps["tasks"][x]["cpu"],
                     ps["tasks"][x]["mem"], ps["tasks"][x]["run"], e_, mid or "-") for t, x, e_, mid in r.log if t <= W]
            if rlog != ps["log"]:
                bad = next((i for i, (u, v) in enumerate(zip(rlog, ps["log"])) if u != v), min(len(rlog), len(ps["log"])))
                problems.append(f"{title}: independent scheduler differs from the printed log at row {bad}: "
                                f"{rlog[bad] if bad < len(rlog) else None} vs "
                                f"{ps['log'][bad] if bad < len(ps['log']) else None}")
            want_run = {x["task"]: {"machine": x["machine"], "started": x["started"], "remaining": x["remaining"]}
                        for x in ps["running"]}
            if r.end_state["running"] != want_run or \
                    sorted(r.end_state["pending"]) != sorted(x["task"] for x in ps["pending"]) or \
                    r.end_state["down"] != sorted(ps["down"]):
                problems.append(f"{title}: independent scheduler's end state differs from the printed queue")
            cont = continued_run(ps)
            after_sim = [(t, x, e_, m_) for t, x, e_, m_ in a.log if t > W]
            if cont.log != after_sim:
                problems.append(f"{title}: run continued from the printed end state differs from sim.py after {W}")
            if [(t, x, e_, m_) for t, x, e_, m_ in r.log if t > W] != after_sim:
                problems.append(f"{title}: independent full run differs from sim.py after {W}")
            refs[title] = (r, cont)
            # 3. invariants on the printed log
            problems += invariants(title, ps)
            # 4. printed inputs == window inputs == raw trace
            if ps["tasks"] != {t.tid: {"job": t.job, "pri": t.priority, "cpu": t.cpu, "mem": t.mem,
                                       "submit": t.submit, "run": t.duration} for t in w.tasks}:
                problems.append(f"{title}: printed task inputs differ from the window's inputs")
            if ps["machines"] != [{"id": m.mid, "cpu": m.cpu, "mem": m.mem, "down": m.down, "back": m.back}
                                  for m in w.machines]:
                problems.append(f"{title}: printed machines differ from the window's machines")
            problems += raw_check(w, slices_by_parts, hist)
            nl = sum(1 for x in a.runs if first_start_in(a, x, W) is not None and a.wait(x) > LONG_WAIT)
            win_rows.append((w.number, f"| {title} | {rd.name} | {w.meta['parts'][0]}-{w.meta['parts'][1]} | "
                            f"{w.meta['offset_s']} | {len(w.tasks)} | {len({t.job for t in w.tasks})} | "
                            f"{sum(t.priority >= 9 for t in w.tasks)} / {sum(t.priority <= 1 for t in w.tasks)} | "
                            f"{max(w.meta['offered_load']):.2f} | {n_evictions(a, W)} | "
                            f"{sum(1 for x in a.log if x[2] == 'fail' and x[0] <= W)} | {nl} | "
                            f"{len(a.end_state['running'])} / {len(a.end_state['pending'])} | {len(ps['log'])} |"))
        n_gold_ok = 0
        for it in items:
            title = it["scene_index"]
            ps = parsed[title]
            r, cont = refs[title]
            meta = metas[it["uid"]]
            got = rederive(it, meta, ps, r, cont)
            want = it["gold_answer"] if it["question_type"] == "descriptive" else \
                [it["gold_choices"][str(i)] for i in range(len(it["choices"]))]
            if got != want:
                problems.append(f"{it['uid']}: gold {want} but re-derived {got}")
            else:
                n_gold_ok += 1
            q, g = qs[it["uid"]], golds[it["uid"]]
            if title not in it["question"] or not q["prompt"].startswith(title + "\n"):
                problems.append(f"{it['uid']}: scope title missing from prompt")
            if any(wd in q["prompt"].lower() for wd in FORBIDDEN) or "question_type" in q or "gold" in str(q):
                problems.append(f"{it['uid']}: prompt leaks type/method words")
            for tid in re.findall(r"\bT\d{3}\b", q["prompt"]):
                if tid not in ps["tasks"]:
                    problems.append(f"{it['uid']}: mentions {tid}, not a task of its scope")
            for mid in re.findall(r"\bM\d\d\b", q["prompt"]):
                if mid not in {m["id"] for m in ps["machines"]}:
                    problems.append(f"{it['uid']}: mentions {mid}, not a machine of its scope")
            for j in re.findall(r"\bJ\d\d\b", q["prompt"]):
                if j not in {a["job"] for a in ps["tasks"].values()}:
                    problems.append(f"{it['uid']}: mentions {j}, not a job of its scope")
            if it["question_type"] != "predictive":
                for x in map(int, re.findall(r"time (\d+)", q["prompt"])):
                    if x > ps["W"]:
                        problems.append(f"{it['uid']}: mentions time {x} after the window")
            if it["question_type"] != "descriptive" and (all(it["gold_choices"].values()) or
                                                          not any(it["gold_choices"].values())):
                problems.append(f"{it['uid']}: all choices have the same truth")
            if (g["gold_answer"], g["question_type"], g["gold_choices"]) != \
                    (it["gold_answer"], it["question_type"], it["gold_choices"]):
                problems.append(f"{it['uid']}: gold.jsonl differs from items.jsonl")
            all_items.append((rd.name, it, meta, ps, r, cont))
        cnt = Counter(it["question_type"] for it in items)
        totals.update(cnt)
        pages = man["scopes"][-1]["end_page"]
        doc_rows.append(f"| {rd.name} | {cfg.get('role', 'test')} | {len(cfg['scopes'])} | {pages} | {n_rows} | "
                        f"{cnt['descriptive']} | {cnt['explanatory']} | {cnt['predictive']} | "
                        f"{cnt['counterfactual']} | {len(items)} | {n_gold_ok}/{len(items)} |")

    test = [x for x in all_items if x[0] != "itops_dev"]
    test_parsed = {x[1]["scene_index"]: x[3] for x in test}
    sens = sensitivity(test_parsed)
    for name, n in sens:
        if n == 0:
            problems.append(f"rule never matters in the test windows: {name}")
    report += ["## Result", ""]
    result_at = len(report)
    report += [""]
    report += ["Checks run on every run folder (all windows, all task log rows, all questions):", "",
               "1. **Determinism.** `sim.simulate` run twice on each window gives identical logs, task histories "
               "and end states, and reproduces exactly the task log, the Events section and the queue at window "
               "end printed in the PDF (text extracted from the PDF with pypdfium2). A re-run reproduces the task "
               "log exactly.",
               "2. **Independent re-implementation.** `ref_engine` in `validate.py` is a second scheduler written "
               "from the front-matter prose (different state layout: a flat list of running tasks, free capacity "
               "recomputed from it, the reservation time found by scanning candidate times), fed only with numbers "
               "parsed back out of the PDF (the Machines table and the submit rows of the task log). It reproduces "
               "every printed task log row and the printed queue at window end; run on from the printed queue at "
               "window end it gives the same events after the window as `sim.py`; and it re-derives every gold "
               "label (descriptive answers, but-for runs for explanatory, continued runs for predictive, re-runs "
               "with the change for counterfactual). So each question is answerable from its document alone.",
               "3. **Invariants** on every printed log: the CPU and memory in use on a machine never exceed its "
               "capacity; no task starts on a machine while it is down, and every task running on a machine when "
               "it fails stops then; only free-tier tasks are evicted; every finish comes exactly one run time "
               "after the task's last start; every task submitted in the window either finishes in it or is "
               "listed in the queue at window end, never both; the queue tables agree with the log.",
               "4. **Real inputs.** Every task's printed submit time, priority, CPU and memory request and run time "
               "equal its raw trace record (job id and task index are kept in the build provenance), and its job "
               f"was submitted in the window; every machine's capacity is 1/{S.CAPACITY_DIVISOR} of its real "
               "machine's recorded capacity; the failure and return times are the real machine's REMOVE and next "
               "ADD times; no other machine has a REMOVE in the window. The trace files match the bucket's "
               "SHA256SUM, and a second read of the raw task_events files finds the same number of eligible tasks "
               "as `data.py` in every slice (" + "; ".join(f"parts {p[0]}-{p[1]}: {n}" for p, n, _ in rc) + ").",
               "5. **Prompt hygiene.** Every prompt starts with its scope title and the question repeats it; every "
               "task, job and machine id mentioned belongs to that scope; times mentioned in non-predictive "
               "questions lie in the window; no prompt contains the words " +
               ", ".join(f"'{wd}'" for wd in FORBIDDEN) + "; questions.jsonl carries no type or gold; every MC "
               "question has at least one true and one false choice.", "",
               f"**CPU time.** One window's full run (the window plus the continued run to the last finish) takes "
               f"at most {max(cpu_sim) * 1000:.0f} ms of CPU in `sim.py` (mean "
               f"{sum(cpu_sim) / len(cpu_sim) * 1000:.1f} ms) and at most {max(cpu_ref) * 1000:.0f} ms in the "
               f"independent scheduler, far under 20 s. Building and screening all {len(cands)} candidate windows "
               f"takes {cpu_build:.1f} s.", ""]
    report += ["## Every policy rule matters", "",
               "Each row breaks one rule in the independent scheduler and counts the test windows whose task log "
               f"then differs from the printed one (out of {len(test_parsed)}). Every rule changes the outcome in "
               "several windows, so a system that skips or misreads a rule gets logs, and answers, wrong. (Breaking "
               "the submit-time tie-break of queue order changes nothing, because task ids are numbered in "
               "submission order, so the task-id tie-break already gives the same order.)", "",
               "| rule broken | windows changed |", "|---|---|"]
    report += [f"| {name} | {n} |" for name, n in sens] + [""]
    report += ["## Documents", "",
               "| run | role | windows | pages | task log rows | descriptive | explanatory | predictive | "
               "counterfactual | total | gold re-derived |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    report += doc_rows
    report += ["", f"Test total: {len(test)} questions; per type: " +
               ", ".join(f"{t} {sum(x[1]['question_type'] == t for x in test)}"
                         for t in ("descriptive", "explanatory", "predictive", "counterfactual")) + ".", ""]
    report += ["## Windows", "",
               f"{sum(c.kept for c in cands)} of {len(cands)} candidate windows met the targets and were kept. Per "
               "window: trace parts, window start (s after the first part's first event), tasks, jobs, production "
               f"/ free-tier tasks, offered load, evictions, tasks stopped by the failure, waits over {LONG_WAIT} s, "
               "running / waiting at the window end, task log rows. Targets: at least "
               f"{S.MIN_EVICTIONS} evictions, at least one failure or long wait, offered load at least "
               f"{S.MIN_LOAD:.2f}.", "",
               "| window | run | parts | start | tasks | jobs | prod / free | load | evictions | fail stops | "
               "long waits | end running / waiting | rows |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    report += [row for _, row in sorted(win_rows)]
    report += [""]

    report += ["## Templates and true/false balance (test documents)", "",
               "| type | template | questions | choices | true share | true per question (min-max) | "
               "distinct answers |", "|---|---|---|---|---|---|---|"]
    by = defaultdict(list)
    for x in test:
        by[(x[1]["question_type"], x[1]["question_subtype"])].append(x[1])
    constant = []
    for (t, st), its in sorted(by.items()):
        if t == "descriptive":
            answers = Counter(it["gold_answer"] for it in its)
            if len(answers) < 2:
                constant.append(f"{t}/{st}")
            report.append(f"| {t} | {st} | {len(its)} | - | - | - | {len(answers)} "
                          f"(most common '{answers.most_common(1)[0][0]}' x{answers.most_common(1)[0][1]}) |")
        else:
            g = [v for it in its for v in it["gold_choices"].values()]
            per = [sum(it["gold_choices"].values()) for it in its]
            if all(g) or not any(g):
                constant.append(f"{t}/{st}")
            report.append(f"| {t} | {st} | {len(its)} | {len(g)} | {sum(g) / len(g):.2f} | {min(per)}-{max(per)} | - |")
    for t in ("explanatory", "predictive", "counterfactual"):
        g = [v for x in test if x[1]["question_type"] == t for v in x[1]["gold_choices"].values()]
        k = Counter(sum(x[1]["gold_choices"].values()) for x in test if x[1]["question_type"] == t)
        report.append(f"| {t} | **all** | {sum(k.values())} | {len(g)} | {sum(g) / len(g):.2f} | "
                      f"{dict(sorted(k.items()))} (true choices: questions) | - |")
    report += ["", "Constant-answer templates: " + (", ".join(constant) if constant else "none") + ". The two "
               "single-answer predictive templates (next_start, start_machine) are near 0.25 true by format: one "
               "of four choices is right.", ""]
    if constant:
        problems.append("constant-answer templates: " + ", ".join(constant))
    ek = defaultdict(list)
    for _, it, m, *_ in test:
        if it["question_type"] == "explanatory":
            for k, i in zip(m["kinds"], range(len(it["choices"]))):
                ek[k].append(it["gold_choices"][str(i)])
    report += ["Explanatory choices by cause kind (test): " +
               "; ".join(f"{k}: {len(v)} choices, {sum(v) / len(v):.2f} true" for k, v in sorted(ek.items())) +
               ". (evictor = the evicting task was submitted; same_machine / other_machine = a task running just "
               "before on the evicted task's machine / on another machine was submitted; holder = a task running "
               "during the wait was submitted; ahead = a higher-priority task that started during the wait was "
               "submitted; job = a job was submitted; failure = the machine failure; own_mem / own_cpu = the "
               "waiting task requested memory / CPU at all.)", ""]
    sk = defaultdict(list)
    for _, it, m, *_ in test:
        if it["question_type"] in ("counterfactual", "predictive") and "kinds" in m:
            for k, i in zip(m["kinds"], range(len(it["choices"]))):
                sk[k].append(it["gold_choices"][str(i)])
    report += ["Statement kinds in counterfactual and will_happen choices (test): " +
               "; ".join(f"{k}: {len(v)}, {sum(v) / len(v):.2f} true" for k, v in sorted(sk.items())) + ".", ""]

    def mc_scores(rows, pred):
        q_ok = o_ok = o_n = 0
        for it, p in zip(rows, pred):
            g = [it["gold_choices"][str(i)] for i in range(len(it["choices"]))]
            o_ok += sum(a == b for a, b in zip(g, p))
            o_n += len(g)
            q_ok += g == p
        return q_ok / len(rows), o_ok / o_n
    report += ["## Simple baselines (test documents)", "",
               "Shortcut answers a system could give without running the policy. Low question accuracy here "
               "means the questions are not solved by copying the record.", "",
               "| type | baseline | question accuracy | option accuracy |", "|---|---|---|---|"]
    for t in ("explanatory", "predictive", "counterfactual"):
        rows = [(x[1], x[2]) for x in test if x[1]["question_type"] == t]
        its = [it for it, _ in rows]
        for name, pred in (("all false", [[False] * len(it["choices"]) for it in its]),
                           ("all true", [[True] * len(it["choices"]) for it in its])):
            qa, oa = mc_scores(its, pred)
            report.append(f"| {t} | {name} | {qa:.2f} | {oa:.2f} |")
        if t == "counterfactual":
            qa, oa = mc_scores(its, [m["baseline"] for _, m in rows])
            report.append(f"| {t} | copy the recorded outcome (ignore the change) | {qa:.2f} | {oa:.2f} |")
        if t == "predictive":
            rr = [(it, m) for it, m in rows if it["question_subtype"] == "next_start"]
            qa, oa = mc_scores([it for it, _ in rr], [[c["choice"].split()[-1] == m["head"] for c in it["choices"]]
                                                      for it, m in rr])
            report.append(f"| {t} (next_start only, n={len(rr)}) | the head of the queue starts first | "
                          f"{qa:.2f} | {oa:.2f} |")
    cfk = Counter(x[2]["intervention"]["kind"] for x in test if x[1]["question_type"] == "counterfactual")
    report += ["", "Counterfactual change kinds (test): " + ", ".join(f"{k} {v}" for k, v in sorted(cfk.items())) +
               ".", ""]

    rng = random.Random(7)
    sample = rng.sample(test, 20)
    report += ["## 20 random test questions for hand-checking", "",
               "Each shows the prompt, the gold, and an excerpt of the document (parsed back from the PDF). For "
               "explanatory, predictive and counterfactual questions the excerpt also gives the result of the "
               "independent scheduler's but-for / continued / changed run, so the gold can be traced.", ""]
    for i, (name, it, m, ps, r, cont) in enumerate(sample, 1):
        q = next(json.loads(l) for l in (RUNS / name / "questions.jsonl").read_text().splitlines()
                 if json.loads(l)["uid"] == it["uid"])
        gold = it["gold_answer"] if it["question_type"] == "descriptive" else \
            ", ".join(f"{k}: {'true' if v else 'false'}" for k, v in it["gold_choices"].items())
        report += [f"### {i}. `{it['uid']}` ({name}, {it['question_type']} / {it['question_subtype']})", "",
                   "```text", q["prompt"], "```", "", f"**Gold:** {gold}", "", "Excerpt:", "", "```text"]
        report += excerpt(it, m, ps, r, cont)
        report += ["```", ""]
    head = [f"**{'PASS' if not problems else 'FAIL'}**: {len(problems)} problem(s) found.", ""]
    if problems:
        head += ["```"] + problems[:200] + ["```", ""]
    report[result_at:result_at + 1] = head
    OUT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"{'PASS' if not problems else 'FAIL'}: {len(problems)} problems; totals {dict(totals)}; "
          f"max sim CPU {max(cpu_sim) * 1000:.0f} ms; wrote {OUT}")
    for p in problems[:25]:
        print("  ", p)


if __name__ == "__main__":
    main()
