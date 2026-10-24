"""Reference scheduler: the policy written in every document's front matter.

One window = one small cluster, starting empty at time 0. Times are whole seconds from the window start.
At every time at which something happens, in this order:
  1. tasks whose run time is over finish and free their CPU and memory;
  2. machines that fail at this time go down; the tasks running on them stop ("fail") and go back to the queue;
  3. machines that return at this time come back, empty, with their capacity;
  4. tasks submitted at this time join the queue;
  5. one scheduling round (below).
Scheduling round. Pending tasks are taken in queue order: priority (higher first), then submit time (earlier
first), then task id. For each task in turn:
  a. first fit: it starts on the first up machine (machines in id order) whose free CPU and free memory are both
     at least its requests (and, if a reservation is held, the start does not delay the reserved task, see c);
  b. preemption: if it does not fit, no reservation is held yet and it is a production task (priority 9-11), it
     looks at the up machines in id order; on each it considers the free-tier tasks (priority 0-1) running there,
     lowest priority first, then the most recently started first (then the higher task id first), and evicts
     them one by one in that order until it fits; it takes the first machine where this works. If no machine
     works, nothing is evicted. Evicted tasks go back to the queue, lose their progress, and restart from the
     beginning (with their full run time) when they start again; they keep their original submit time;
  c. reservation (backfilling): the first task in the round that can start neither by a. nor by b. gets a
     reservation: its earliest possible start, computed from the recorded run times of the tasks now running
     (no new arrivals, failures or returns assumed), on the first machine where that time is reached. Every
     later task in the round may start only if it does not delay that reservation: on the reserved machine it
     may start only if it finishes no later than the reserved time, or if its requests fit in what the
     reserved machine will still have free at that time after the reserved task's requests. Later tasks do not
     preempt. A task that cannot fit on any up machine even when that machine is empty gets no reservation.
A task runs for exactly its recorded run time once started. Tasks that are evicted or stopped by a failure
restart from the beginning.

Deterministic: integer units and seconds, no randomness, sorted iteration only.

Interventions (applied to the recorded inputs before the run; everything else held as recorded):
  {"kind": "remove_job", "job": J}                               job J's tasks are never submitted
  {"kind": "remove_failure", "machine": M}                       machine M does not fail in the window
  {"kind": "set_priority", "task": T, "value": p}                task T has priority p
  {"kind": "set_request", "task": T, "resource": r, "value": v}  task T requests v units of r ("cpu"/"mem")
  {"kind": "remove_machine", "machine": M}                       machine M is not part of the cluster
Mechanism switches used only for the but-for test of explanatory questions:
  {"kind": "remove_task", "task": T}                             task T is never submitted
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field, replace

PROD_MIN = 9                     # production tier: priority 9-11
FREE_MAX = 1                     # free tier: priority 0-1
INPUT_KINDS = ("remove_job", "remove_failure", "set_priority", "set_request", "remove_machine")
MECHANISM_KINDS = ("remove_task",)


@dataclass(frozen=True)
class Task:
    tid: str
    job: str
    priority: int
    cpu: int
    mem: int
    submit: int
    duration: int


@dataclass(frozen=True)
class Machine:
    mid: str
    cpu: int
    mem: int
    down: int | None = None      # failure time (None: no failure in the window)
    back: int | None = None      # return time (None: does not return)


@dataclass
class Window:
    number: int
    length: int                  # W: the window covers times 0..W
    machines: list[Machine]
    tasks: list[Task]
    meta: dict = field(default_factory=dict)       # provenance (real trace ids and times); not printed

    @property
    def title(self) -> str:
        return f"Cell window {self.number:02d}"

    def task(self, tid: str) -> Task:
        return next(t for t in self.tasks if t.tid == tid)

    def machine(self, mid: str) -> Machine:
        return next(m for m in self.machines if m.mid == mid)


@dataclass
class TaskRun:
    submit: int
    starts: list[tuple[int, str]] = field(default_factory=list)       # (time, machine)
    stops: list[tuple[int, str, str, str | None]] = field(default_factory=list)  # (time, machine, evict|fail, by)
    finish: int | None = None

    @property
    def first_start(self) -> int | None:
        return self.starts[0][0] if self.starts else None

    @property
    def first_machine(self) -> str | None:
        return self.starts[0][1] if self.starts else None

    @property
    def evictions(self) -> list[tuple[int, str, str | None]]:
        return [(t, m, by) for t, m, k, by in self.stops if k == "evict"]


@dataclass
class SimResult:
    window: Window
    tasks: dict[str, Task]                       # after interventions
    machines: list[Machine]
    log: list[tuple[int, str, str, str | None]]  # (time, task, event, machine) in processing order
    runs: dict[str, TaskRun]
    end_state: dict                              # state after the events at time W
    stuck: list[str]                             # tasks that can never start (no machine big enough)
    until: int | None

    def wait(self, tid: str) -> int | None:
        r = self.runs[tid]
        return None if r.first_start is None else r.first_start - r.submit

    def evictions(self, until: int | None = None) -> list[tuple[int, str, str, str]]:
        """(time, evicted task, machine, by task), time order."""
        out = [(t, tid, m, by) for tid, r in self.runs.items() for t, m, by in r.evictions
               if until is None or t <= until]
        return sorted(out, key=lambda x: (x[0], self.log_pos[(x[0], x[1], "evict")]))

    @property
    def log_pos(self) -> dict:
        if not hasattr(self, "_pos"):
            self._pos = {}
            for i, (t, tid, ev, _) in enumerate(self.log):
                self._pos.setdefault((t, tid, ev), i)
        return self._pos


def apply(w: Window, ivs) -> tuple[list[Task], list[Machine]]:
    tasks, machines = list(w.tasks), list(w.machines)
    for iv in ivs:
        k = iv["kind"]
        if k == "remove_job":
            tasks = [t for t in tasks if t.job != iv["job"]]
        elif k == "remove_task":
            tasks = [t for t in tasks if t.tid != iv["task"]]
        elif k == "set_priority":
            tasks = [replace(t, priority=iv["value"]) if t.tid == iv["task"] else t for t in tasks]
        elif k == "set_request":
            tasks = [replace(t, **{iv["resource"]: iv["value"]}) if t.tid == iv["task"] else t for t in tasks]
        elif k == "remove_failure":
            machines = [replace(m, down=None, back=None) if m.mid == iv["machine"] else m for m in machines]
        elif k == "remove_machine":
            machines = [m for m in machines if m.mid != iv["machine"]]
        else:
            raise ValueError(k)
    return tasks, machines


def simulate(w: Window, ivs=(), until: int | None = None) -> SimResult:
    """Run the window (and, if until is None, on past W with no new arrivals until every task that can start
    has finished). Returns the full log and per-task runs."""
    tasks, machines = apply(w, ivs)
    T = {t.tid: t for t in tasks}
    mids = [m.mid for m in machines]
    M = {m.mid: m for m in machines}
    up = {m.mid: True for m in machines}
    run_on: dict[str, dict[str, int]] = {m: {} for m in mids}       # machine -> {task: end time}
    started_at: dict[str, int] = {}
    where: dict[str, str] = {}
    free = {m.mid: [m.cpu, m.mem] for m in machines}
    runs = {tid: TaskRun(t.submit) for tid, t in T.items()}
    log: list[tuple[int, str, str, str | None]] = []
    queue: list[tuple] = []                                          # sorted keys (-pri, submit, tid)
    key = {tid: (-t.priority, t.submit, tid) for tid, t in T.items()}
    subs: dict[int, list[str]] = {}
    for tid, t in T.items():
        subs.setdefault(t.submit, []).append(tid)
    downs = {m.down: [] for m in machines if m.down is not None}
    backs = {m.back: [] for m in machines if m.down is not None and m.back is not None}
    for m in machines:
        if m.down is not None:
            downs[m.down].append(m.mid)
            if m.back is not None:
                backs[m.back].append(m.mid)
    ends: dict[int, set[str]] = {}
    end_state: dict = {}
    W = w.length

    def start(tid, mid, now):
        t = T[tid]
        free[mid][0] -= t.cpu
        free[mid][1] -= t.mem
        run_on[mid][tid] = now + t.duration
        started_at[tid] = now
        where[tid] = mid
        ends.setdefault(now + t.duration, set()).add(tid)
        runs[tid].starts.append((now, mid))
        log.append((now, tid, "start", mid))

    def stop(tid, now, kind, by=None):
        mid = where.pop(tid)
        t = T[tid]
        e = run_on[mid].pop(tid)
        ends[e].discard(tid)
        del started_at[tid]
        free[mid][0] += t.cpu
        free[mid][1] += t.mem
        runs[tid].stops.append((now, mid, kind, by))
        log.append((now, tid, kind, mid))
        bisect.insort(queue, key[tid])

    def fits(tid, mid):
        t = T[tid]
        return up[mid] and free[mid][0] >= t.cpu and free[mid][1] >= t.mem

    def can_ever(tid, mid):
        t, m = T[tid], M[mid]
        return up[mid] and m.cpu >= t.cpu and m.mem >= t.mem

    def reservation(tid, now):
        t = T[tid]
        best = None
        for mid in mids:
            if not can_ever(tid, mid):
                continue
            c, m = free[mid]
            when = now
            if not (c >= t.cpu and m >= t.mem):
                when = None
                rel = sorted((e, x) for x, e in run_on[mid].items())
                i = 0
                while i < len(rel):
                    e = rel[i][0]
                    while i < len(rel) and rel[i][0] == e:
                        c += T[rel[i][1]].cpu
                        m += T[rel[i][1]].mem
                        i += 1
                    if c >= t.cpu and m >= t.mem:
                        when = e
                        break
            if when is not None and (best is None or when < best[1]):
                best = [mid, when, c - t.cpu, m - t.mem]
        return best

    def preempt(tid, now):
        t = T[tid]
        for mid in mids:
            if not can_ever(tid, mid):
                continue
            cands = sorted((x for x in run_on[mid] if T[x].priority <= FREE_MAX),
                           key=lambda x: (T[x].priority, -started_at[x], tuple(-ord(ch) for ch in x)))
            c, m = free[mid]
            victims = []
            for x in cands:
                if c >= t.cpu and m >= t.mem:
                    break
                victims.append(x)
                c += T[x].cpu
                m += T[x].mem
            if victims and c >= t.cpu and m >= t.mem:
                return mid, victims
        return None

    def round_(now):
        pending = list(queue)
        resv = None
        i = 0
        while i < len(pending):
            tid = pending[i][2]
            t = T[tid]
            placed = None
            for mid in mids:
                if not fits(tid, mid):
                    continue
                if resv is not None and mid == resv[0]:
                    if now + t.duration <= resv[1]:
                        pass
                    elif t.cpu <= resv[2] and t.mem <= resv[3]:
                        resv[2] -= t.cpu
                        resv[3] -= t.mem
                    else:
                        continue
                placed = mid
                break
            if placed is None and resv is None and t.priority >= PROD_MIN:
                p = preempt(tid, now)
                if p is not None:
                    placed, victims = p
                    for v in victims:
                        stop(v, now, "evict", tid)
                        bisect.insort(pending, key[v])
            if placed is not None:
                queue.remove(pending[i])
                pending.pop(i)
                start(tid, placed, now)
                continue
            if resv is None:
                resv = reservation(tid, now)
            i += 1

    times = sorted(set(subs) | set(downs) | set(backs))
    ti = 0
    while True:
        cand = []
        if ti < len(times):
            cand.append(times[ti])
        live_ends = [e for e, s in ends.items() if s]
        if live_ends:
            cand.append(min(live_ends))
        if not cand:
            break
        now = min(cand)
        if until is not None and now > until:
            break
        if not end_state and now > W:
            end_state = snapshot(W, T, where, started_at, run_on, queue, up, M)
        while ti < len(times) and times[ti] <= now:
            ti += 1
        for tid in sorted(ends.pop(now, set())):
            mid = where.pop(tid)
            del run_on[mid][tid]
            del started_at[tid]
            free[mid][0] += T[tid].cpu
            free[mid][1] += T[tid].mem
            runs[tid].finish = now
            log.append((now, tid, "finish", mid))
        for mid in downs.get(now, []):
            for tid in sorted(run_on[mid]):
                stop(tid, now, "fail")
            up[mid] = False
        for mid in backs.get(now, []):
            up[mid] = True
            free[mid] = [M[mid].cpu, M[mid].mem]
        for tid in sorted(subs.get(now, [])):
            log.append((now, tid, "submit", None))
            bisect.insort(queue, key[tid])
        round_(now)
    if not end_state and (until is None or until >= W):
        end_state = snapshot(W, T, where, started_at, run_on, queue, up, M)
    stuck = [q[2] for q in queue]
    return SimResult(w, T, machines, log, runs, end_state, stuck, until)


def snapshot(W, T, where, started_at, run_on, queue, up, M) -> dict:
    running = {tid: {"machine": mid, "started": started_at[tid], "remaining": run_on[mid][tid] - W}
               for tid, mid in where.items()}
    return {"running": running, "pending": [q[2] for q in queue], "down": [m for m, u in up.items() if not u]}


# ------------------------------------------------------------------ derived facts used by questions and events
def long_waits(res: SimResult, threshold: int, until: int) -> list[tuple[str, int]]:
    """Tasks whose first start came more than `threshold` s after their submission (or that had not started by
    `until` although submitted more than `threshold` s before it), with the wait."""
    out = []
    for tid, r in res.runs.items():
        if r.submit > until:
            continue
        fs = r.first_start
        if fs is not None and fs <= until:
            if fs - r.submit > threshold:
                out.append((tid, fs - r.submit))
        elif until - r.submit > threshold:
            out.append((tid, until - r.submit))
    return sorted(out, key=lambda x: (-x[1], x[0]))


def events(res: SimResult) -> list[tuple[int, int, str]]:
    """The Events section: (time, order, text), time order, events at times 0..W."""
    w = res.window
    W = w.length
    out = []
    for m in res.machines:
        if m.down is not None and m.down <= W:
            hit = sorted(tid for t, tid, ev, mid in res.log if t == m.down and ev == "fail" and mid == m.mid)
            txt = f"machine {m.mid} failed" + (f"; tasks {', '.join(hit)} stopped and went back to the queue"
                                                if len(hit) > 1 else f"; task {hit[0]} stopped and went back to "
                                                "the queue" if hit else "; no task was running on it")
            out.append((m.down, 1, txt))
            if m.back is not None and m.back <= W:
                out.append((m.back, 2, f"machine {m.mid} returned"))
    for t, tid, mid, by in res.evictions(W):
        out.append((t, 3, f"task {by} (priority {res.tasks[by].priority}) evicted task {tid} (priority "
                          f"{res.tasks[tid].priority}) from machine {mid}"))
    for tid, r in res.runs.items():
        if len(r.starts) > 1:
            for t, mid in r.starts[1:]:
                if t <= W:
                    out.append((t, 4, f"task {tid} restarted on machine {mid}"))
    return sorted(out, key=lambda x: (x[0], x[1], x[2]))
