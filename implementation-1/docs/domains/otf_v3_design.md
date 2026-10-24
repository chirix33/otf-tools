# OTF v3: domain-general design (proposal, 2026-10-23)

Status: PROPOSAL awaiting the author's approval. Written by a read-only design agent; key factual claims checked
against the code and runs on 2026-10-23 (nested-JSON bug in `engine._json` reproduced; gpt-oss E1 generation:
documents 1-8 and 14 tried their own generation and only e1_d08 passed, the rest reused e1_d08's model or fell
back; official `otf` E1 = 75.7%, `otf_single` = 71.5%, `otf_oracle` = 77.5%, from `runs/e1_report.md`).

## 0. Decisions on one screen

1. **One abstraction for every document.** Each scope's records split into entities, inputs (given to the
   process from outside), constants (stated numbers), rules (the prose policy, or estimated) and outcomes (what
   the process produces). The process model maps inputs + constants to outcomes. Time is optional: CLEVRER,
   manufacturing and IT are temporal; finance is a timeless computation (derived figures follow from base cells).
2. **What-ifs are edits to inputs or constants, applied by the engine, not the generated code.** One LLM call
   writes a small JSON patch (remove / set / scale / shift / add / change constant); deterministic engine code
   applies it and calls the same `simulate` that passed the check.
3. **Divergence replay, generalised.** Keep the record up to t* = the earlier of (first recorded outcome
   touching the changed thing, first difference between paired factual/patched simulations), simulate only after
   t*. On CLEVRER removals this mostly equals today's rule.
4. **Anti-replay check, generalised.** Hide every outcome, and every timed record after the cut that is not an
   input. Keep inputs (including future ones). The model must forecast what was hidden. Timeless documents hide
   derived figures, which must be recomputed. Two new automatic probes: a replay probe (the model's own outcome
   reader, on the blinded copy, must find almost nothing) and a sensitivity guard (the simulator must react to
   input changes). Bar stays 0.4, pre-registered for every domain.
5. **PDF conversion: no LLM rewrite of content.** Keep the deterministic Navigation Map, add ruled-table
   parsing (pdfplumber `find_tables`) and optionally a relaxed header rule. Meaning (input vs outcome, time
   column) comes from the checked step-1 reading code ("schema induction as code"). CLEVRER maps must stay
   byte-identical.
6. **No new setup LLM calls.** Explanatory gets +1 per-question call (choice -> patch).
7. **v3 is OTF's 3rd and last tuning variant.** After freeze only logged bug fixes.
8. **Biggest risk: generation reliability**, not the design (only 1 of 9 own generations passed on E1 with gpt-oss).

## 1. Abstraction and interfaces

| Part | CLEVRER | Manufacturing | IT ops | Finance |
|---|---|---|---|---|
| entities | objects | products (+ plant) | tasks, jobs, machines | table row labels |
| inputs (kept in the check) | each object's arrival time and first state | daily production, daily orders, opening stock, order-book days | task submissions (priority, requests, run duration), machine capacities, failures, re-adds | base cells as reported |
| constants | estimated inside simulate | plant capacity kg/day | none or cluster size | none |
| rules | estimated from data | written stock/dispatch policy | written placement policy | arithmetic |
| outcomes (hidden in the check) | collisions, exits | stock, shipped, backordered, stock-outs | starts, finishes, evictions, restarts | derived cells (totals, change, %) |
| time | frames | days | seconds | none |

Step 1 (checked before step 2 exists):

```python
def entities(doc, scope) -> [{"id": str, "description": str}]
def recorded_end(doc, scope) -> float | None                      # None: no time
def inputs(doc, scope) -> [{"id", "time": float|None, "kind", "entities": [ids], "fields": {...}, "src": [loc, ...]}]
def outcomes(doc, scope) -> [{"time": float|None, "kind", "entities": [ids], "value": number|None, "src": [loc, ...]}]
def params(doc, scope) -> {name: number}                          # optional
# loc = [node_id, row] | [node_id, row, [cols]] | [node_id, line]
```

Step 2: `simulate(doc, scope, inputs, params, start=None, horizon=None) -> [outcome records]`. It reads exogenous
inputs only from its `inputs` argument; `doc` only for states at or before `start` and calibration from other
scopes; an entity takes part only if it has inputs. New sandbox helper `table_rows(node)`.

## 2. Interventions

Patch language (applied by new `otf/records.py`):

