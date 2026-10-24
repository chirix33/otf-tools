"""Load the real Google cluster trace records (clusterdata-2011-2, CC-BY 4.0; Reiss, Wilkes, Hellerstein 2011).

Raw data: data/domains/raw/google-trace-2011/ (files named <table>_part-NNNNN-of-NNNNN.csv.gz, checked against
the bucket's SHA256SUM by `verify()`). Tables used: job_events, task_events, machine_events.

Windows are taken from four pairs of consecutive task_events / job_events parts (SLICE_PARTS), well after the
trace start (part 0 lists everything already running at once). A part covers about 5,010 s of trace time. For
each pair, tasks are taken from jobs submitted during the first part; the second part is there so that their
FINISH events are seen (a task submitted at the end of the first part still has ~5,000 s to finish).

Decisions (also in docs/domains/it_operations.md, "As built"):
- A task is used only if, in the pair, its first event is a SUBMIT, it is then scheduled, and the first
  terminating event after its first SCHEDULE is a FINISH (not EVICT, FAIL, KILL or LOST). Its run duration is
  FINISH time - SCHEDULE time, rounded to whole seconds (at least 1 s). Its priority and CPU / memory requests
  are the values on that SCHEDULE row; tasks with a zero or missing CPU or memory request are left out.
- Its job must have a SUBMIT row in job_events inside the first part of the pair.
- CPU and memory are normalised in the trace (largest machine = 1). They are converted to whole units of
  1/UNIT, rounded half-up; the rounded values are the ones used everywhere.
- Machines: capacities from machine_events ADD / UPDATE rows; a REMOVE is a failure, the machine's next ADD is
  its return.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "domains" / "raw" / "google-trace-2011"
SLICE_PARTS = ((120, 121), (240, 241), (360, 361), (470, 471))
UNIT = 100_000                   # 1 CPU or memory unit = 1/100000 of the largest machine in the cell
US = 1_000_000                   # trace times are in microseconds
# task_events event types
SUBMIT, SCHEDULE, EVICT, FAIL, FINISH, KILL, LOST = 0, 1, 2, 3, 4, 5, 6
TERMINAL = {EVICT, FAIL, FINISH, KILL, LOST}
RUN_ENDS = {FINISH}              # only a FINISH ends a usable run (spec: run time = SCHEDULE to FINISH)
# machine_events event types
M_ADD, M_REMOVE, M_UPDATE = 0, 1, 2


def part_file(table: str, part: int) -> Path:
    n = 1 if table == "machine_events" else 500
    return RAW / f"{table}_part-{part:05d}-of-{n:05d}.csv.gz"


def units(x: str) -> int:
    return int(float(x) * UNIT + 0.5) if x else 0


def verify() -> list[str]:
    """Check every file used against the bucket's SHA256SUM. Returns the problems (empty = all good)."""
    want = {}
    for ln in (RAW / "SHA256SUM").read_text().splitlines():
        h, name = ln.split(" *")
        want[name.replace("/", "_")] = h
    files = [part_file("machine_events", 0)] + [part_file(t, p) for pair in SLICE_PARTS for p in pair
                                                 for t in ("task_events", "job_events")]
    out = []
    for f in files:
        if not f.exists():
            out.append(f"missing {f.name}")
        elif hashlib.sha256(f.read_bytes()).hexdigest() != want.get(f.name):
            out.append(f"checksum mismatch {f.name}")
    return out


@dataclass(frozen=True)
class TraceTask:
    job: int
    index: int
    submit_us: int
    priority: int
    cpu: int                     # units
    mem: int                     # units
    duration: int                # seconds, SCHEDULE to FINISH


@dataclass
class Slice:
    parts: tuple[int, int]
    start_us: int                # first event of the first part
    sub_end_us: int              # last event of the first part (end of the submission period)
    obs_end_us: int              # last event of the second part
    job_submit_us: dict[int, int] = field(default_factory=dict)
    tasks: dict[int, list[TraceTask]] = field(default_factory=dict)      # job -> eligible tasks (by index)


@dataclass
class MachineHistory:
    mid: int
    events: list[tuple[int, int, int, int]]   # (time_us, type, cpu units, mem units), time order

    def capacity_at(self, t_us: int) -> tuple[int, int] | None:
        """Capacity (cpu, mem) if the machine is in the cell at t_us, else None."""
        cap = None
        for t, typ, c, m in self.events:
            if t > t_us:
                break
            if typ == M_REMOVE:
                cap = None
            elif c and m:
                cap = (c, m)
        return cap

    def outages(self, a_us: int, b_us: int) -> list[tuple[int, int | None]]:
        """REMOVE events in [a_us, b_us), each with the time of the machine's next ADD (None if never)."""
        out = []
        for i, (t, typ, _, _) in enumerate(self.events):
            if typ == M_REMOVE and a_us <= t < b_us:
                back = next((t2 for t2, typ2, _, _ in self.events[i + 1:] if typ2 == M_ADD), None)
                out.append((t, back))
        return out


def load_machines() -> dict[int, MachineHistory]:
    ev = defaultdict(list)
    with gzip.open(part_file("machine_events", 0), "rt") as fh:
        for r in csv.reader(fh):
            ev[int(r[1])].append((int(r[0]), int(r[2]), units(r[4]), units(r[5])))
    return {m: MachineHistory(m, sorted(e)) for m, e in ev.items()}


def load_slice(parts: tuple[int, int]) -> Slice:
    rows = defaultdict(list)
    bounds = []
    for p in parts:
        lo = hi = None
        with gzip.open(part_file("task_events", p), "rt") as fh:
            for r in csv.reader(fh):
                t = int(r[0])
                lo = t if lo is None else min(lo, t)
                hi = t if hi is None else max(hi, t)
                rows[(int(r[2]), int(r[3]))].append((t, int(r[5]), r[8], r[9], r[10]))
        bounds.append((lo, hi))
    sl = Slice(parts, bounds[0][0], bounds[0][1], bounds[1][1])
    for p in parts:
        with gzip.open(part_file("job_events", p), "rt") as fh:
            for r in csv.reader(fh):
                t, job, typ = int(r[0]), int(r[2]), int(r[3])
                if typ == SUBMIT and sl.start_us <= t <= sl.sub_end_us and job not in sl.job_submit_us:
                    sl.job_submit_us[job] = t
    for (job, idx), es in rows.items():
        if job not in sl.job_submit_us:
            continue
        es.sort(key=lambda e: e[0])          # stable: same-time rows keep file order
        if es[0][1] != SUBMIT:
            continue
        i = next((k for k, e in enumerate(es) if e[1] == SCHEDULE), None)
        if i is None:
            continue
        end = next((e for e in es[i + 1:] if e[1] in TERMINAL), None)
        if end is None or end[1] not in RUN_ENDS:
            continue
        _, _, pri, cpu, mem = es[i]
        c, m = units(cpu), units(mem)
        if not pri or c <= 0 or m <= 0:
            continue
        dur = max(1, int((end[0] - es[i][0]) / US + 0.5))
        sl.tasks.setdefault(job, []).append(TraceTask(job, idx, es[0][0], int(pri), c, m, dur))
    for job in sl.tasks:
        sl.tasks[job].sort(key=lambda x: x.index)
    return sl


def load_all() -> tuple[list[Slice], dict[int, MachineHistory]]:
    return [load_slice(p) for p in SLICE_PARTS], load_machines()
