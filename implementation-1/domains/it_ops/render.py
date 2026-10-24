"""Render IT operations windows into a text-based PDF (same approach as domains/manufacturing/render.py).

Front matter: what the records are, the scheduling policy in prose, the cluster and subsampling rule, units.
Each scope ("Cell window <NN>") is a level-0 outline entry with four level-1 sections: Machines, Task log,
Events, Queue at window end. Tables are ruled grids; every cell is a single word so a table row reads back as
one line of tokens.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .data import UNIT
from .scopes import (CAPACITY_DIVISOR, FREE_SHARE, LOAD_MAX, LOAD_TARGET, N_MACHINES, PROD_JOBS, RETURN_HORIZON,
                     TASKS_PER_FREE_JOB, TASKS_PER_JOB, WINDOW_S)
from .sim import SimResult, Window, events

DOC_TITLE = "Compute Cell Scheduling Records"
N_LONGEST = 5


@dataclass
class ScopeSection:
    window: Window
    start_page: int = 0
    end_page: int = 0

    @property
    def title(self) -> str:
        return self.window.title


@dataclass
class RenderedDoc:
    pdf_path: Path
    sections: list[ScopeSection] = field(default_factory=list)

    def manifest(self) -> dict:
        scopes = [{"title": s.title, "window": s.window.number, "length_s": s.window.length,
                   "n_machines": len(s.window.machines), "n_tasks": len(s.window.tasks),
                   "start_page": s.start_page, "end_page": s.end_page} for s in self.sections]
        # "videos" mirrors the CLEVRER manifest shape the shared report code reads (scene_index = scope title)
        return {"pdf": str(self.pdf_path), "domain": "it_ops", "scopes": scopes,
                "videos": [{"scene_index": s.title, "title": s.title, "start_page": s.start_page,
                            "end_page": s.end_page} for s in self.sections]}


def intro() -> list[str]:
    W = WINDOW_S
    return [
        "This document records how tasks were scheduled on small compute clusters. The workload and the machine "
        "failures are real records from a production compute cell of about 12,500 machines (the Google cluster "
        "trace of May 2011, clusterdata-2011-2, CC-BY 4.0): every task's submission time, job, priority, CPU and "
        "memory request and run time, and every machine's capacity, failure time and return time, are taken from "
        "that trace (ids are renamed). Where and when each task ran in the small cluster is not recorded in the "
        "trace: it is computed from those records by the scheduling policy stated below, applied exactly.",
        f"The document is divided into chapters titled 'Cell window &lt;NN&gt;'. Each chapter is an independent "
        f"run of one small cluster over a window of {W} seconds. Questions refer to a chapter by that title. "
        f"Times are whole seconds from the start of the window (time 0); the window covers times 0 to {W}.",
        "Each chapter has four sections. 'Machines' lists the cluster's machines with their CPU and memory "
        "capacity, the time a machine failed (if it did) and the time it returned (if it did). 'Task log' lists, in "
        "time order, every event of every task from time 0 to the window end: submit, start, finish, evict and "
        "fail, with the task's job, priority, CPU and memory request, run time, and the machine involved. 'Events' "
        "lists machine failures and returns, evictions and restarts, and the longest waits. 'Queue at window end' "
        f"gives the state after the events at time {W}: the tasks still running (with their remaining run time) "
        "and the tasks still waiting, in queue order.",
        "<b>Tasks.</b> A task belongs to a job and has a priority from 0 to 11 (higher is more important). "
        "Priorities 9 to 11 are the <i>production</i> tier and priorities 0 and 1 the <i>free</i> tier. Each task "
        "requests an amount of CPU and of memory, which it holds on one machine while it runs, and has a run time: "
        "once started it runs for exactly that many seconds and then finishes, unless it is stopped first. The run "
        "time is given on every row of the task log, starting with the task's submit row.",
        "<b>Scheduling policy.</b> Every window starts with all machines empty and no task waiting. At every time "
        "at which something happens, in this order:",
        "1. <b>Finishes.</b> Tasks whose run time is over finish and free their CPU and memory.",
        "2. <b>Failures.</b> Machines that fail at this time go down. Each task running on such a machine stops "
        "(a <i>fail</i> event) and goes back to the queue.",
        "3. <b>Returns.</b> Machines that return at this time come back, empty, with their capacity.",
        "4. <b>Submissions.</b> Tasks submitted at this time join the queue.",
        "5. <b>Scheduling round.</b> The waiting tasks are taken one at a time in <i>queue order</i>: higher "
        "priority first, then earlier submission time, then lower task id. Each task, in turn:",
        "a. <b>First fit.</b> The task starts on the first machine, in machine id order, that is up and whose "
        "free CPU and free memory are both at least the task's requests (subject to the reservation rule in c).",
        "b. <b>Preemption.</b> If it fits nowhere, no task holds a reservation yet in this round, and it is a "
        "production task, it may evict free-tier tasks from one machine. It looks at the up machines in id order. "
        "On each it considers the free-tier tasks running there, lowest priority first, then the most recently "
        "started first (then the higher task id first), and evicts them one by one in that order until it fits; "
        "it takes the first machine where this works, evicting only as many as needed there, and starts on it. "
        "If no machine works, nothing is evicted. An evicted task goes back to the queue at once (it may start "
        "again later in the same round); it loses its progress and will run its full run time again.",
        "c. <b>Reservation and backfilling.</b> The first task in the round that can start neither by a. nor by b. "
        "gets a <i>reservation</i>: the earliest time at which it could start, computed from the run times of the "
        "tasks now running (assuming no new submissions, failures or returns), on the first machine, in id order, "
        "where that earliest time is reached. Every later task in the round may still start by first fit, but "
        "on the reserved machine only if it will finish no later than the reserved time, or if its requests fit "
        "in what the reserved machine will still have free at the reserved time after the reserved task's "
        "requests (and after other such starts on it in the same round). On the other machines it starts as "
        "usual. Later tasks do not preempt. A task that would not fit on any up machine even if that machine "
        "were empty gets no reservation and simply keeps waiting; the next task that cannot start may then get "
        "the reservation.",
        "Tasks stopped by an eviction or a failure keep their original submission time (and so their place in "
        "queue order) and start again from the beginning. A task never moves while it runs.",
        "<b>Order of rows.</b> Task log rows with the same time follow the steps above: finishes (by task id), "
        "failures (by machine, then task id), submissions (by task id), then the scheduling round's starts and "
        "evictions in the order the round makes them (each eviction just before the start that caused it).",
        "<b>Terms used in the Events section and in questions.</b> A task's <i>wait</i> is the time from its "
        "submission to its first start. A task is <i>restarted</i> when it starts again after an eviction or a "
        "failure. The number of <i>evictions</i> counts evict events (one per evicted task). 'Running on a "
        "machine at time t' means running after all the events at time t.",
        f"<b>The cluster and the workload.</b> Each window has {N_MACHINES} machines, ids M01 to M{N_MACHINES:02d}. "
        f"Each is modelled on a real machine of the cell (one of them is a machine that failed during the window "
        f"in the trace) and has 1/{CAPACITY_DIVISOR} of that machine's recorded CPU and memory capacity. A failed "
        f"machine returns at the time the trace records it coming back, if that is within {RETURN_HORIZON // 3600} "
        "hours; otherwise it does not return. The tasks are a sample of the real tasks submitted in the cell during "
        "the window, chosen by this fixed rule: jobs submitted in the window are taken in a random order, first "
        f"up to {PROD_JOBS} production jobs, then free-tier jobs until the offered load reaches "
        f"{FREE_SHARE * LOAD_TARGET:.0%}, then other jobs until it reaches {LOAD_TARGET:.0%} (a job that would push "
        f"it above {LOAD_MAX:.0%} is skipped). A job contributes its first {TASKS_PER_JOB} tasks "
        f"({TASKS_PER_FREE_JOB} for a free-tier job) that finished normally in the trace and fit on at least one "
        "machine of the window. Offered load = the larger, over CPU and memory, of the sum of request x run time "
        "inside the window over all tasks, divided by the cluster's total capacity x the window length.",
        f"<b>After the window.</b> For questions about what happens after time {W}: no new task is submitted and "
        "no machine fails after the window; a machine that is down returns at its listed return time (if any); "
        "the policy continues unchanged from the state given in 'Queue at window end'.",
        f"<b>Units.</b> Times and run times in seconds. CPU and memory in units of 1/{UNIT:,} of the largest "
        "machine in the original cell (the trace's normalised values, rounded to whole units).",
    ]


def _grid(data: list[list[str]], widths: list[float]) -> Table:
    t = Table(data, repeatRows=1, colWidths=[w * inch for w in widths])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t


def longest_waits(res: SimResult, n: int = N_LONGEST) -> list[tuple[str, int, int, int]]:
    """(task, wait, submitted, first start) for tasks first started by the window end, longest first."""
    W = res.window.length
    rows = [(tid, r.first_start - r.submit, r.submit, r.first_start) for tid, r in res.runs.items()
            if r.first_start is not None and r.first_start <= W and r.first_start > r.submit]
    return sorted(rows, key=lambda x: (-x[1], x[0]))[:n]


def queue_rows(res: SimResult) -> tuple[list[list[str]], list[list[str]]]:
    es = res.end_state
    T = res.tasks
    running = [[tid, T[tid].job, str(T[tid].priority), str(T[tid].cpu), str(T[tid].mem), x["machine"],
                str(x["started"]), str(x["remaining"])]
               for tid, x in sorted(es["running"].items(), key=lambda kv: (kv[1]["machine"], kv[0]))]
    pending = [[tid, T[tid].job, str(T[tid].priority), str(T[tid].cpu), str(T[tid].mem), str(T[tid].submit),
                str(T[tid].duration)] for tid in es["pending"]]
    return running, pending


def build_pdf(runs: list[tuple[Window, SimResult]], pdf_path: Path, doc_label: str) -> RenderedDoc:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    h1, h2, body = styles["Heading1"], styles["Heading2"], styles["BodyText"]
    sections = [ScopeSection(w) for w, _ in runs]
    doc = RenderedDoc(pdf_path, sections)
    by_key: dict[str, ScopeSection] = {}

    class Doc(SimpleDocTemplate):
        def afterFlowable(self, fl):
            info = getattr(fl, "_outline", None)
            if info:
                key, title, level = info
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(title, key, level=level)
                if level == 0 and key in by_key:
                    by_key[key].start_page = self.page

    def heading(text, style, key, level):
        p = Paragraph(text, style)
        p._outline = (key, text, level)
        return p

    story = [heading(DOC_TITLE, styles["Title"], "intro", 0)]
    story += [Paragraph(t, body) for t in intro()]
    story.append(Paragraph(f"Chapters in this document ({doc_label}): " +
                           ", ".join(s.title for s in sections) + ".", body))
    for sec, (w, res) in zip(sections, runs):
        key = f"w{w.number:02d}"
        by_key[key] = sec
        T, W = w.title, w.length
        story += [PageBreak(), heading(T, h1, key, 0),
                  Paragraph(f"Times 0 to {W}. The cluster has {len(w.machines)} machines. "
                            f"{len(w.tasks)} tasks of {len({t.job for t in w.tasks})} jobs are submitted during "
                            "the window.", body)]
        # Machines
        story.append(heading(f"{T}: Machines", h2, key + "m", 1))
        rows = [["machine", "CPU", "memory", "fails at", "returns at"]]
        for m in w.machines:
            rows.append([m.mid, str(m.cpu), str(m.mem), "-" if m.down is None else str(m.down),
                         "-" if m.down is None else ("never" if m.back is None else str(m.back))])
        story += [Spacer(1, 4), _grid(rows, [0.8, 0.8, 0.8, 0.8, 0.8])]
        # Task log
        story.append(heading(f"{T}: Task log", h2, key + "l", 1))
        rows = [["time", "task", "job", "priority", "CPU", "memory", "run time", "event", "machine"]]
        for t, tid, ev, mid in res.log:
            if t > W:
                break
            x = res.tasks[tid]
            rows.append([str(t), tid, x.job, str(x.priority), str(x.cpu), str(x.mem), str(x.duration), ev,
                         mid or "-"])
        story += [Spacer(1, 4), _grid(rows, [0.55, 0.55, 0.5, 0.6, 0.6, 0.65, 0.65, 0.6, 0.65])]
        # Events
        story.append(heading(f"{T}: Events", h2, key + "e", 1))
        ev = events(res)
        if not ev:
            story.append(Paragraph("No machine failures, evictions or restarts in this window.", body))
        story += [Paragraph(f"Time {t}: {txt}.", body) for t, _, txt in ev]
        lw = longest_waits(res)
        if lw:
            story.append(Paragraph("Longest waits (submission to first start, tasks started by the window end): " +
                                   "; ".join(f"task {tid} waited {d} s (submitted at {s}, first started at {f})"
                                             for tid, d, s, f in lw) + ".", body))
        else:
            story.append(Paragraph("Every task started at its submission time.", body))
        # Queue at window end
        story.append(heading(f"{T}: Queue at window end", h2, key + "q", 1))
        running, pending = queue_rows(res)
        story.append(Paragraph(f"State after the events at time {W}.", body))
        if running:
            story += [Paragraph(f"Tasks running at time {W} (remaining run time = seconds still to run after "
                                f"time {W}):", body), Spacer(1, 4),
                      _grid([["task", "job", "priority", "CPU", "memory", "machine", "started", "remaining"]] +
                            running, [0.55, 0.5, 0.6, 0.6, 0.65, 0.65, 0.6, 0.7]), Spacer(1, 6)]
        else:
            story.append(Paragraph(f"No task is running at time {W}.", body))
        if pending:
            story += [Paragraph(f"Tasks waiting at time {W}, in queue order (each will run its full run time "
                                "once started):", body), Spacer(1, 4),
                      _grid([["task", "job", "priority", "CPU", "memory", "submitted", "run time"]] + pending,
                            [0.55, 0.5, 0.6, 0.6, 0.65, 0.75, 0.7]), Spacer(1, 6)]
        else:
            story.append(Paragraph(f"No task is waiting at time {W}.", body))
        down = [w.machine(m) for m in res.end_state["down"]]
        if down:
            story += [Paragraph(f"Machine {m.mid} is down at time {W}; " +
                                ("it does not return." if m.back is None else f"it returns at time {m.back}.")
                                , body) for m in down]
        else:
            story.append(Paragraph(f"All machines are up at time {W}.", body))

    d = Doc(str(pdf_path), pagesize=letter, title=DOC_TITLE,
            leftMargin=0.7 * inch, rightMargin=0.7 * inch, topMargin=0.7 * inch, bottomMargin=0.7 * inch)
    d.build(story)
    total = d.page
    for i, sec in enumerate(sections):
        sec.end_page = sections[i + 1].start_page - 1 if i + 1 < len(sections) else total
    return doc


def save_manifest(doc: RenderedDoc, path: Path) -> None:
    path.write_text(json.dumps(doc.manifest(), indent=2))
