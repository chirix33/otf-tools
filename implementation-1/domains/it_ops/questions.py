"""Question generator for the four types. Every gold label comes from the reference scheduler (sim.py).

descriptive     open-ended lookups/counts in the window's task log
explanatory     MC, multi-correct: causes of an eviction or of a long wait; a cause is correct iff the but-for run
                (that condition removed, everything else as recorded) removes the outcome
predictive      MC: what happens after the window end (continued run from the end state, no new arrivals)
counterfactual  MC, multi-correct: re-run the window with one change (remove a job / remove the failure /
                change a priority / halve a request / one machine fewer), everything else as recorded
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

from .scopes import LONG_WAIT
from .sim import FREE_MAX, PROD_MIN, SimResult, Window, simulate

DESC_TEMPLATES = ("first_machine", "n_evictions", "wait", "finish_time", "n_starts", "running_on")
EXPL_TEMPLATES = ("evict_cause", "wait_cause")
PRED_TEMPLATES = ("will_happen", "next_start", "start_machine")
CF_KINDS = ("remove_job", "remove_failure", "set_priority", "set_request", "remove_machine")
N_CHOICES = 4

# running tallies across one build, used to keep answers from following an exploitable pattern
_EXPL_SEEN: Counter = Counter()          # (cause kind, truth)
_STMT_SEEN: Counter = Counter()          # (statement kind, truth), counterfactual and predictive
_ANSWER_USED: Counter = Counter()        # descriptive answers / single-answer MC positions


def reset_balance() -> None:
    _EXPL_SEEN.clear()
    _STMT_SEEN.clear()
    _ANSWER_USED.clear()


@dataclass
class Question:
    scope: str
    qtype: str
    subtype: str
    question: str
    choices: list[str] = field(default_factory=list)
    gold_answer: str | None = None
    gold_choices: list[bool] = field(default_factory=list)
    meta: dict = field(default_factory=dict)       # interventions, statement args (for validation only)


# ---------------------------------------------------------------- facts about a run (window period: times <= W)
def first_start_in(r: SimResult, tid: str, W: int) -> int | None:
    s = r.runs[tid].first_start
    return s if s is not None and s <= W else None


def running_at(r: SimResult, t: int) -> dict[str, str]:
    """task -> machine for tasks running after all events at time t (replayed from the log)."""
    on: dict[str, str] = {}
    for tt, tid, ev, mid in r.log:
        if tt > t:
            break
        if ev == "start":
            on[tid] = mid
        elif ev in ("finish", "evict", "fail"):
            on.pop(tid, None)
    return on


def n_evictions(r: SimResult, W: int) -> int:
    return sum(1 for t, _, ev, _ in r.log if ev == "evict" and t <= W)


def stmt_truth(kind: str, a: dict, r: SimResult, W: int) -> bool:
    """Truth of a statement in run r. Window statements use events at times <= W; 'p_' statements are about
    what happens after W (r must be a full run)."""
    if kind in ("first_machine", "start_earlier", "start_later", "evicted", "finish_by", "long_wait"):
        run = r.runs.get(a["t"])
        if run is None:
            return False
        fs = first_start_in(r, a["t"], W)
        if kind == "first_machine":
            return fs is not None and run.first_machine == a["m"]
        if kind == "start_earlier":
            return fs is not None and fs < a["x"]
        if kind == "start_later":
            return fs is None or fs > a["x"]
        if kind == "evicted":
            return any(t <= W for t, _, _ in run.evictions)
        if kind == "finish_by":
            return run.finish is not None and run.finish <= W
        if kind == "long_wait":
            return fs is None or fs - run.submit > LONG_WAIT
    if kind == "fewer_evictions":
        return n_evictions(r, W) < a["n"]
    if kind == "more_evictions":
        return n_evictions(r, W) > a["n"]
    if kind.startswith("p_"):
        run = r.runs[a["t"]]
        later = [(t, m) for t, m in run.starts if t > W]
        if kind == "p_finish_by":
            return run.finish is not None and run.finish <= a["x"]
        if kind == "p_start_by":
            return bool(later) and later[0][0] <= a["x"]
        if kind == "p_start_on":
            return bool(later) and later[0][1] == a["m"]
        if kind == "p_evicted":
            return any(t > W for t, _, _ in run.evictions)
    raise ValueError(kind)


def stmt_text(kind: str, a: dict, W: int) -> str:
    t = a.get("t")
    return {
        "first_machine": lambda: f"task {t} would first start on machine {a.get('m')}",
        "start_earlier": lambda: f"task {t} would first start earlier than time {a.get('x')} (its recorded first start)",
        "start_later": lambda: f"task {t} would first start later than time {a.get('x')} (its recorded first start), "
                               f"or not at all by time {W}",
        "evicted": lambda: f"task {t} would be evicted at least once by time {W}",
        "finish_by": lambda: f"task {t} would finish by time {W}",
        "long_wait": lambda: f"task {t} would wait more than {LONG_WAIT} s before its first start",
        "fewer_evictions": lambda: f"there would be fewer evictions by time {W} than the recorded {a.get('n')}",
        "more_evictions": lambda: f"there would be more evictions by time {W} than the recorded {a.get('n')}",
        "p_finish_by": lambda: f"task {t} will finish no later than time {a.get('x')}",
        "p_start_by": lambda: f"task {t} will start no later than time {a.get('x')}",
        "p_start_on": lambda: f"task {t} will start on machine {a.get('m')}",
        "p_evicted": lambda: f"task {t} will be evicted before it finishes",
    }[kind]()


def _pick(cands: list[dict], rng: random.Random, min_changed: int, want_changed: int,
          focus: str | None = None) -> list[dict] | None:
    """N_CHOICES statements: a random number of true ones (1-3), at least `min_changed` whose truth differs
    from the baseline, at most 2 of a kind, and when `focus` is set at least one about that task. Within the
    candidates, (kind, truth) pairs that move the running true share of their kind toward one half go first."""
    k_true = rng.choice((1, 2, 2, 3))
    rng.shuffle(cands)

    def helps(c):
        t, f = _STMT_SEEN[(c["kind"], True)], _STMT_SEEN[(c["kind"], False)]
        return (c["truth"] and t <= f) or (not c["truth"] and f < t)
    cands.sort(key=lambda c: not helps(c))
    chosen: list[dict] = []

    def fits(c, strict):
        if c in chosen or any(x["text"] == c["text"] for x in chosen):
            return False
        if sum(x["kind"] == c["kind"] for x in chosen) >= 2:
            return False
        if strict:
            nt = sum(x["truth"] for x in chosen)
            if c["truth"] and nt >= k_true:
                return False
            if not c["truth"] and len(chosen) - nt >= N_CHOICES - k_true:
                return False
        return True

    order = []
    if focus:
        order.append([c for c in cands if c["task"] == focus and c["changed"]][:1] or
                     [c for c in cands if c["task"] == focus][:1])
    order.append([c for c in cands if c["changed"]])
    order.append(cands)
    for strict in (True, False):
        for i, group in enumerate(order):
            for c in group:
                if len(chosen) >= N_CHOICES:
                    break
                if group is order[-2] and sum(x["changed"] for x in chosen) >= want_changed:
                    break
                if fits(c, strict):
                    chosen.append(c)
                    if focus and i == 0:
                        break
    if len(chosen) < N_CHOICES or sum(x["changed"] for x in chosen) < min_changed:
        return None
    if all(x["truth"] for x in chosen) or not any(x["truth"] for x in chosen):
        return None
    rng.shuffle(chosen)
    return chosen


def _commit(chosen: list[dict]) -> None:
    for c in chosen:
        _STMT_SEEN[(c["kind"], c["truth"])] += 1


def _least_used(cands: list, key, rng: random.Random):
    least = min(_ANSWER_USED[key(c)] for c in cands)
    pick = rng.choice([c for c in cands if _ANSWER_USED[key(c)] == least])
    _ANSWER_USED[key(pick)] += 1
    return pick


# ---------------------------------------------------------------- descriptive
def descriptive(w: Window, f: SimResult, template: str, rng: random.Random) -> Question | None:
    T, W = w.title, w.length
    started = [tid for tid in f.runs if first_start_in(f, tid, W) is not None]
    if template == "first_machine":
        moved = [tid for tid in started if f.wait(tid) > 0 or len(f.runs[tid].starts) > 1]
        pool = moved if (moved and rng.random() < 0.7) else started
        tid = _least_used(pool, lambda x: ("fm", f.runs[x].first_machine), rng)
        return Question(T, "descriptive", template,
                        f"In {T}, on which machine did task {tid} first start? Answer with the machine id.",
                        gold_answer=f.runs[tid].first_machine.lower())
    if template == "n_evictions":
        return Question(T, "descriptive", template,
                        f"In {T}, how many evictions happened from time 0 to time {W}?",
                        gold_answer=str(n_evictions(f, W)))
    if template == "wait":
        waited = [tid for tid in started if f.wait(tid) > 0]
        pool = waited if (waited and rng.random() < 0.85) else started
        tid = rng.choice(pool)
        return Question(T, "descriptive", template,
                        f"In {T}, how many seconds passed between the submission of task {tid} and its first "
                        "start?", gold_answer=str(f.wait(tid)))
    if template == "finish_time":
        done = [tid for tid, r in f.runs.items() if r.finish is not None and r.finish <= W]
        hard = [tid for tid in done if f.wait(tid) > 0 or len(f.runs[tid].starts) > 1]
        pool = hard if (hard and rng.random() < 0.75) else done
        if not pool:
            return None
        tid = rng.choice(pool)
        return Question(T, "descriptive", template, f"In {T}, at what time did task {tid} finish?",
                        gold_answer=str(f.runs[tid].finish))
    if template == "n_starts":
        def starts(tid):
            return sum(1 for t, _ in f.runs[tid].starts if t <= W)
        multi = [tid for tid in started if starts(tid) > 1]
        pool = multi if (multi and rng.random() < 0.5) else started
        tid = rng.choice(pool)
        return Question(T, "descriptive", template,
                        f"In {T}, how many times did task {tid} start from time 0 to time {W}?",
                        gold_answer=str(starts(tid)))
    if template == "running_on":
        times = sorted({t for t, _, ev, _ in f.log if t <= W and ev in ("start", "evict", "fail")})
        if not times:
            return None
        for _ in range(20):
            t = rng.choice(times)
            on = running_at(f, t)
            m = rng.choice([m.mid for m in w.machines])
            n = sum(1 for x in on.values() if x == m)
            if n > 0 or rng.random() < 0.15:
                break
        return Question(T, "descriptive", template,
                        f"In {T}, how many tasks were running on machine {m} at time {t}, after all the events "
                        "at that time?", gold_answer=str(n))
    raise ValueError(template)


# ---------------------------------------------------------------- explanatory
def _helps_expl(c) -> bool:
    t, f = _EXPL_SEEN[(c["kind"], True)], _EXPL_SEEN[(c["kind"], False)]
    return (c["truth"] and t <= f) or (not c["truth"] and f < t)


def _choose_expl(cands: list[dict], rng: random.Random) -> list[dict] | None:
    if not any(c["truth"] for c in cands) or all(c["truth"] for c in cands):
        return None
    k_true = rng.choice((1, 2, 2, 3))
    rng.shuffle(cands)
    cands.sort(key=lambda c: not _helps_expl(c))
    chosen: list[dict] = []
    for strict in (True, False):
        for c in cands:
            if len(chosen) >= N_CHOICES:
                break
            if c in chosen or sum(x["kind"] == c["kind"] for x in chosen) >= 2:
                continue
            seen_t, seen_f = _EXPL_SEEN[(c["kind"], True)], _EXPL_SEEN[(c["kind"], False)]
            if not _helps_expl(c) and abs(seen_t - seen_f) >= 2:
                continue                       # keep every cause kind close to half true
            nt = sum(x["truth"] for x in chosen)
            if strict and ((c["truth"] and nt >= k_true) or (not c["truth"] and len(chosen) - nt >= N_CHOICES - k_true)):
                continue
            chosen.append(c)
    if len(chosen) < N_CHOICES or all(x["truth"] for x in chosen) or not any(x["truth"] for x in chosen):
        return None
    rng.shuffle(chosen)
    return chosen


def _running_during(f: SimResult, a: int, b: int) -> dict[str, str]:
    """task -> a machine it ran on at some time in [a, b) (after the events at that time)."""
    out: dict[str, str] = {}
    on = running_at(f, a)
    out.update(on)
    for t, tid, ev, mid in f.log:
        if a < t < b and ev == "start":
            out.setdefault(tid, mid)
    return out


def explanatory(w: Window, f: SimResult, template: str, rng: random.Random) -> Question | None:
    T, W = w.title, w.length
    best = None
    if template == "evict_cause":
        targets = [(t, tid, mid, by) for t, tid, mid, by in f.evictions(W)]
        rng.shuffle(targets)
        for t, x, mid, by in targets[:8]:
            jx, jp = f.tasks[x].job, f.tasks[by].job
            on = running_at(f, t - 1) if t > 0 else {}
            pool = [(f"task {by} was submitted (at time {f.tasks[by].submit})", {"kind": "remove_task", "task": by},
                     "evictor")]
            for u, m in sorted(on.items()):
                if u in (x, by):
                    continue
                k = "same_machine" if m == mid else "other_machine"
                pool.append((f"task {u} was submitted (it was running on machine {m} just before time {t})",
                             {"kind": "remove_task", "task": u}, k))
            for m in w.machines:
                if m.down is not None and m.down < t:
                    pool.append((f"machine {m.mid} failed at time {m.down}", {"kind": "remove_failure",
                                                                            "machine": m.mid}, "failure"))
            jobs = sorted({f.tasks[u].job for u in on} - {jx, jp})
            for j in jobs:
                pool.append((f"job {j} was submitted", {"kind": "remove_job", "job": j}, "job"))
            rng.shuffle(pool)
            pool = [p for p in pool if p[2] in ("evictor", "failure")] + \
                [p for p in pool if p[2] not in ("evictor", "failure")][:10]
            cands = []
            for text, iv, k in pool:
                r = simulate(w, [iv], until=t)
                still = any(tt == t for tt, _, _ in r.runs[x].evictions) if x in r.runs else False
                cands.append({"text": text, "truth": not still, "kind": k, "iv": iv})
            chosen = _choose_expl(cands, rng)
            if chosen is None:
                continue
            score = sum(_helps_expl(c) for c in chosen)
            if best is not None and score <= best[0]:
                continue
            best = (score, Question(
                T, "explanatory", template,
                f"In {T}, task {x} was evicted from machine {mid} at time {t}. Which of the following are "
                f"responsible for that? A condition is responsible if, without it and with everything else as "
                f"recorded, task {x} would not have been evicted at time {t}.",
                choices=[c["text"] for c in chosen], gold_choices=[c["truth"] for c in chosen],
                meta={"target": {"kind": "evicted_at", "task": x, "time": t}, "kinds": [c["kind"] for c in chosen],
                      "interventions": [c["iv"] for c in chosen]}))
    elif template == "wait_cause":
        targets = [tid for tid in f.runs if first_start_in(f, tid, W) is not None and f.wait(tid) > LONG_WAIT]
        rng.shuffle(targets)
        for x in targets[:8]:
            s, fs = f.runs[x].submit, f.runs[x].first_start
            tx = f.tasks[x]
            during = _running_during(f, s, fs)
            pool = [(f"task {x} requested memory ({tx.mem} units)", {"kind": "set_request", "task": x,
                                                                     "resource": "mem", "value": 0}, "own_mem"),
                    (f"task {x} requested CPU ({tx.cpu} units)", {"kind": "set_request", "task": x,
                                                                  "resource": "cpu", "value": 0}, "own_cpu")]
            for m in w.machines:
                if m.down is not None and m.down < fs:
                    pool.append((f"machine {m.mid} failed at time {m.down}", {"kind": "remove_failure",
                                                                            "machine": m.mid}, "failure"))
            ahead = sorted(u for u in during if f.tasks[u].priority > tx.priority and f.runs[u].submit <= fs
                           and (first_start_in(f, u, W) or 0) >= s)
            for u in ahead:
                pool.append((f"task {u} was submitted (priority {f.tasks[u].priority}; it started at time "
                             f"{next(tt for tt, _ in f.runs[u].starts if tt >= s)} while task {x} was waiting)",
                             {"kind": "remove_task", "task": u}, "ahead"))
            for u, m in sorted(during.items()):
                if u != x and u not in ahead and f.tasks[u].job != tx.job:
                    pool.append((f"task {u} was submitted (it ran on machine {m} while task {x} was waiting)",
                                 {"kind": "remove_task", "task": u}, "holder"))
            for j in sorted({f.tasks[u].job for u in during} - {tx.job}):
                pool.append((f"job {j} was submitted", {"kind": "remove_job", "job": j}, "job"))
            rng.shuffle(pool)
            fixed = [p for p in pool if p[2] in ("own_mem", "own_cpu", "failure")]
            pool = fixed + [p for p in pool if p not in fixed][:10]
            cands = []
            for text, iv, k in pool:
                r = simulate(w, [iv], until=s + LONG_WAIT)
                fs2 = r.runs[x].first_start
                cands.append({"text": text, "truth": fs2 is not None and fs2 - s <= LONG_WAIT, "kind": k,
                              "iv": iv})
            chosen = _choose_expl(cands, rng)
            if chosen is None:
                continue
            score = sum(_helps_expl(c) for c in chosen)
            if best is not None and score <= best[0]:
                continue
            best = (score, Question(
                T, "explanatory", template,
                f"In {T}, task {x} was submitted at time {s} and first started at time {fs}, more than "
                f"{LONG_WAIT} s later. Which of the following are responsible for that wait? A condition is "
                f"responsible if, without it and with everything else as recorded, task {x} would have first "
                f"started within {LONG_WAIT} s of its submission.",
                choices=[c["text"] for c in chosen], gold_choices=[c["truth"] for c in chosen],
                meta={"target": {"kind": "waited", "task": x, "submit": s}, "kinds": [c["kind"] for c in chosen],
                      "interventions": [c["iv"] for c in chosen]}))
    else:
        raise ValueError(template)
    if best is None:
        return None
    q = best[1]
    for k, g in zip(q.meta["kinds"], q.gold_choices):
        _EXPL_SEEN[(k, g)] += 1
    return q


# ---------------------------------------------------------------- predictive
def _threshold(v: int, truth: bool, rng: random.Random) -> int:
    """A round time (multiple of 10) on the requested side of v: >= v if truth, else < v."""
    d = rng.randint(1, 12) * 10
    return -(-(v + d - 10) // 10) * 10 if truth else ((v - d) // 10) * 10


def predictive(w: Window, f: SimResult, template: str, rng: random.Random) -> Question | None:
    T, W = w.title, w.length
    es = f.end_state
    lead = (f"In {T}, continuing after time {W} from the state in 'Queue at window end', with no new submissions "
            "and no further failures, ")
    pending = [tid for tid in es["pending"] if any(t > W for t, _ in f.runs[tid].starts)]

    def next_start(tid):
        return next(t for t, _ in f.runs[tid].starts if t > W)

    def next_machine(tid):
        return next(m for t, m in f.runs[tid].starts if t > W)
    if template == "will_happen":
        cands = []
        for tid, x in es["running"].items():
            fin = f.runs[tid].finish
            if fin is not None:
                truth = rng.random() < 0.5
                cands.append(("p_finish_by", {"t": tid, "x": _threshold(fin, truth, rng)}))
            if f.tasks[tid].priority <= FREE_MAX:
                cands.append(("p_evicted", {"t": tid}))
        for tid in es["pending"]:
            starts = [(t, m) for t, m in f.runs[tid].starts if t > W]
            if starts:
                cands.append(("p_start_by", {"t": tid, "x": _threshold(starts[0][0], rng.random() < 0.5, rng)}))
                cands.append(("p_start_on", {"t": tid, "m": starts[0][1]}))
                others = [m.mid for m in w.machines if m.mid != starts[0][1]]
                cands.append(("p_start_on", {"t": tid, "m": rng.choice(others)}))
                if f.runs[tid].finish is not None:
                    cands.append(("p_finish_by", {"t": tid, "x": _threshold(f.runs[tid].finish, rng.random() < 0.5,
                                                                            rng)}))
            if f.tasks[tid].priority <= FREE_MAX:
                cands.append(("p_evicted", {"t": tid}))
        stm = []
        for kind, a in cands:
            if kind.endswith("_by") and a["x"] <= W:
                continue
            stm.append({"kind": kind, "args": a, "text": stmt_text(kind, a, W), "truth": stmt_truth(kind, a, f, W),
                        "baseline": None, "changed": True, "task": a["t"]})
        chosen = _pick(stm, rng, 0, 0)
        if chosen is None:
            return None
        _commit(chosen)
        return Question(T, "predictive", template, lead + "which of the following will happen?",
                        choices=[c["text"] for c in chosen], gold_choices=[c["truth"] for c in chosen],
                        meta={"kinds": [c["kind"] for c in chosen], "args": [c["args"] for c in chosen]})
    if template == "next_start":
        if len(pending) < 3:
            return None
        first = min(next_start(t) for t in pending)
        winners = [t for t in pending if next_start(t) == first]
        losers = [t for t in pending if next_start(t) > first]
        if not losers:
            return None
        k = rng.choice((1, 1, 2)) if len(winners) > 1 else 1
        head = es["pending"][0]
        picks = rng.sample(winners, min(k, len(winners)))
        rest = [t for t in losers if t not in picks]
        rng.shuffle(rest)
        if head in rest:                   # the queue head is a natural guess: include it when it is wrong
            rest.remove(head)
            rest.insert(0, head)
        picks += rest[:N_CHOICES - len(picks)]
        if len(picks) < 3:
            return None
        rng.shuffle(picks)
        gold = [next_start(t) == first for t in picks]
        return Question(T, "predictive", template,
                        lead + "which of these waiting tasks will be the first of them to start? If several of "
                        "them start first at the same time, each of them is correct.",
                        choices=[f"task {t}" for t in picks], gold_choices=gold,
                        meta={"tasks": picks, "next_start": {t: next_start(t) for t in picks},
                              "head": head})
    if template == "start_machine":
        if not pending:
            return None
        tid = _least_used(pending, lambda t: ("sm", next_machine(t)), rng)
        right = next_machine(tid)
        others = [m.mid for m in w.machines if m.mid != right]
        picks = [right] + rng.sample(others, N_CHOICES - 1)
        rng.shuffle(picks)
        return Question(T, "predictive", template,
                        lead + f"on which machine will task {tid} start?",
                        choices=[f"machine {m}" for m in picks], gold_choices=[m == right for m in picks],
                        meta={"task": tid, "machine": right})
    raise ValueError(template)


# ---------------------------------------------------------------- counterfactual
def _cf_candidates(w: Window, f: SimResult, kind: str) -> list[tuple[dict, str]]:
    W = w.length
    out = []
    if kind == "remove_job":
        for j in sorted({t.job for t in w.tasks}):
            n = sum(t.job == j for t in w.tasks)
            out.append(({"kind": "remove_job", "job": j},
                        f"job {j} (its {n} task{'s' if n > 1 else ''}) had not been submitted"))
    elif kind == "remove_failure":
        for m in w.machines:
            if m.down is not None and m.down <= W:
                out.append(({"kind": "remove_failure", "machine": m.mid},
                            f"machine {m.mid} had not failed at time {m.down}"))
    elif kind == "set_priority":
        for t in w.tasks:
            if t.submit > W - 60:
                continue
            new = PROD_MIN if t.priority < PROD_MIN else 0
            out.append(({"kind": "set_priority", "task": t.tid, "value": new},
                        f"task {t.tid} had had priority {new} instead of {t.priority}"))
    elif kind == "set_request":
        for t in w.tasks:
            if t.submit > W - 60:
                continue
            for r, name in (("mem", "memory"), ("cpu", "CPU")):
                v = getattr(t, r)
                if v >= 2:
                    out.append(({"kind": "set_request", "task": t.tid, "resource": r, "value": v // 2},
                                f"task {t.tid} had requested half as much {name} ({v // 2} units instead of {v})"))
    elif kind == "remove_machine":
        for m in w.machines:
            out.append(({"kind": "remove_machine", "machine": m.mid},
                        f"machine {m.mid} had not been part of the cluster (one machine fewer)"))
    return out


def _interesting(f: SimResult, W: int) -> set[str]:
    """Tasks whose window history is not trivial (waited, restarted, evicted or unfinished)."""
    return {tid for tid, r in f.runs.items() if r.submit <= W and (
        f.wait(tid) is None or f.wait(tid) > 0 or len(r.starts) > 1 or r.finish is None or r.finish > W)}


def counterfactual(w: Window, f: SimResult, kind: str, rng: random.Random) -> Question | None:
    T, W = w.title, w.length
    cands = _cf_candidates(w, f, kind)
    rng.shuffle(cands)
    base_n = n_evictions(f, W)
    hot = _interesting(f, W)
    for iv, clause in cands[:25]:
        r = simulate(w, [iv], until=W)
        if [e for e in r.log if e[0] <= W] == [e for e in f.log if e[0] <= W]:
            continue                                    # the change has no visible consequence
        gone = {t for t in f.runs if t not in r.runs}
        changed = {tid for tid in r.runs if tid in f.runs and
                   ([x for x in r.runs[tid].starts if x[0] <= W], [x for x in r.runs[tid].stops if x[0] <= W])
                   != ([x for x in f.runs[tid].starts if x[0] <= W], [x for x in f.runs[tid].stops if x[0] <= W])}
        focus = iv.get("task")
        pool = sorted(changed | (hot - gone))
        rng.shuffle(pool)
        tasks = sorted(set(pool[:30]) | ({focus} if focus else set()))
        stm = []
        for tid in tasks:
            fs = first_start_in(f, tid, W)
            s = f.runs[tid].submit
            opts = [("evicted", {"t": tid}), ("finish_by", {"t": tid})]
            if s <= W - LONG_WAIT:
                opts.append(("long_wait", {"t": tid}))
            if fs is not None:
                opts += [("start_earlier", {"t": tid, "x": fs}), ("start_later", {"t": tid, "x": fs})]
            ms = [m.mid for m in r.machines]
            m1 = r.runs[tid].first_machine if first_start_in(r, tid, W) is not None else None
            if m1 is not None:
                opts.append(("first_machine", {"t": tid, "m": m1}))
            if f.runs[tid].first_machine in ms and fs is not None and f.runs[tid].first_machine != m1:
                opts.append(("first_machine", {"t": tid, "m": f.runs[tid].first_machine}))
            for k, a in opts:
                stm.append({"kind": k, "args": a, "text": stmt_text(k, a, W), "truth": stmt_truth(k, a, r, W),
                            "baseline": stmt_truth(k, a, f, W), "task": tid})
        for k in ("fewer_evictions", "more_evictions"):
            a = {"n": base_n}
            stm.append({"kind": k, "args": a, "text": stmt_text(k, a, W), "truth": stmt_truth(k, a, r, W),
                        "baseline": False, "task": ""})
        for c in stm:
            c["changed"] = c["truth"] != c["baseline"]
        chosen = _pick(stm, rng, 1, 2, focus=focus)
        if chosen is None:
            continue
        _commit(chosen)
        return Question(T, "counterfactual", kind,
                        f"In {T}, suppose {clause}, with everything else as recorded. Which of the following "
                        f"would have happened by time {W}?",
                        choices=[c["text"] for c in chosen], gold_choices=[c["truth"] for c in chosen],
                        meta={"intervention": iv, "baseline": [c["baseline"] for c in chosen],
                              "kinds": [c["kind"] for c in chosen], "args": [c["args"] for c in chosen]})
    return None
