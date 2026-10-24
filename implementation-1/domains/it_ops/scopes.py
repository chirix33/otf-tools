"""Build the windows (scopes): one small cluster per window, real workload and failure records.

For each slice (pair of trace parts, see data.py) and each machine REMOVE event in its submission period, in
time order, one candidate window is made (all random choices from one generator seeded with SEED, in this
order):
  1. offset: the window starts at a whole second drawn uniformly so that the removal falls between
     FAIL_AFTER_START s after the window start and FAIL_BEFORE_END s before its end, and the window lies inside
     the submission period;
  2. machines: the removed machine plus N_MACHINES - 1 machines drawn from the real machines that are in the
     cell at the window start and have no REMOVE during the window (no real machine is used in two kept
     windows); their order (ids M01, M02, ...) is a random permutation. Capacity = the machine's recorded
     capacity at the window start divided by CAPACITY_DIVISOR, rounded half-up to whole units. The removed
     machine fails at its removal time and returns at its next ADD time if that is within RETURN_HORIZON s of
     the window start (otherwise it does not return);
  3. workload (the subsampling rule, printed in the front matter): candidate jobs are those whose job SUBMIT
     lies in the window. A job's tasks are its first TASKS_PER_JOB eligible tasks (TASKS_PER_FREE_JOB for a
     free-tier job), lowest task index first, among those submitted before the window end that fit on at least
     one machine of the window when it is empty. Offered load = max over CPU and memory of
     sum(request x run time inside the window) / (cluster capacity x window length). Jobs are taken in this
     order: up to PROD_JOBS production jobs (priority 9-11) in random order; then free-tier jobs (priority 0-1)
     in random order while the offered load is below FREE_SHARE x LOAD_TARGET; then the other jobs in random
     order while it is below LOAD_TARGET. A job that would raise the offered load above LOAD_MAX is skipped.
     Windows of the same slice may share jobs (each is its own random sample of the cell's workload).
A candidate window is kept if it meets the targets: at least MIN_EVICTIONS evictions in the window, at least
one failure or one wait above LONG_WAIT s, and offered load at least MIN_LOAD. Kept windows are numbered 01,
02, ... in order. Chosen once, before any question was generated (sweep in docs/domains/it_operations.md).
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .data import US, MachineHistory, Slice, TraceTask, load_all
from .sim import FREE_MAX, PROD_MIN, Machine, Task, Window, long_waits, simulate

SEED = 2027
WINDOW_S = 1200
N_MACHINES = 8
CAPACITY_DIVISOR = 8
TASKS_PER_JOB = 4
TASKS_PER_FREE_JOB = 16
PROD_JOBS = 6
FREE_SHARE = 0.6
LOAD_TARGET = 0.90
LOAD_MAX = 0.95
FAIL_AFTER_START = 300
FAIL_BEFORE_END = 600
RETURN_HORIZON = 6 * 3600
MIN_EVICTIONS = 2
MIN_LOAD = 0.85
LONG_WAIT = 300


@dataclass
class Candidate:
    window: Window
    kept: bool
    evictions: int
    long_waits: int
    load: tuple[float, float]


def _cap(x: int) -> int:
    return (x + CAPACITY_DIVISOR // 2) // CAPACITY_DIVISOR


def offered_load(tasks, machines, W) -> tuple[float, float]:
    cc = sum(m.cpu for m in machines) * W
    mm = sum(m.mem for m in machines) * W
    c = sum(t.cpu * min(t.duration, W - t.submit) for t in tasks)
    m = sum(t.mem * min(t.duration, W - t.submit) for t in tasks)
    return c / cc, m / mm


def band(p: int) -> str:
    return "prod" if p >= PROD_MIN else "free" if p <= FREE_MAX else "mid"


def make_window(sl: Slice, hist: dict[int, MachineHistory], removal: tuple[int, int, int | None],
                used_machines: set, rng: random.Random) -> Window | None:
    rmid, r_us, back_us = removal
    r_s = (r_us - sl.start_us) // US
    sub_s = (sl.sub_end_us - sl.start_us) // US
    lo = max(0, r_s - (WINDOW_S - FAIL_BEFORE_END))
    hi = min(r_s - FAIL_AFTER_START, sub_s - WINDOW_S)
    if lo > hi:
        return None
    off = rng.randint(lo, hi)
    w0 = sl.start_us + off * US
    w1 = w0 + WINDOW_S * US
    if hist[rmid].capacity_at(w0) is None:
        return None
    pool = sorted(m for m, h in hist.items() if m not in used_machines and m != rmid
                  and h.capacity_at(w0) is not None and not h.outages(w0, w1))
    real = [rmid] + rng.sample(pool, N_MACHINES - 1)
    rng.shuffle(real)
    machines = []
    for i, m in enumerate(real, 1):
        c, mm = hist[m].capacity_at(w0)
        down = back = None
        if m == rmid:
            down = (r_us - w0) // US
            if back_us is not None and (back_us - w0) // US <= RETURN_HORIZON:
                back = (back_us - w0) // US
        machines.append(Machine(f"M{i:02d}", _cap(c), _cap(mm), down, back))
    # workload
    cand: dict[str, list[tuple[int, list[TraceTask]]]] = {"prod": [], "free": [], "mid": []}
    for job in sorted(sl.tasks):
        if not w0 <= sl.job_submit_us[job] < w1:
            continue
        ts = [t for t in sl.tasks[job] if t.submit_us < w1 and
              any(m.cpu >= t.cpu and m.mem >= t.mem for m in machines)]
        if ts:
            b = band(ts[0].priority)
            cand[b].append((job, ts[:TASKS_PER_FREE_JOB if b == "free" else TASKS_PER_JOB]))
    for b in ("prod", "free", "mid"):
        rng.shuffle(cand[b])

    def load(jobs):
        return max(offered_load([Task("", "", t.priority, t.cpu, t.mem, (t.submit_us - w0) // US, t.duration)
                                 for _, ts in jobs for t in ts], machines, WINDOW_S))

    chosen = cand["prod"][:PROD_JOBS]
    for b, target in (("free", FREE_SHARE * LOAD_TARGET), ("mid", LOAD_TARGET)):
        for j in cand[b]:
            if load(chosen) >= target:
                break
            if load(chosen + [j]) <= LOAD_MAX:
                chosen.append(j)
    # ids: tasks in submit order (ties: real job id, task index); jobs numbered by their first task
    flat = sorted((t.submit_us, j, t.index, t) for j, ts in chosen for t in ts)
    job_ids: dict[int, str] = {}
    tasks = []
    for k, (s_us, j, idx, t) in enumerate(flat, 1):
        job_ids.setdefault(j, f"J{len(job_ids) + 1:02d}")
        tasks.append(Task(f"T{k:03d}", job_ids[j], t.priority, t.cpu, t.mem, (s_us - w0) // US, t.duration))
    meta = {"parts": list(sl.parts), "offset_s": off, "start_us": w0, "real_machines": real,
            "real_jobs": {v: k for k, v in job_ids.items()},
            "real_tasks": {tk.tid: [j, idx] for tk, (_, j, idx, _) in zip(tasks, flat)},
            "removal": [rmid, r_us, back_us]}
    w = Window(0, WINDOW_S, machines, tasks, meta)
    w.meta["offered_load"] = list(offered_load(tasks, machines, WINDOW_S))
    return w


def candidates(slices=None, hist=None) -> list[Candidate]:
    if slices is None:
        slices, hist = load_all()
    rng = random.Random(SEED)
    used_machines: set = set()
    out = []
    for sl in slices:
        removals = sorted(((m, t, back) for m, h in hist.items() for t, back in h.outages(sl.start_us, sl.sub_end_us)),
                          key=lambda x: (x[1], x[0]))
        for rem in removals:
            if rem[0] in used_machines:
                continue
            w = make_window(sl, hist, rem, used_machines, rng)
            if w is None:
                continue
            res = simulate(w, until=w.length)
            ne = len(res.evictions(w.length))
            nl = len(long_waits(res, LONG_WAIT, w.length))
            nf = sum(1 for m in w.machines if m.down is not None and m.down <= w.length)
            kept = ne >= MIN_EVICTIONS and (nf >= 1 or nl >= 1) and max(w.meta["offered_load"]) >= MIN_LOAD
            out.append(Candidate(w, kept, ne, nl, tuple(w.meta["offered_load"])))
            if kept:
                used_machines.update(w.meta["real_machines"])
    n = 0
    for c in out:
        if c.kept:
            n += 1
            c.window.number = n
    return out


def all_windows() -> list[Window]:
    return [c.window for c in candidates() if c.kept]