```text
{"op":"remove","select":S} | {"op":"set","select":S,"field":F,"value":V} | {"op":"scale","select":S,"field":F,"factor":X}
{"op":"shift","select":S,"by":D} | {"op":"add","record":{...}} | {"op":"set"|"scale","param":NAME,"value"|"factor":..,"from":T}
S = {"entity": id, "kind"?, "time"?, "from"?, "to"?}
```

A selector matching only outcomes becomes an outcome override (later effects not modelled, said in the evidence);
matching nothing = tool error -> fallback (counted). One PATCH call (replaces ARGS) sees the question, choices,
entity list, one example input per kind, constants and time range. **Fix `engine._json`** (non-greedy regex returns
`{}` on nested JSON; use raw_decode last-object logic as in `clevrer_bench/prompts.py`).

Divergence replay: t_c = earliest time the patch can act; t_r = first recorded outcome at/after t_c touching an
edited entity; t_d = first difference between paired factual/patched runs from t_c.
t* = max(t_c, min(t_r, t_d)); infinite -> trace is the record; else record up to t* - eps + simulate after.
Timeless: full recompute.

## 3. Outcomes and queries

Any number of participants; states and figures are outcome records with values. Evidence: entities, recorded
outcomes, the change in words with t*, the counterfactual run, DIFFERENCES (no longer happens / newly happens /
value changed). Focus filter for long lists (records naming question/choice entities first, cap 150; diff cap 60).
Explanatory adds per-choice but-for checks (CAUSES call: target outcome + a removal patch per choice). Counterfactual
and predictive choices are judged by the answer LLM (no option-to-query language).

## 4. Generalised forecast check

Step-1 checks (4 scopes, 3 tries, frozen before any simulator): functions run; ids consistent; outcome times in
range; outcomes found; `src` valid; no cell both input and outcome; provenance test (`inputs(blinded) == inputs(full)`);
replay probe (`outcomes(blinded)` recovers <= 0.05 record-F1).

Blinding: text nodes emptied; cells/lines referenced by inputs kept; otherwise hidden if referenced by an outcome
after the cut (or untimed), or (timed) the row time is after the cut. Cut = first outcome time - 1% of period.

Scoring: record-F1 per scope (same kind, same entity set, |dt| <= 5% of period, values within 5% of the kind's
range with a 5%-of-|value| floor), mean over the first 6 scopes with hidden outcomes. Sensitivity guard: perturbing
inputs must change simulate's output on at least one checked scope. Bar 0.4 for every domain; report pass rates and
a post-hoc sensitivity table at 0.3/0.5.

Why copying fails: CLEVRER (collision times must come from motion), manufacturing (policy must be run), IT
(placement/waits/evictions computed), finance (totals/changes recomputed from base cells).

Remaining gap: the LLM decides what counts as an input; if it labels outcome data as input every probe passes.
Mitigation: step-1 labelling frozen with no feedback from the forecast check; publish an automatic audit of
input/outcome labelling per model, hand-checked for every generated model (~30-50).

## 5. Map / PDF conversion

Recommendation: hybrid (deterministic map + checked LLM reading code). LLM content rewriting rejected: output-token
cost scales with document length (E2 impractical), sampled and non-deterministic, OTF-only cleaning is a fairness
problem, transcription errors silently corrupt both inputs and the record the check verifies against.
Map fixes: ruled tables via `find_tables()` (must; finance), relaxed header rule (optional, C3), `schema_summary`
cap at 25 shapes, hard gate that all CLEVRER maps are byte-identical.

Benchmark rules implied: finance tables drawn as grids; every exogenous input stated in the document (IT lists run
duration at submission); scopes are level-0 outline entries with child sections; scope title appears exactly in
the question; run folders named `<split>_dNN`.

## 6. Prompts

Describe each function's role (given vs produced), point to the front matter for stated rules, keep useful hints
in generic words (rates that change on their own; states of participants at an outcome; how states change at an
outcome). Rewrite PARSERS_USER, SIMULATOR_USER, EXPLORE_HOWTO, DOC_CONTEXT; PATCH replaces ARGS; new CAUSES;
ANSWER guides updated; ROUTER unchanged. Extend `tests/test_no_benchmark_words.py` with the new domains' vocabulary
(stock, inventory, backorder, dispatch, shipment, warehouse, plant, factory, truck, product, sales, scheduler, evict,
preempt, cluster, cpu, machine, job, queue, priority, revenue, goodwill, impairment, fiscal, dividend).

## 7. Per-type tools

| Type | Tool | Extra calls | CLEVRER change |
|---|---|---|---|
| descriptive | read scope | 0 | none |
| counterfactual | PATCH -> replay -> evidence + DIFFERENCES | 1 (as today) | patch format, t*, diff |
| explanatory | dependency table (removal per entity, <= 12) + CAUSES per-choice but-for | +1 | per-choice checks new |
| predictive | start = recorded_end; horizon = last future input time, else end + 0.5 x period | 0 | identical horizon |

