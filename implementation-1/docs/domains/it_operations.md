# Domain spec: IT operations (Google cluster trace 2011)

Status: DRAFT 2026-10-23. Paper name: "IT operations".

## Source

Google `clusterdata-2011-2` (Reiss, Wilkes, Hellerstein), CC-BY 4.0: 29 days of a ~12.5k-machine Borg cell,
May 2011. Public bucket `storage.googleapis.com/clusterdata-2011-2`, no account needed (the 2019 trace is
BigQuery-only, so it is not used). Tables used: `job_events`, `task_events`, `machine_events` (500 + 500 + 1 parts;
downloaded so far: part 0 of each, checksums verified). Priorities 0-11 (0-1 free, 9-11 production).

Part 0 starts at the trace start, when everything already running is listed at once; windows are taken from later
parts (steady state). Pick 2-4 later parts for the windows.

## What is real and what is simulated

- **Real (exogenous):** task submit times, job/task ids (renamed to short ids), priority, CPU and memory requests
  (normalised, as in the trace), each task's run duration (its recorded SCHEDULE to FINISH time), and machine
  failure/removal times and capacities (from `machine_events`).
- **Simulated (endogenous):** a small cluster (8-16 machines whose capacities are sampled from real machines),
  where and when each task runs, waiting, preemption and restarts, by the written policy below.
- Tasks are subsampled from a real time window so the small cluster runs at ~85-95% load (queueing and
  preemption happen, but not permanent overload). The subsampling rule is fixed and written in the front matter.

Paper wording: "real workload and failure trace; simulated scheduler".

## The policy (front matter, in prose)

1. Pending tasks are ordered by priority (higher first), then submit time, then task id.
2. **Placement**: first fit, machines in id order; a task fits if its CPU and memory requests fit the machine's
   free capacity.
3. **Backfilling**: if the head task does not fit anywhere, later tasks that fit may start, but only if they do
   not delay the head task (its earliest possible start is computed from recorded run durations).
4. **Preemption**: a production task (priority 9-11) that cannot be placed may evict free-tier tasks (0-1) from
   one machine, lowest priority first, then youngest first; evicted tasks return to the queue and restart from
   the beginning.
5. **Machine failure**: tasks on a failed machine return to the queue (restart); the machine comes back at its
   recorded re-add time, if any.
6. A task runs for exactly its recorded duration once started.

## Document layout

- Front matter: the records, the policy, the cluster, the subsampling rule, time unit (seconds from window start).
- One **scope** per window (e.g. 6 hours), titled `Cell window 07` (named in every question). Sections:
  - **Machines** (table: id, CPU capacity, memory capacity)
  - **Task log** (table: time, task, job, priority, CPU, memory, event = submit/start/finish/evict/fail, machine)
  - **Events** (list: preemptions, failures, task restarts, longest waits)
  - **Queue at window end** (table: pending and running tasks with their remaining run time). Makes predictive
    questions answerable.
- 3 test documents (~15 windows each) + 1 dev document.

## Question templates and gold

Gold from the reference scheduler (`domains/it_ops/sim.py`, independent of `otf/`).

- **Descriptive**: on which machine did task T first start; how many tasks were evicted in the window; how long
  did task T wait before its first start.
- **Explanatory** (MC, multi-correct): "Why was task T evicted at time t?" / "Why did task T wait more than
  10 minutes?" Candidates: production task P needed its machine; machine M failed; tasks of job J held the
  capacity; T's memory request did not fit any machine. Correct iff removing that cause removes the outcome.
- **Predictive**: from the end-of-window queue, "Which pending task will start next?", "Will task T finish
  before time t?", "Which machine will task T start on?" Gold: run the scheduler forward with the listed tasks.
- **Counterfactual** (MC, multi-correct), interventions mixed roughly equally:
  - removal: "If job J had not been submitted ..."
  - failure removed: "If machine M had not failed at time t ..."
  - changed value: "If task T's priority had been 9 ..." / "If task T had requested half the memory ..."
  - capacity: "If the cluster had one machine fewer ..."
  Gold: re-run the window from its start with the change, all real inputs as recorded.

## Size and checks

~300 test questions (~75 per type), dev ~40. Checks: re-run reproduces the task log exactly; capacity is never
exceeded; every task finishes or is still listed in the end queue; 20 hand-checked questions.

## Open items

- Which trace parts and window length (target: each window has at least 2 evictions and 1 failure or long wait).
- Machine count and load target, chosen once by these targets before any system runs.

Both open items are settled in "As built" below.

## As built (2026-10-23)

Rebuild: `python -m domains.it_ops.build` then `python -m domains.it_ops.validate` (from `implementation-1/`,
project Python; needs reportlab and pypdfium2, no LLM, no GPU). Deterministic (seed 2027); build ~11 s,
validation ~13 s. Code: `domains/it_ops/` (data, sim, scopes, render, questions, build, validate). Report:
`domains/it_ops/VALIDATION.md` (PASS: every gold label re-derived from the PDF by a second, separately
written scheduler).

**Output.** `runs/itops_d01..itops_d05` (test: 6, 5, 5, 5, 5 windows; 44-54 pages; 60 questions each, 15 per
type; 300 total, 75 per type) and `runs/itops_dev` (4 windows, 40 questions, smoke tests only). Same harness
files as `runs/mfg_*` (document.pdf, items.jsonl, items_all.jsonl, questions.jsonl, gold.jsonl,
gold_meta.jsonl, manifest.json, build_config.json). `gold_meta.jsonl` holds the interventions behind the gold
labels: never give it to a system. `build_config.json` keeps the provenance of each window (trace parts, real
start time, real machine ids, real removal).