Fallback to reading (reported): failed check, sandbox error, unresolved or empty patch, no scope, predictive/
explanatory on a timeless scope. Ablation switches: reading_only, no_check, no_replay, library off.

## 8. Walk-throughs

See the design agent's report (CLEVRER Video 10017 all four types; manufacturing Plant 2120 Period 02; IT Cell
window 07; finance Report R-031 "impairment in 2019 doubled" -> scale cell x2 -> recompute -> 9,280 = gold; "total
decreased by 20%" falls back because the total is not a cell).

## 9. Regression gates (write into SPEC before running)

- G1: all CLEVRER maps byte-identical (pilot20, E1 x15, E2).
- G2: guard test + toy unit tests (temporal and timeless fixtures: record-F1, blinding, replay probe, every patch op, t*).
- G3: v3 oracle passes the v3 check on pilot20 (report F1 vs 0.644); end to end on all 308 pilot20 questions within
  2 points of the v2 oracle.
- G4: gpt-oss v3 generation passes within budget on pilot20; on all 308 questions v3 >= v2 - 3 points. If it fails:
  bug hunt from logs only (no rewording), then proceed with v3 as pre-registered.
- G5: each new-domain dev document: every table parses as a table, generation runs without crashing (no accuracy looked at).

After freeze: re-run gpt-oss OTF and the v3 oracle on E1 (and E2 if it runs). Report `otf` = v3 (official),
keep `otf_v2` (75.7%) and `otf_single` (71.5%) as ablations; if v3 < v2 report as measured.

## 10. Fairness

v3 = OTF's 3rd and final variant (v1 router V1 single pass; v2 router V2 + library re-check). OTF sees nothing
baselines don't; map shared and identical on CLEVRER; `table_rows` not advertised to ReAct-C. Calls per question:
descriptive 2, counterfactual 3, explanatory 3, predictive 2; no new setup calls; 12-call cap does not bind.

## 11. Implementation plan (~17 h + GPU gate)

| # | Change | Files | h |
|---|---|---|---|
| 1 | record utilities + toy tests | new `otf/records.py`, `tests/test_records.py` | 3.5 |
| 2 | sandbox helpers | `otf/sandbox.py` | 0.25 |
| 3 | step-1/step-2 checks | `otf/toolgen.py` | 3 |
| 4 | prompts | `otf/prompts.py` | 2 |
| 5 | engine (incl. `_json` fix, ablation flags) | `otf/engine.py` | 3 |
| 6 | oracle port + offline engine test | `oracle/oracle_model.py` (keep v2 copy) | 1 |
| 7 | map: ruled tables, shape cap, identity gate | `otf/navmap.py`, `scripts/check_navmap_identity.py` | 2.5 |
| 8 | library signature + `otf_library_v3` + system args | `otf/library.py`, `otf_system.py`, `scripts/otf_library_pass.py` | 0.75 |
| 9 | guard extension | `tests/test_no_benchmark_words.py` | 0.25 |
| 10 | SPEC section 5 (v3), variant log, gates | `SPEC.md` | 0.5 |
| 11 | GPU gate G3-G4 on gpt-oss (~2-2.5 GPU-h) | - | 2.5 wall |

Cut lines, in order: C1 per-choice CAUSES; C2 focus filter + DIFFERENCES; C3 relaxed header rule; C4 library
signature tweak; C5 paired t_d runs; C6 new-domain oracle models. Never cut item 3 (the check).
Minimum viable: items 1-6, 7 (ruled tables + identity gate), 9, 10.

## 12. Risks and open questions

Risks: generation reliability (zero passing models per domain is possible with ~3 documents); "the LLM decides what
is hidden"; "0.4 is a CLEVRER number"; "finance is just program-of-thought"; CLEVRER regression; compute; the domain
benchmarks themselves are the critical path. Unsure: `find_tables()` empty on all CLEVRER pages (G1 checks);
IT simulation time within the 20 s sandbox; `_scope_of` exact match on titles like "Plant 2120, Period 03".

Open questions: (1) v3 as final variant with bug-fix-only rule and "proceed after bug hunt" G4 rule? (2) report v2
E1 as an ablation row? (3) documents per new domain (3 vs ~5 smaller) and generation budget? (4) which models run the
new domains? (5) do the new baselines run on the new domains? (6) include per-choice explanatory checks (C1)?
(7) require run duration at submission in IT documents?