**Data decisions**

- **Trace parts: 8 later parts, not 2-4.** task_events and job_events parts 120-121, 240-241, 360-361 and
  470-471 (about days 7, 14, 21 and 27), all checked against the bucket's SHA256SUM. Reason: production tasks
  (priority 9-11) that end with a FINISH are scarce, about 30 per part, and with 4 parts most windows had no
  eviction at all. Each pair is a "slice": tasks come from jobs submitted during its first part (~5,010 s); the
  second part is there so their FINISH is seen.
- **Run time** = FINISH time - first SCHEDULE time, whole seconds, as the spec says. A task is used only if its
  first event in the slice is a SUBMIT and the first terminating event after its first SCHEDULE is a FINISH
  (EVICT, FAIL, KILL or LOST: left out). Priority and requests are those on the SCHEDULE row; tasks with a zero
  or missing request are left out. Because the FINISH must fall within the slice, run times are effectively
  capped at about 5,000 s (bias toward shorter tasks; the 99th percentile of run times is ~5,500-7,000 s).
- **Units.** CPU and memory in whole units of 1/100,000 of the largest machine (the trace's normalised values,
  rounded half-up). Times in whole seconds from the window start.

**Cluster and windows** (chosen by a parameter sweep against the spec's targets, before any question was
generated; scopes.py has the full rule)

- **Machine capacity is 1/8 of the real machine's recorded capacity.** At full size a real machine holds
  dozens of tasks, so a readable window (a few pages of task log) could not show queueing or evictions; at
  1/8 a machine holds a few tasks. The ratios between machine types stay real.
- **8 machines per window** (lower end of the spec's 8-16; 10 machines gave longer documents and no more
  windows meeting the targets).
- **20-minute windows (1,200 s)**, not 6 hours. Real run times are mostly 2-15 minutes, so 20 minutes already
  shows several generations of tasks; longer windows made documents too long (300-500 tasks per window).
- **Exactly one failure per window.** Each candidate window is built around one real machine REMOVE in its
  slice: that machine is one of the 8, fails at its real removal time and returns at its real next ADD time
  (if within 6 hours, otherwise "never"). The other 7 machines are drawn from real machines with no REMOVE in
  the window. In the real cell (8,957 REMOVE events over 29 days for ~12,500 machines) a random 8-machine cluster would see
  a failure in about 0.3% of 20-minute windows, so failures are far more frequent here than in the real cell.
- **Workload subsampling rule** (also printed in the front matter): jobs submitted in the window, in random
  order: up to 6 production jobs; free-tier jobs until offered load reaches 54% (0.6 x 90%); then the other
  jobs until it reaches 90%; a job that would push it above 95% is skipped. A job contributes its first 4
  eligible tasks (16 for a free-tier job) that fit some machine. Free-tier work is heavily over-represented
  compared with the real cell, so that production tasks find something to evict.
- **Windows may share jobs.** Windows from the same slice overlap in time, and each is its own random sample
  of the cell's workload, so two windows can contain the same real job. Requiring disjoint jobs ran the
  free-tier pool dry and kept only 10-19 windows in the sweep. Real machines are never reused across kept windows.
- **30 of 40 candidate windows kept.** Kept if at least 2 evictions, at least one failure or one wait over
  300 s, and offered load at least 85%. All 30 are used: 4 dev, 26 test, split by a seeded shuffle.
- **Long wait = 5 minutes (300 s)**, not 10 minutes, to suit 20-minute windows (explanatory "why did T wait"
  questions and the long_wait counterfactual statement).

**Policy** exactly as the spec's six rules, made precise in the front matter: events at one time are taken in
the order finishes, failures, returns, submissions, then one scheduling round; only the first task blocked in
a round gets a reservation (EASY backfilling, one reservation); only tasks before that reservation may preempt;
evicted tasks rejoin the queue at once with their original submit time; the cluster starts empty. After the
window (predictive questions): no new submissions, no new failures, down machines return as listed. The
validation report shows every rule changes the outcome in 7-26 of the 26 test windows when broken.

**Questions**

- Descriptive (6 templates, ~12 each): first machine of a task, evictions in the window, a task's wait, finish
  time, number of starts, tasks running on a machine at a time.
- Explanatory (eviction cause 38, wait cause 37): candidates are real conditions (a task or job was submitted,
  the machine failure, the task's own memory / CPU request); correct iff the but-for run removes the outcome
  ("not evicted at time t" / "started within 300 s"). Each cause kind is kept near half true.
- Predictive (will_happen, next_start, start_machine, 25 each), from the end-of-window queue.
- Counterfactual: 15 each of remove a job, remove the failure, change a priority (to 9, or to 0 for production
  tasks), halve a CPU or memory request, one machine fewer (a named machine left out). Statements about first
  start time and machine, eviction, finishing by the window end, long waits, eviction count.
- True share: explanatory 0.51, counterfactual 0.51, predictive 0.36 (next_start and start_machine are one
  right answer out of four by format). No constant-answer template. "Copy the recorded outcome" scores 0.00
  question accuracy on counterfactuals.

**Reviewer pushback to expect**

- Capacity scaled to 1/8, failures selected (one per window) and free-tier load over-represented: the
  workload values are real, but the mix and failure rate are not the cell's. Wording: "real task and failure
  records; small simulated cluster; sampling rule stated".
- Windows were kept by outcome targets (30 of 40), and windows can share real jobs.
- FINISH-only run times bias toward short, well-behaved tasks.
- The cluster starts empty in each window, so the first minutes are lightly loaded.
