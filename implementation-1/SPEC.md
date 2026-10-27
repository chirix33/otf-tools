# Frozen spec for the final experiments

Status: **FROZEN** = decided, change only with a written reason here. **OPEN** = waiting on a decision.
Drafted 2026-10-21. Internal deadline for all numbers + paper: **2026-10-28** (submission 2026-10-30 2PM CDT).

## 1. Hardware and serving

| Item | Decision | Status |
|---|---|---|
| GPU | 1x RTX 5090, 32 GB VRAM (≈30 GB usable; Windows display holds ~2 GB). Host: 64 GB RAM, Core Ultra 9 285K. | FROZEN |
| Server | vLLM ≥ 0.19 inside WSL2 Ubuntu-24.04 (venv `~/venvs/vllm`), OpenAI-compatible endpoint on `localhost:8000`. One model on the GPU at a time. Exact flags: `scripts/serve.sh`. Model aliases, sampling settings and endpoints: `configs/models.json`. | FROZEN |
| Kernel autotune | `--no-enable-flashinfer-autotune` for every model (2026-10-22): FlashInfer autotuning made Gemma's startup exceed the orchestrator's 30-min limit (`server_failed` at 15:54). It affects only kernel selection speed, not outputs. | FROZEN |
| Endpoint config | Every system reads `base_url` + `model` from the run config; no system hard-codes OpenAI. | FROZEN |

## 2. Models

| Model | Weights | Fits in 32 GB? | Settings | Status |
|---|---|---|---|---|
| gpt-oss-20b | `openai/gpt-oss-20b`, native MXFP4 (~13 GB) | Yes, with 128k context | reasoning_effort = medium (model default) | FROZEN |
| Qwen3.6-27B | `Qwen/Qwen3.6-27B`. BF16 (~54 GB) and FP8 (~28 GB) do not fit. Using NVIDIA's NVFP4 build `nvidia/Qwen3.6-27B-NVFP4` @ `0893e160` (21 GB on disk; NVIDIA reports scores within ~0.5 pt of FP8). Fallback if NVFP4 fails on the 5090: `glenic/Qwen3.6-27B-AWQ`. Hybrid attention (16 of 64 layers use a KV cache): ~64 KB of KV per token, so a 128k context costs ~8 GB. | Yes, at 4-bit | Thinking ON; model-card sampling (T=1.0, top_p=0.95, top_k=20); vision encoder disabled; tool parser `qwen3_coder`, reasoning parser `qwen3` | FROZEN |
| Llama-3.3-70B-Instruct | 4-bit is ~40 GB and does not fit. CPU offload with 64 GB RAM gives ~3-5 tok/s (days per system). 2-bit fits but damages the model enough that reviewers would reject it. | **No** | — | **DROPPED** (2026-10-21), replaced by Gemma-4-31B-it (next row) |
| Gemma-4-31B-it | `google/gemma-4-31B-it`, served as Red Hat's NVFP4 build `RedHatAI/gemma-4-31B-it-NVFP4` @ `5df75cca` (23.3 GB) with FP8 KV cache. NVIDIA's own NVFP4 build is 32.6 GB (attention kept BF16) and does not fit. Fallback: `LilaRest/gemma-4-31B-it-NVFP4-turbo` (19.3 GB, text-only). KV: 10 global layers (~80 KB/token BF16) + 50 sliding-window layers (fixed ~0.8 GB per sequence). | Yes, at 4-bit | T=1.0, top_p=0.95, top_k=64. Thinking on or off is frozen after the smoke test (registry aliases `gemma-4-31b-think` / `gemma-4-31b-nothink`) | **Thinking ON** (frozen 2026-10-21 by the pre-set rule: 0% truncation, ~14 s per question; alias `gemma-4-31b-think`) | FROZEN |

**Hosted models on OpenRouter (2026-10-25, OPEN until all authors agree).** The local GPU cannot finish the runs
before the deadline, and one collaborator has no GPU. The proposal: run every system on the same three models through
OpenRouter, with no local quantized builds, so all rows in a table use the same weights. Aliases `or-gpt-oss-20b`,
`or-qwen3.6-27b`, `or-gemma-4-31b-think` in `configs/models.json`. Each alias is locked to one provider with no
fallback:

| Alias | Provider | Precision | Note |
|---|---|---|---|
| `or-gpt-oss-20b` | CoreWeave | fp4 | MXFP4 is the official release format, so this is the original model |
| `or-qwen3.6-27b` | Alibaba | not listed by OpenRouter | The model's publisher. No provider serves fp4; the others serve fp8. `min_p` is dropped: Alibaba rejects it, and 0.0 disables it anyway |
| `or-gemma-4-31b-think` | Crusoe | bf16 | Novita (bf16) rejected a 21k-token prompt. Crusoe sometimes returns 429; the clients retry |

Sampling and caps are the same as the local entries. Thinking is set with OpenRouter's `reasoning` field instead of
vLLM's `chat_template_kwargs`. `context_len` stays 131,072, so the E2 full-context cut does not change. Put
`OPENROUTER_API_KEY=...` in `.env`. Use `run.py run` directly; `scripts/run_baselines.py` and `run_queue.py`
start local vLLM servers. The new aliases write to new `systems/<system>__or-*` folders, so local and hosted
predictions never mix. Smoke test (2026-10-25, `mfg_dev`, one question per type): full context ran on all three
aliases, and RAG and PageIndex ran on `or-gpt-oss-20b`, with no errors.

Rule: every LLM call inside every system uses the model under test, including PageIndex tree building, RAG answering,
and our map builder, tool generator and router. One-time costs are reported as setup tokens and amortized.

Output cap: `max_tokens` = 16384 per call (raised from 8192 on 2026-10-21: gpt-oss-20b vanilla hit 8192 on 2 of 32 smoke questions; raised for every model so no baseline is cut off). A truncated answer is scored as a parse error and counted in the report.

## 3. Data and splits

| Item | Decision | Status |
|---|---|---|
| Dev set | `runs/pilot20` (seed 0, 20 videos, 308 questions). All prompt and tool-generator tuning happens here only. | FROZEN |
| Test pool | 300 videos sampled with seed 1 from the 4,980 validation videos **not** in pilot20. | FROZEN |
| E1: main accuracy | The 300 test videos split into **15 documents of 20 videos** (~54k tokens each), so every model can hold a whole document and vanilla LLM gets its fairest shot. Questions: **all** explanatory, predictive and counterfactual (~510 / ~210 / ~560), plus a 25% stratified random sample of descriptive (~820). About 2,100 questions per model per system. | FROZEN |
| E2: scale | One document holding all 300 test videos (~800k tokens, beyond every model's context). gpt-oss-20b only, counterfactual + explanatory only. Shows vanilla collapsing and token cost growing while our system stays flat. | FROZEN (drop first if time runs out) |
| Scoring | Unchanged from the pilot (`clevrer_bench/scoring.py`): per-question and per-option for multiple choice, exact match for descriptive. Reports show a 95% percentile-bootstrap CI (2,000 resamples, seed 0) of question accuracy per system and type. They also show **paired** differences, OTF minus each other system with the same model on the same questions, with a 95% paired-bootstrap CI and the share of resamples <= 0 (`clevrer_bench/report.py`). | FROZEN |

**E2 as built (2026-10-22):** `runs/e2_d01`, the same 300 test videos in one 784-page document (about 838k
o200k tokens). Questions: the 554 counterfactual + 513 explanatory questions, identical to E1's, so E1 vs E2
isolates document size (all questions remain in `items_all.jsonl`). Model: gpt-oss-20b. Systems: vanilla, PageIndex,
RAG, OTF. Vanilla keeps whole pages from the start up to the context budget (131,072 - 16,384 output - 3,000 margin
= 111,688 tokens): the first 106 of 784 pages (13.5%). Its prompt says how many pages it got; the cut is recorded
in setup.json. The OTF tool library for E2 is separate from E1's.

## 4. Systems

| System | Definition | Status |
|---|---|---|
| Vanilla LLM | Whole document text + shared instructions + question in one call (current `full_context_text`, ported to chat completions). In E2 the document is cut from the end to fit the context, and the cut is reported. | FROZEN |
| RAG | 512-token chunks, 64 overlap, each chunk prefixed with its section path (e.g. "Video 10331 > Motion log"), standard practice. Embedder `BAAI/bge-small-en-v1.5` on CPU (fastembed 0.9.0, which serves Qdrant's quantized ONNX build), cosine top-k = 5, one answer call. Sections come from the PDF outline. Implemented in `clevrer_bench/systems/rag.py`. On pilot20 the top 5 contain the question's video for 80-92% of questions, depending on type. | FROZEN |
| PageIndex | `pageindex==0.4.0` local mode, as in the pilot, pointed at the vLLM endpoint. | FROZEN (check tool calling works on both models during smoke test) |
| Ours | Sec. 5. | FROZEN contracts, implementation pending |

Fairness: no system may read `item.question_type`, `item.question_subtype`, or gold fields. The harness will pass a
stripped item so this is enforced rather than promised. Our router predicts the type; an ablation with the oracle type is reported separately.

**Reporting rule** (decided 2026-10-21): if a baseline matches or beats our system for some model (the Qwen smoke test hinted at this for counterfactuals: vanilla 7/8 and PageIndex 7/8 on a 20-video document), report it as measured and discuss it. Do not retune or drop that model.

## 5. Our system (OTF): as built 2026-10-21

The method lives in the document-agnostic package `otf/`; the benchmark adapter is `clevrer_bench/systems/otf_system.py`
(system name `otf`).

1. **Navigation Map** (`otf/navmap.py`, deterministic, no LLM, ~2 s per 20-video document). Outline leaves become
   nodes of kind table, list, or text. Tables are parsed from word positions (pdfplumber): a short all-alphabetic
   header line, with each word assigned to the column whose left edge it sits under. On pilot20 it matches the
   renderer's own rows, events, and objects exactly for all 20 videos.
2. **Process-model generation** (`otf/toolgen.py`), eager, once per document. Generation tokens count as setup cost.
   - Step 1, parsers: `entities`, `recorded_end`, `observed_events`. Checked for consistent ids, at least one
     interaction found, and times within range. Up to 3 tries.
   - Step 2, forward simulator `simulate(doc, scope, removed, horizon, start)`, written by a **code-executing
     agent** on top of the checked parsers. It must first run at least 3 (at most 8) `explore` snippets on the
     real data; `doc` and the parsers are available, and the printed output comes back to it. It then submits
     `simulate`, and check failures come back into the same conversation (at most 5 submissions). If a
     conversation fails, a fresh one starts (at most 3). The prompt shows the parsers' real output on one scope
     that is not among the checked scopes. An empty reply (a gpt-oss quirk) is retried, with tokens counted.
   - **Forecast check (anti-replay):** for 6 scopes, `start` is set just before the first recorded interaction.
     The simulator runs on a blinded copy of that scope: tables keep only rows up to `start` plus each entity's
     first 2 rows, and every list line mentioning two or more entities is removed. Its events after `start` must
     match the recorded ones with mean F1 >= **0.4** (time tolerance 5% of the recorded period). Pure replay
     scores 0, which was verified. The bar was calibrated on the pilot20 dev set (2026-10-22): the hand-written
     oracle scores 0.644 on this check, and a gpt-oss model at 0.55 gave 26/32 end to end, so the earlier 0.7
     bar rejected useful models.
   - **Tool library** (`otf/library.py`): a model that passes is stored under the document's structural
     signature (node title patterns, kinds, table columns). Libraries are separate per split and per model, so
     test tools come only from test documents. A later document with the same structure first re-checks the
     stored model on itself and reuses it if it passes; generation cost is then paid once per structure.
3. **Router**: one LLM call classifies the question into one of the 4 types. The harness hides the gold type.
4. **Per-type tools** (`otf/engine.py`). All of them start from the record up to the divergence point:
   - counterfactual: one LLM call extracts the removed entities. The record holds until the first recorded
     interaction of a removed entity; from just before that, `simulate` runs forward.
   - predictive: `simulate` from the last recorded states, to 1.5x the recorded period.
   - explanatory: a dependency table, giving for each entity the recorded events that disappear when it is
     removed (same divergence logic).
   - descriptive: the scope's sections, read directly.
   If the model failed its check, or a tool run fails, the question falls back to reading the scope's sections.
   The fallback rate is reported.
5. **Sandbox** (`otf/sandbox.py`): separate `python -I` process; imports limited to a whitelist (stdlib math and
   data modules plus numpy); open/exec/eval/getattr and dunder attributes rejected; 20 s timeout.
6. **Answer**: one LLM call with the tool's evidence and the shared answer contract.

**Frozen 2026-10-22 (after the gpt-oss E1 single pass, before Gemma/Qwen OTF):**
- **Router**: `otf/prompts.py` `ROUTER`, a decision procedure (counterfactual, then predictive, then explanatory,
  then descriptive) with generic wording cues. Chosen on **pilot20 only**, 2 variants: on gpt-oss the old prompt
  (`ROUTER_V1`) got 293/308 (explanatory 24/36) and the new one 305/308 (explanatory 36/36).
- **End-of-split library re-check** (`scripts/otf_library_pass.py`, run by the orchestrator after each model's
  OTF pass): every document whose own model failed re-checks the split's library models with the same forecast
  check (F1 >= 0.4). If one passes, the document switches to it and is re-answered; its failed-generation tokens
  stay in its setup cost. gpt-oss E1: documents 1, 2, 3, 4 and 6 switched to document 8's model; documents 5, 7 and
  14 stayed on fallback (F1 0.392, 0.384, 0.378). 12 of 15 documents now use a generated model.
- **Reported rows**: `otf` = re-check + new router (official); `otf_single` = the first single pass with
  `ROUTER_V1` and no re-check (gpt-oss: 71.5% overall), kept as an ablation. gpt-oss's single-pass answers are kept
  in `predictions_router_v1.jsonl` / `predictions_pass1.jsonl` and copied to `systems/otf_single__gpt-oss-20b`.

**Generality guard**: `tests/test_no_benchmark_words.py` keeps benchmark vocabulary out of `otf/`.
**Oracle upper bound**: `oracle/oracle_model.py` is a hand-written model with the same interface, run with
`--system otf --system-arg model_code=oracle/oracle_model.py` (system name `otf_oracle`).

**OTF v3 (approved 2026-10-23; FROZEN 2026-10-23 ~21:00, git tag `otf-v3`): domain-general OTF, OTF's third
and final tuning variant.** After the freeze only logged bug fixes, as below.
Design: `docs/domains/otf_v3_design.md`; reason: `docs/domains/otf_review.md` (v2 is shaped like CLEVRER:
removal-only counterfactuals, events need 2+ participants, the forecast check hides future inputs, physics-shaped
prompts). Variants: v1 = `ROUTER_V1` single pass (`otf_single`), v2 = `ROUTER` + end-of-split library re-check
(`otf`, gpt-oss E1 75.7%), v3 = generalised. After the v3 freeze only logged bug fixes (crashes, exceptions, parse
failures, timeouts, prompt text that contradicts the code), never changes chosen by accuracy. Gemma's and Qwen's
OTF runs are held until the freeze; v2's gpt-oss E1 rows stay in the reports as ablations (`otf_v2`, `otf_single`).
Gates, pre-registered before any v3 run:
- **G1** every CLEVRER Navigation Map rebuilt by the v3 `navmap.py` is byte-identical (pilot20, e1_d01-d15, e2_d01).
- **G2** the benchmark-word guard (extended with the new domains' vocabulary) and the toy unit tests pass.
- **G3** the v3 oracle passes the v3 check on pilot20 (F1 reported next to v2's 0.644); end to end on all 308 pilot20
  questions it is within 2 points of the v2 oracle.
- **G4** gpt-oss v3 generation on pilot20 passes within the unchanged budget; on all 308 pilot20 questions v3 >= v2 - 3
  points. If G4 fails: bug hunt from the logs only (no prompt rewording), then proceed with v3 as pre-registered.
- **G5** on each new-domain dev document every table parses as a table and generation runs without a crash (no
  accuracy is looked at).
Forecast-check bar stays 0.4 for every domain (no per-domain calibration); per-domain pass rates and a post-hoc
sensitivity table at 0.3 / 0.5 are reported. Generation budget unchanged (3 parser tries; 3 conversations x 5
submissions; 3-8 explore runs).

**v3 gate run 1 (2026-10-23 17:24-17:46, gpt-oss, all 308 pilot20 questions; kept as `otf_v3gate1__*`):**
G1, G2 passed. G3 oracle v3 86.4% vs v2 88.3% (-1.9, inside the bar; counterfactual 55.3% vs 71.1%). G4 FAILED:
all 3 step-1 tries failed on gpt-oss's own code (a line pattern that missed the bracketed descriptions, twice;
then an identity test on rows), so OTF fell back to reading (85.1% vs v2 87.3%). G5: tables parse everywhere;
generation passed on itops_dev (F1 0.81), failed on mfg_dev and fin_dev. Changes made after run 1, before freeze:
1. **Bug fix (prompt contradicted the check):** the prompt asked `src` to include each record's time and entity
   cells, while step 1 rejected any cell shared by an input and an outcome, which a row holding both (e.g. a
   ledger row) cannot avoid. The overlap check is removed; the replay probe still fails any reader whose
   outcome values stay visible through cells marked as inputs (toy test added).
2. **Checker defect fix:** a failed step 1 now reports what each reading function returned on one scope and
   which list lines / table rows no record was read from (previously only "no records found", so a retry could
   not see why). Same for every model and document; no hint about answers or domain.
3. **Helper note:** `table_rows` builds new dicts per call; the helper text says to identify rows by index.
4. **Design cut line C5 (chosen after gate run 1, on pilot20 only):** the counterfactual replay point is the
   first recorded outcome touching the changed entities (as in v2), or the change time for a constant; the
   paired-simulation divergence time is dropped. In run 1 it started replay earlier than v2 on 4 pilot20
   counterfactual questions and all 4 were lost (the simulator predicted contacts the record does not show).
   Cost: in a queueing process, effects on other entities before the changed entity's first recorded outcome
   are replayed from the record.

**v3 gate run 2 (2026-10-23 18:04-18:25, fixes 1-4; v2 rows reused):** G3 PASSED: oracle v3 89.3% vs v2 88.3%
(counterfactual 68.4% vs 71.1%; 4 of 38 counterfactual questions fell back because the patch call returned no usable
patch). G4 FAILED again: generation produced no passing model on pilot20 (step 1), mfg_dev (step 1), itops_dev
(step 2; it passed in run 1 with F1 0.81) or fin_dev (step 2, F1 0); OTF fell back to reading (pilot20 82.1%).
Checker defects found in the logs and fixed after run 2:
5. On the blinded copy, a reader that crashed was reported as "reads differently", hiding the error (mfg_dev: all
   3 tries crashed on int('') of a hidden cell). The report now shows the crash and says hidden cells are "".
6. The prompts now say how hiding works (hidden cells become "", hidden rows and lines are removed).

**Qwen v3 generation probe (2026-10-23 18:30-19:50, after fixes 1-6, sharing the Qwen server; tool library off on
the dev documents):** a passing model on 3 of 4 documents, each in the first simulator conversation: pilot20 F1 0.572
(parsers on try 2; 262k setup tokens), mfg_dev F1 0.922 (try 3; 108k), itops_dev F1 0.749 (try 1; 285k). fin_dev failed
step 1 (src given as a bare node id twice, then outcome values readable on the copy). The first 4 questions of each
ran without tool errors (tools used on mfg_dev explanatory and itops_dev predictive questions). Generation success
is model-dependent: gpt-oss passed 1 of 8 attempts over the two gate runs, Qwen 3 of 4.

7. **Bug fix found in the fin_dev probe log:** a gridded table whose header spans two rows ("2019 | 2019" over
   "Capital additions | Depreciation") got repeated column names, so a reader and the blinding could address
   different cells by the same name (a false "outcome still readable" on fin_dev). Header rows that hold only words
   or years are now merged into the names while the names repeat or have gaps, and names still repeated are
   numbered. Affects gridded tables only: G1 re-run, all CLEVRER maps identical. Remaining known map limit: one
   finance prose section (fin_d02 R-136 Text) still parses as a word table.

**Post-freeze bug fix 8 (2026-10-25, found in the local Qwen E1 run; logged under the bug-fix rule):** the forecast
check certified a vacuous model. Qwen's reading code labelled every motion-log row as a value-less outcome
(`state_update`) and no collision; value-less records are matched by kind, entities and time only, so forecasting
"each object has a row every 8 frames" scored F1 0.76 and passed (e1_d02, reused by d03-d07), and Qwen's pilot20
gate-probe model passed the same way (`motion` rows, F1 0.57). In use the evidence buried the real collisions:
predictive accuracy was 16/16 on e1_d01 (reading fallback) and 9/77 on d02-d07. Fix: `records.schedule_kinds` marks a
value-less outcome kind as a recording schedule when it has one record for at least 80% of the rows of the table(s)
it is read from AND its times lie on a regular grid (>= 5 distinct times, >= 80% of grid points present); such kinds
are not scored by the step-1 replay probe or the forecast check, the sensitivity guard ignores them, the engine
leaves them out of the evidence, and the parser prompt says so (the prompt would otherwise contradict the check).
Re-check of existing models offline: oracle unchanged (F1 0.644, passes); Qwen e1_d02 model rejected at step 1; Qwen
pilot20 model F1 0.0 (fails); Qwen e1_d01 0.362, mfg_dev 0.922, itops_dev 0.749 and gpt-oss itops_dev 0.807 unchanged.
Toy test added (`test_schedule_rows_are_not_outcomes`); guard test passes. Same kind of loophole as copying the
record: a check must reward forecasting what happens, not when rows exist (a paper point).

**Move to OpenRouter (author decision 2026-10-25).** All remaining runs, and re-runs of everything reported, use the
hosted `or-*` aliases (sec. 2): full context, RAG, PageIndex and OTF-Tools (+ oracle and the ablations: reading only,
no replay, no library) on E1, E2 and the three new domains; the pilot20 dev checks run first. Collaborators run the
other baselines (GraphRAG, ReAct-R, ReAct-C, ReCode). The local GPU runs were halted at 14:50 (marker
`runs/logs/LOCAL_RUNS_HALTED` blocks auto-resume); local results stay on disk as an archive and are not used in the
paper. No spending cap. Latency is not compared with the local runs.

**Post-freeze bug fix 9 (2026-10-25, found in the first hosted pilot20 dev check; a checker defect that certified a
wrong model; git tag `otf-v3.2`):** the blinded copy hid later rows only in tables that the model's reading code
took records from. gpt-oss (`or-gpt-oss-20b`) read every input and outcome from the Events list and never cited the
Motion log, so the Motion log stayed whole on the blinded copy; its `simulate` scanned the recorded positions for
frames where two objects are within 0.5 units and passed with F1 0.911 (the hand-written oracle scores 0.644).
That is replay of a recorded trajectory, which the check exists to reject. Fix (`records.blind`, `_time_column`): a
table in the scope that no record was read from is also hidden after the cut when it has a time column, i.e. a
column that is numeric, non-decreasing down the rows, has >= 3 distinct values and ends inside the scope's recorded
span. It can only hide more; timeless scopes (finance) are unchanged. Toy test `test_unread_trajectory_is_blinded`
added; the guard test passes. Offline re-check (`scripts/recheck_models.py`): oracle unchanged (F1 0.644, passes);
mfg_dev Qwen 0.922, itops_dev Qwen 0.749 and gpt-oss 0.807 / 0.663 unchanged. The archived local Qwen E1 models
were passing the same way: d03 0.707 -> 0.362, d04 0.668 -> 0.167, d05 0.723 -> 0.364, d07 0.634 -> 0.203 (now
fail); d02 0.763 -> 0.400 and d06 0.549 -> 0.478 still pass. The hosted dev outputs made under the old checker were
moved to `runs/hosted_discarded_20261025/` and generated again.

**Post-freeze bug fix 10 (2026-10-25 ~17:30, a Navigation Map parse failure; git tag `otf-v3.3`), found by the
sanity check against full context** (gpt-oss manufacturing: OTF predictive 18.7% vs full context 30.7%). A leaf with
several ruled tables of different widths kept only its first table; the later tables and the captions fell into the
node's `text`, which neither the generated readers nor the reading fallback use. Lost: the manufacturing "Order book"
table of orders and planned production for the forecast days in every period with open backorders (11-12 of 15
periods per document; those periods' first table is the open-order list), and the IT-operations waiting queue in
"Queue at window end" (e.g. 51 waiting tasks in itops_d01 window 04). The questions state that this table holds
what then happened, so OTF's predictive tool ran without the future inputs (it used 1.5x the recorded period
instead) while full context, RAG and PageIndex, which read the PDF text, had them. Fix (`navmap.build_map`,
`_captioned_tables`): a leaf holding ruled tables and its own caption lines is split; each ruled table (with its
continuations) becomes a sibling node titled "<leaf title>: <the line just before it>" and the leaf keeps the caption
lines. Titles are then the same in every period (e.g. "...: Order book: Orders received and production planned for
days # to #"). G1 re-run: every CLEVRER map (pilot20, e1_d01-d15, e2_d01) byte-identical; finance maps identical;
toy tests and guard pass. Only manufacturing and IT-operations maps change. Consequence: all OTF runs on those two
domains (main, dev documents and their tool libraries) are redone; the earlier hosted ones were moved to
`runs/hosted_discarded_20261025_fix10/`. The baselines are unaffected. Collaborators' ReAct-R, ReAct-C and ReCode read documents through
the map (list_sections / read_section), so their manufacturing / IT-operations runs need the new map too (GraphRAG does not).

**Finding 1 (2026-10-25 ~17:50; resolved by OTF v3.4 below):** sanity check on finance, gpt-oss.
Overall OTF 64.7% vs full context 65.3%, but counterfactual 54.0% vs 63.3%. All of the loss is on fin_d02, the one
finance document whose generated model passed (F1 0.649): its 33 counterfactual questions answered with the tool
scored 1/33 (full context 23/33), while the reading-fallback documents fin_d01/d03 scored at or above full context.
Cause: for a timeless scope the counterfactual evidence is ENTITIES + RECORDED OUTCOMES + the changed input + the
recomputed outcomes (`engine._recorded`, `_evidence`). This model reads every reported figure as an input, so on
most reports there are no outcomes and the evidence holds none of the unchanged figures (e.g. R-104: "change from
2018 to 2019 if 2019 were 30.1" needs 2018 = 20.9, which the evidence never shows), and the answer is null or wrong.
This is not one of the allowed bug classes (no crash, parse failure, contradiction, or wrongly certified model), and
"fall back to reading when the tool evidence is empty" or "list the unchanged inputs" would be a design change chosen
by accuracy, so it is left as is pending the author. It contradicts the "graceful degradation" framing for finance.

**Finding 2 (2026-10-25 ~18:25; resolved by OTF v3.4 below):** manufacturing, gpt-oss, after fix
10: OTF 57.7% vs full context 54.3% overall (counterfactual +25.3, predictive -2.7, explanatory 41.3% vs 56.0%,
-14.7 [-29.3, +1.3]). The explanatory ("which conditions are responsible for the shortfall") choice checks compare
each "without it" re-run with the *recorded* outcome. In the example inspected (mfg-2103-03-02) every choice,
including the one the gold marks as not responsible, turned a recorded backlog of 10,781 into 0, i.e. the model's
re-run from mid-period (day 37) does not carry the accumulated backlog, so every candidate cause looks responsible.
The forecast check cuts just before a period's first recorded outcome (small state), so it does not test restarts
from a large mid-period state. Comparing against an unpatched re-run, or checking restarts mid-period, would be design
changes chosen by accuracy; left as is pending the author.

**OTF v3.4 (author decision 2026-10-25 ~18:40; git tag `otf-v3.4`).** The author relaxed the freeze: changes that
make OTF work better are wanted, made generically, validated on pilot20, and every split is re-run with the final
version (earlier numbers are archived, not reported). Triggered by findings 1-2 above (test-split sanity checks,
which the paper must not hide). Generation and the forecast check are unchanged, so stored process models are reused
and only answers are redone. Two changes to the answer step (`otf/engine.py`, `otf/records.py`, `otf/prompts.py`):
1. *Paired what-ifs* (`records.apply_delta`): a what-if runs the model twice from the same point, without and with
   the change; the base run is aligned with the record (same kind and entities, nearest time within one recorded
   period); for aligned outcomes only the difference between the two runs is applied to the record, so a value the
   model gets wrong in both runs keeps its recorded value (finding 2); a recorded outcome the model never reproduces
   is judged by the changed run alone, as before. Used by counterfactual runs, the dependency table and the choice
   checks; the no-replay ablation keeps the unpaired run. Toy test `test_paired_delta_cancels_model_error`.
2. *Record with the tool result in timeless scopes*: the scope's own sections come before the tool result (prompt
   `RECORD_AND_TOOL`), so unchanged figures stay visible (finding 1). Not for timed scopes: there the evidence lists
   the recorded outcomes already, and on pilot20 the extra sections cost explanatory accuracy (gpt-oss oracle 20 vs 25
   of 36). Switch `ablation=tool_only` turns it off.
pilot20 validation (all 308; cf / desc / expl / pred = total): gpt-oss oracle 22 / 211 / 23 / 14 = 270 (v3.3: 272);
Qwen oracle 20 / 216 / 20 / 14 = 270 (271); Qwen generated model 18 / 218 / 20 / 14 = 270 (273). Differences are
within run-to-run noise. Two intermediate variants were tried on pilot20 and rejected (pure paired runs without
alignment: explanatory 15/36; paired with time alignment but the record in every scope: 20/36).

**OTF v3.4.1 (2026-10-25 ~19:45, bug in v3.4's own code; tag `otf-v3.4.1`).** The paired what-if compared the run
without and with the change using the record's value tolerance (`value_tols`, coarse: hundreds or thousands of units
for stock), so a real change smaller than that (removing a 55-unit order) counted as "no change" and the recorded value
stayed; manufacturing counterfactual fell from 72.0% (v3.3 after fix 10) to 50.7% (gpt-oss). Fix: two runs of the same
model are compared exactly (records still pair within the time tolerance), and a numeric change is applied as recorded
value + (with-change - without-change). CLEVRER outcomes carry no values, so pilot20 / E1 / E2 are unaffected;
manufacturing, IT operations and finance OTF answers are redone. Toy test extended.

**OTF v3.4.2 (2026-10-25 ~20:05; tag `otf-v3.4.2`).** (a) The counterfactual DIFFERENCES and the choice checks
still compared the what-if with the record at the record's value tolerance; since the paired trace equals the record
except where the change acts, they now compare exactly (the no-replay ablation keeps the tolerance). (b) In a timeless
scope, or one where the model reads no outcomes at all (both models treat report years as a time axis, so finance
scopes are often "timed" with zero outcomes), a what-if that alters nothing the model computes now counts as a failed
tool run (reading fallback): the tool said "no differences", which the answer step read as "nothing changes", while the question needs
arithmetic on the changed figure (gpt-oss fin_d02: 0-1 of ~30 tool-answered counterfactuals in v3.3, v3.4 and
v3.4.1; reading answers on the same document ~55-75%). In timed scopes "no differences" stays an answer. CLEVRER
outcomes carry no values and are timed, so pilot20 / E1 / E2 are unaffected. Note: finance accuracy varies by +-5
questions per document between identical runs (fin_d01, reading only: 39, 37, 32 of 50).

**gpt-oss on the new domains with v3.4.2 (2026-10-25 ~20:45; question accuracy, hosted only):** manufacturing OTF
60.0% vs full context 54.3% vs RAG 25.3% (counterfactual 69.3 vs 46.7; predictive 36.0 vs 30.7; explanatory 44.0 vs
56.0, still behind); IT operations 27.7 vs 18.3 vs 16.7; finance 68.7 vs 65.3 vs 64.0 (counterfactual 66.7 vs 63.3).
PageIndex pending. Also 2026-10-25 ~20:35: hosted endpoints get a 10-minute request timeout (was 30 min, sized for the
local vLLM queue); single stalled requests had held whole documents for 30+ minutes.

**gpt-oss E1 (2026-10-25 ~21:40; OTF v3.4.2, hosted only): the navigation-only case (author decision).** OTF 67.8%
vs full context 61.2%, PageIndex 53.2%, RAG 49.1% (OTF ahead of PageIndex on every type, counterfactual +13.5
[+9.6, +17.3]; vs full context counterfactual +1.1, n.s.); oracle model 76.6% (predictive 91.2%). No E1 document got a
passing generated model (5 failed at step 1, 10 at step 2: crashes, a 20 s sandbox timeout, F1 0-0.37; e1_d07 reached
0.439 but failed the sensitivity guard), so every gpt-oss E1 answer is OTF's scoped-reading fallback. The author chose
to keep the generation budget unchanged and report gpt-oss E1 as the case where generation fails and OTF falls back
gracefully; the oracle row shows what working tools add.

**Incident 2026-10-25/26 (hosted runs):** unexpected shutdown at 23:01:59 (event 41/6008, hard reset; no GPU load,
all runs hosted), reboot at 07:56, logon at 11:07; runs resumed at 11:10 (~12 hours lost). 2 torn prediction lines
dropped (`repair_predictions.py`), re-asked. OTF generation in progress (Qwen/Gemma documents) restarted from scratch
(not resumable; the interrupted attempts' tokens are not in setup cost). `scripts/resume_after_reboot.ps1` now restarts
the hosted runners at logon (unless `runs/logs/HOSTED_RUNS_HALTED` exists or a runner is running).

**gpt-oss complete (2026-10-26 ~12:15; OTF v3.4.2; question accuracy %, overall and cf / expl / pred / desc;
reports `runs/<split>_hosted_gptoss_report.md`):**

| Split | OTF | Full context | RAG | PageIndex |
|---|---|---|---|---|
| E1 | 67.8 (43.7 / 48.5 / 57.6 / 96.6) | 61.2 (42.6 / 37.0 / 26.7 / 95.3) | 49.1 (34.3 / 40.2 / 30.4 / 68.1) | 53.2 (30.1 / 33.1 / 12.4 / 89.3) |
| E2 | 45.7 (43.3 / 48.3) | 13.2 (13.9 / 12.5) | 17.2 (11.4 / 23.4) | 24.2 (24.7 / 23.6) |
| Manufacturing | 60.0 (69.3 / 44.0 / 36.0 / 90.7) | 54.3 (46.7 / 56.0 / 30.7 / 84.0) | 25.3 (38.7 / 21.3 / 8.0 / 33.3) | 46.0 (42.7 / 34.7 / 29.3 / 77.3) |
| IT operations | 27.7 (5.3 / 4.0 / 25.3 / 76.0) | 18.3 (4.0 / 5.3 / 24.0 / 40.0) | 16.7 (5.3 / 8.0 / 21.3 / 32.0) | **32.0** (8.0 / 4.0 / 33.3 / 82.7) |
| Finance | 68.7 (66.7 / - / - / 70.7) | 65.3 (63.3 / - / - / 67.3) | 64.0 (65.3 / - / - / 62.7) | 52.3 (49.3 / - / - / 55.3) |

E1 ablations (all fall back to reading for gpt-oss, see above): oracle 76.6, reading-only 67.1, no-replay 67.0,
no-library 65.7. IT operations: PageIndex beats OTF (reported as measured, sec. 4 reporting rule); gpt-oss passed
generation on 2 of 5 IT-operations documents. Spend: $186 at the end of 2026-10-25 work (gpt-oss nearly all, Qwen /
Gemma dev checks); $368.5 at 2026-10-26 12:10 with Qwen and Gemma running (~$150 per hour while Qwen's full-context and
PageIndex runs are in progress).

**OTF v3.4.3 (2026-10-26 ~13:45; tag `otf-v3.4.3`).** Triggered by the sanity check on Qwen manufacturing (all 5
documents passed generation, F1 0.86-0.99, yet OTF 61.3% vs full context 79.0%; explanatory 21.3 vs 64.0): the choice
checks cannot take away conditions such as "older backorders were served first" ("not a cause that can be taken
away"), and the answer step, seeing only the tool result, answered "not responsible". Change: the scope's own sections
now come with every tool result (before: timeless scopes only), so the answer step always sees at least what the
reading fallback sees, and the prompt says to decide from the sections what the tool cannot check. pilot20 (dev, Qwen
generated model, cf / expl / pred): 17 / 25 / 14 vs 18 / 20 / 14 without; the gpt-oss oracle had shown 20 vs 25 on
explanatory in the earlier variant, so the dev evidence is neutral overall. `ablation=tool_only` keeps the tool result
alone. Only answers that used a tool change: those rows were set aside (`predictions_v342_tool.jsonl`) and re-asked
for every model; gpt-oss E1 (no tool use) is unaffected.

**OTF v3.4.4 (2026-10-26 ~16:30; tag `otf-v3.4.4`).** Qwen manufacturing after v3.4.3: OTF 64.3% vs full context
79.0%, reading-only (same scopes, no tools) 74.7%; the loss is explanatory (tools 29.3 vs reading 70.7), with the
answer saying "not responsible" where the gold says responsible. Change (`engine._unreproduced`): a choice check
counts only if the model's own re-run without any change reproduces the target outcome (and its value); otherwise it
reports "could not be checked" and the record decides. Explanatory, correct of 36 on pilot20 (dev): Qwen generated
model 25 (v3.4.3: 23), gpt-oss oracle 20 (23) - neutral; manufacturing Qwen 30 of 75 (v3.4.3: 22; reading-only 53;
full context 48). Tuning on this question type stops here (each further round is another change chosen on test
results); manufacturing explanatory with tools stays below reading for Qwen and is reported as measured. Only
explanatory answers that used a tool are re-asked (`predictions_v343_expl.jsonl`).

**Qwen E1 (2026-10-26 ~21:20; OTF v3.4.4; question accuracy %, overall / cf / expl / pred):** OTF 74.9 / 43.5 /
61.2 / 96.3; PageIndex 76.7 / 42.4 / 69.8 / 93.1; full context 67.8 / 35.0 / 46.4 / 84.8; RAG 52.2; oracle 75.1.
All 15 documents passed generation (e1_d01's model reused by d02-d15, F1 0.44-0.74); OTF matches the oracle. OTF vs
PageIndex: -1.8 [-3.3, -0.3] overall, counterfactual +1.1 [-2.2, +4.3] (n.s.), explanatory -8.6 [-12.7, -4.9],
predictive +3.2 [-0.5, +6.9]. Sanity check vs full context passes on every type. Ablation `tool_only` (explanatory
only): 56.1 vs 61.2 with the record (v3.4.3 confirmed on E1). Reading-only ablation (same scopes, no tools): 73.7 /
38.6 / 61.0 / 97.2; OTF minus reading-only: counterfactual +4.9 [+1.8, +7.8] (p=0.001), explanatory +0.2, predictive
-0.9, overall +1.2 - the tools' gain is on counterfactuals; PageIndex's explanatory lead also holds against reading.

**Incident 2026-10-26/27:** unexpected shutdown at 23:19:52 (hard reset, sixth one), reboot 09:06, logon 12:06; the
logon hook restarted the hosted runners at 12:06 (0 torn lines, 0 damaged cache files); ~12.8 hours lost.
**Gemma scope for the deadline (2026-10-27 12:15):** Crusoe caps Gemma at ~8-12 answers/min (8 of 8 test requests
returned 429 at our load) and ~6,700 Gemma main questions remained. Priority within Gemma: OTF and PageIndex (the
paper's comparison) on E1 and the three domains first; E1 full context and RAG resume if time allows; Gemma E2 and
ablations are cut (priority rule). Qwen: only ablations and a few PageIndex questions left; gpt-oss complete.

**Hosted harness (2026-10-25, same for every system; no method change):**
- *Patient retries.* `clevrer_bench/llm.py` `with_backoff`: transient endpoint errors (429, 5xx, timeouts, dropped
  connections) are retried with exponential backoff (5 s doubling to 2 min, up to 30 min) around every model call
  of full context, RAG, OTF and PageIndex (indexing calls and the per-question agent). Reason: Crusoe (Gemma)
  returned 429 at 4 parallel jobs, and OTF's answer step catches every exception while building tool evidence, so
  a 429 there silently became a reading fallback (seen on Gemma's pilot20 oracle, question 12052-14); in generation
  a 429 crashed setup and restarted generation, which would give more tries than the budget.
- *Transient tool errors are not answers.* `scripts/run_hosted.py` drops any OTF answer whose `tool_error` is a
  transient endpoint error before each pass, so the question is asked again instead of being scored as a fallback.
- *No-library ablation folder.* `use_library=false` now writes to `otf_no_library__<model>` (bookkeeping), so it
  never mixes with the main `otf` run. The dev-document checks therefore sit in `otf_no_library__or-*`.
- *Ablations start from the main run's models.* Reading-only and no-replay copy the main E1 run's final
  `otf_model.json` per document (after the library re-check), so they differ from `otf` only by the switch and
  report the same setup cost. No-library generates afresh on every document.
- *Runner.* `scripts/run_hosted.py` (jobs = split x system x model, up to 3 passes, OTF library re-check and
  re-answer as in `run_queue.py`; events in `runs/logs/hosted__status.jsonl`, output in `runs/logs/hosted/`).
  Concurrency per model: gpt-oss 6 jobs x 8 questions, Qwen 6 x 6, Gemma 3 x 4.
- *Incident (15:05-15:25):* killing the first runners left their `run.py` children running, so for ~15 min two
  processes answered the same questions. Fixed by de-duplication (first valid answer per question kept; 190 rows
  dropped in 6 baseline files, no torn lines) and a runner guard (`--stop` kills runners and children; a runner will
  not start while hosted `run.py` processes exist). PageIndex indexes of e1_d01/d02 and mfg_d01 may have been built
  twice; the cached index and its token count are one build's.
- *Spend.* The OpenRouter key had used $59.19 before the hosted runs started (smoke tests); spend is reported
  from that baseline.
- *Incident (16:20-16:48): network choke and credits.* With ~150 requests in flight (all three models at once), new
  outbound connections from this PC timed out (any site; DNS fine) and OpenRouter began returning 402 ("would exceed
  your available credits given your current in-flight requests"). Stopping every run restored the network within a
  minute. The account holds $200 of credits, $147.45 used at 16:50 ($88.26 by the hosted runs). 402 is now treated as
  transient (wait and retry, never an answer or a fallback). Only gpt-oss resumed (16:55, ~60 requests in flight);
  Qwen and Gemma wait for a credit top-up. Throughput measured before the stop: gpt-oss ~46, Qwen ~20-27, Gemma ~6-8
  answers per minute (Crusoe throttles Gemma; Novita bf16 timed out on E1- and E2-sized prompts, so Crusoe is the
  only usable bf16 provider).
- *Root cause of the network choke (found 17:40-18:15):* the PageIndex adapter leaked one open connection per
  question (PageIndex runs each question's agent in a fresh event loop and LiteLLM caches one HTTP client per loop for
  up to an hour), so the PC's connections climbed by ~20 per minute until new ones were refused (seen a second time at
  17:40 with only gpt-oss running; 85 -> 249 connections in 8 min with 2 PageIndex jobs). `pageindex_system.py` now
  drops LiteLLM's client cache and collects the clients after each question (a test process: 8 questions left 8
  connections open before, 0 after); requests and answers are unchanged. Since then connections stay ~45 and every
  probe passes (`scripts/net_watch.py`, `runs/logs/hosted__net.jsonl`).
- *Library re-check bookkeeping.* An OTF job counts as finished only once its library re-check is logged, so a stop
  between the last answer and the re-check cannot skip it.

**Hosted dev checks (2026-10-25, otf-v3.2, after fix 9; `scripts/hosted_dev_summary.py`).** Token metering works on
OpenRouter: input, cached, output and reasoning tokens are all reported (and per-call cost); reasoning tokens > 0 for
Qwen (~1.6k per question) and Gemma (~0.8k), so thinking is on. pilot20, all 308 questions (cf / desc / expl / pred):

| Model | OTF generation on pilot20 | OTF (pilot20) | Oracle (pilot20) |
|---|---|---|---|
| or-gpt-oss-20b | failed at step 1 (3 tries: no entities, then `src` given as a bare node id); 25k setup tokens; reading fallback | 17/38, 211/220, 18/36, 8/14 = 254/308 (82.5%) | 21/38, 211/220, 26/36, 14/14 = 272/308 (88.3%) |
| or-qwen3.6-27b | passed, F1 0.589 (parsers try 1, simulator conversation 1); 166k setup tokens (36k reasoning), 13 min | 22/38, 216/220, 21/36, 14/14 = 273/308 (88.6%) | 21/38, 216/220, 20/36, 14/14 = 271/308 (88.0%) |
| or-gemma-4-31b-think | failed at step 1 (3 tries: a crash, then `src` as a bare node id); 22k setup tokens; reading fallback | 151/163 so far (92.6%) | 242/266 so far (91.0%) |

Dev documents (library off, first 4 questions; generation only, accuracy not looked at): gpt-oss failed on mfg_dev
(step 1, 24k), itops_dev (step 2, F1 0 over 23 submissions, crashes in its own code, 663k) and fin_dev (step 1, 29k);
Qwen failed mfg_dev (step 1, 53k) and passed itops_dev (F1 0.941, 174k); Gemma passed mfg_dev (F1 0.784, 137k) and
failed itops_dev (step 1, 30k) and fin_dev (step 1, 37k). Every failure is in the model's own code (bad `src` shape,
crashes, reading outcomes from input cells), not a harness error; no tool errors on any answered question. Generation
reliability stays model-dependent, as in the local gate runs (gpt-oss passed 1 of 8 attempts there).

**Finance framing (author decision 2026-10-23):** finance stays as the domain without a process. Most report tables
list reported figures with few derived cells, so the forecast check has little to verify and both models modelled
the years as a time axis; OTF is expected to fall back to reading there. The paper reports it as graceful
degradation: OTF should win where a document describes a process (physics, manufacturing, IT operations) and match
the baselines where it does not. The abstract must not claim wins in all four domains.

**Status 2026-10-22, pilot smoke set (8 questions per type):**

| gpt-oss-20b | cf | desc | expl | pred | Total | Input tokens per question |
|---|---|---|---|---|---|---|
| OTF, generated model (check F1 0.622; passed on the 3rd fresh conversation; setup 360k tokens, 13 min) | 6 | 8 | 6 | 8 | **28/32** | 1.5k |
| OTF, hand-written oracle model | 7 | 8 | 6 | 8 | 29/32 | 1.3k |
| OTF, fallback only (generation failed) | 5 | 8 | 5 | 4 | 22/32 | 3.0k |
| Vanilla | 5 | 8 | 3 | 3 | 19/32 | 54k |
| RAG | 5 | 5 | 4 | 4 | 18/32 | 1.2k |
| PageIndex | 3 | 7 | 5 | 1 | 16/32 | 16k |

Router accuracy 28/32; tools used on 21/32 questions (the rest are descriptive), with 0 tool errors.
Gemma and Qwen generation tests run automatically (`scripts/test_generation_when_up.py`) when the E1
orchestrator brings their servers up. Results go to `runs/logs/otf_generation__<model>.txt`.

**Incident 2026-10-21/22:** the PC hard-reset at 23:51 (under GPU load) and again at 01:35, with no Windows
bugcheck and no dump, plus corrected PCIe errors on the GPU's slot (02:00.0). Runs resumed at 10:42 on
2026-10-22 with no data lost: one torn prediction line was dropped and will be re-asked. About 11 GPU-hours were lost.

**Incident 2026-10-23/24 (same pattern):** unexpected shutdown at 23:04:13 under GPU load (RTX 5090 at its 575 W
limit, ~516 W drawn; Qwen full context + Qwen OTF generation), automatic reboot at 23:06 with nobody logged on (the
resume task runs at logon, so nothing restarted), a second unexpected shutdown at 23:35:46 with no jobs running, and
no boot until 10:41. Corrected WHEA hardware errors at both boots (4 / 19 / 6 / 2 on Oct 21 / 22 / 23 / 24). Runs
resumed at 10:44 with no data lost (0 torn lines). About 11.5 GPU-hours were lost. Qwen's OTF generation for
e1_d01 was in its second simulator conversation and restarted from scratch (generation is not resumable); the
interrupted attempts' tokens are not in its setup cost, and the restart is a fresh draw within the same budget.
**Mitigation (2026-10-24 ~11:00):** the GPU power limit was capped at 450 W (default 575 W) with `nvidia-smi -pl 450`
in an admin terminal; confirmed enforced (444 W drawn at 68 C, full utilization). The cap applies to every system and
model run from then on; it changes speed, not outputs (same checkpoints, sampling and caps), so accuracy and token
counts stay comparable with earlier runs; latency is reported per system and is not compared across this change.
The cap does not survive a reboot and must be re-applied after any restart.

## 6. Durability

- Resumable runs (already in `runner.py`). Errors are retried; truncation is recorded, not retried.
- `run_config.json` per run: model repo + revision, quant, vLLM version, sampling, seed, git hash of the harness.
- Map, tools, and verification logs are cached per (document hash, model) under `systems/<name>/work/`.
- Per-call token accounting (input / cached / output / reasoning / calls), including tool generation and router calls.

- **Crash recovery (2026-10-22):** Windows scheduled task `MLSys2027-ResumeRuns` (user-level, at logon of
  STUDENTashraf, not elevated) runs `scripts/resume_after_reboot.ps1`. 90 s after logon, if the E1 orchestrator
  is neither running nor finished, it runs `scripts/repair_predictions.py` (drops torn lines) and restarts it; it
  restarts the OTF generation watcher the same way. It logs to `runs/logs/resume_after_reboot.log`.
  Long jobs must run as independent processes (via this task, or Start-Process), never in Claude terminal tabs: a
  Claude app restart at 12:01 on 2026-10-22 killed the tab-launched jobs. To relaunch manually:
  `Start-ScheduledTask -TaskName "MLSys2027-ResumeRuns"`.
  REMOVE IT when the experiments are done: `Unregister-ScheduledTask -TaskName "MLSys2027-ResumeRuns" -Confirm:$false`.

## 7. Harness changes needed

1. Configurable `base_url`; port `full_context` from the Responses API (`input_file`, `prompt_cache_key`) to chat completions.
2. PageIndex via LiteLLM `hosted_vllm/` (or `openai/` + `api_base`) for indexing and chat; confirm usage metering still works.
3. Multi-document runs (E1 = 15 docs) plus aggregation across documents in `report.py`.
4. Stripped `QAItem` passed to systems (no type or subtype).
5. `max_tokens` and truncation flag in `Prediction`.

## 8. Day-1 smoke test (gate before any full run)

For each local model: start vLLM, run 30 pilot questions (all four types) through vanilla and PageIndex, and record
tokens/s, seconds per question, tool-call success, and truncation rate. From those numbers, confirm E1 fits the GPU
budget (rough estimate: Qwen ~15-25 GPU-hours and gpt-oss ~5-8 GPU-hours across the four systems). If it doesn't, cut the descriptive sample first, then E2.

## 9. Schedule

| Dates | Work |
|---|---|
| Oct 21-22 | vLLM setup, smoke test, harness changes (sec. 7), build E1/E2 documents, RAG baseline |
| Oct 22-24 | Our system on pilot20 only (map, router, generator, verifier, sandbox) |
| Oct 24-27 | Full runs: gpt-oss-20b, then Qwen (GPU is serial); Llama in parallel if hosted |
| Oct 25-28 | Paper written in parallel; final tables Oct 28 |

## 10. Smoke-test results (2026-10-21, pilot20 dev set, 8 questions per type, 8 parallel workers)

| Model | System | cf / desc / expl / pred (of 8 each) | Tokens per question (in / out) | Truncated | Time per question |
|---|---|---|---|---|---|
| gpt-oss-20b | vanilla | 5 / 8 / 3 / 3 | 54k / 2.3k | 2 of 32 | 4.2 s |
| gpt-oss-20b | PageIndex | 3 / 7 / 5 / 1 | 16k / 1.0k | 0 | 1.7 s |
| Qwen3.6-27B | vanilla | 7 / 7 / 4 / 8 | 66k / 1.9k | 0 | 30-35 s |
| Qwen3.6-27B | PageIndex | 7 / 8 / 6 / 7 | 27k / 2.6k | 0 | 17 s |
| Gemma-4-31B think | vanilla | 5 / 8 / 7 / 8 | 68k / 1.5k | 0 | 14 s |
| gpt-oss-20b | RAG | 5 / 5 / 4 / 4 | 1.2k / 0.7k | 0 | 2.4 s |
| Gemma-4-31B no-think | vanilla | 4 / 8 / 7 / 1 | 68k / 0.02k | 0 | 1 s |

Serving notes: every model uses `--attention-backend TRITON_ATTN`, because FlashInfer needs nvcc to JIT sm_120
kernels and WSL has none. Qwen is slow on vanilla: its hybrid-layer state checkpoints evict the cached 66k-token
document, so only 2-4 requests run at once. PageIndex on local models uses `protocol="chat_completions"`, because
vLLM's Responses endpoint rejects the agent's tool outputs. That envelope reports token totals but no per-question
LLM-call or tool-call count.

**E1 GPU budget (2,166 questions per system):** gpt-oss ~3.5 h, Gemma ~8.5 h vanilla plus an estimated ~6 h PageIndex,
Qwen ~20 h vanilla plus ~10 h PageIndex. Baselines total ~48 h. Still to add: RAG (~8 h est.), ours (~25 h est.),
E2 (~6 h). Grand total ~88 GPU-hours against ~144 wall-clock hours to Oct 27 evening, so the baselines must start immediately.

**Priority rule (2026-10-22, user decision):** Qwen3.6-27B runs **full E1** (all 2,166 questions, all five
systems) regardless of time. If the GPU time before the Oct 27 evening freeze runs short, cut in this order:
first Tier B of the new baselines (Gemma/Qwen on E1-core), then E2 (the large-document experiment). Full E1 for
all three models is not cut.

**Update 2026-10-22:** a collaborator is running the **Tier B** new baselines on their own workstation, so they
don't compete for this GPU. Their results will be merged when they arrive. For comparability they must use the same
checkpoints, quantization, sampling and caps as `configs/models.json` and `scripts/serve.sh`. Token counts and
accuracy are comparable across machines; latency is not, and is reported separately.

## 11. Additional baselines: GraphRAG, ReAct, ReCode (PLANNED, added 2026-10-22)

Full design and reasoning: `docs/new_baselines_design.md`. **The current runs are not changed by this section.**
Everything below is OPEN until the pilot20 smoke test and dev tuning are done; then it is frozen here before any
E1/E2 question is answered.

| Item | Plan | Status |
|---|---|---|
| Purpose | Each baseline isolates one OTF ingredient: GraphRAG = structure without execution; ReAct-R = iteration without code; ReAct-C = per-question code with the same map and sandbox as OTF (no once-per-document check or reuse); ReCode = recursive on-the-fly code generation, per question | FROZEN |
| GraphRAG | `microsoft/graphrag` 3.x (version + commit pinned at install), standard LLM indexing with default prompts (its own `prompt-tune` allowed on pilot20 only), bge-small embeddings via a local OpenAI-compatible CPU endpoint, local search on E1, local + global search on E2. If >10% of chunks fail JSON extraction on pilot20, that model uses the documented `fast` indexing method | OPEN |
| ReAct-R | ReAct loop (Thought, Action, Observation) with native tool calling; tools: `search` (RAG's index), `read_section`, `list_sections`, `finish` | OPEN |
| ReAct-C | ReAct-R tools plus `python(code)` in `otf/sandbox.py` with the same Navigation Map `doc` and helpers as OTF | OPEN |
| ReCode | `FoundationAgents/ReCode` (MIT, commit pinned), `docqa` environment with the ReAct-C primitives plus `answer`; 2-3 generic few-shots from pilot20 only; max depth 6 | OPEN |
| Shared caps | Same model and sampling as sec. 2; 16,384 output tokens per call; at most 12 model calls per question (cap hit = parse error, reported); stripped items; shared answer contract and scorer; all tokens counted, indexing as setup cost | FROZEN |
| Tuning budget | At most 3 prompt/config variants per system (OTF included), compared on pilot20 only; all variants listed in the appendix | FROZEN |
| OTF ablations | Reading-only (forced fallback); no-check (first simulator without the forecast check); no-divergence-replay; gold router; library off (= OTF single pass); oracle model (`otf_oracle`) | OPEN (switches not implemented yet) |
| Compute tiers | Tier A (must): gpt-oss-20b, all four baselines on full E1 and on E2 (~20-25 GPU-h). Tier B (if time): Gemma and Qwen on E1-core = `e1_d03, d06, d09, d12, d15` (~720 questions; ~10 GPU-h per model). Go/no-go on Oct 25 09:00: if fewer than 40 GPU-h remain before the Oct 27 evening freeze, Tier B runs for Qwen only (superseded by the 2026-10-22 priority rule: Qwen's full E1 comes first; Tier B, then E2, are cut first if time is short) | FROZEN |
| Reporting | Same reports as the other systems (accuracy with bootstrap CIs, paired differences vs OTF, McNemar), plus: cost-accuracy frontier, break-even curve (setup amortization), E1 to E2 degradation, counterfactual error overlap (UpSet), code-reliability table | FROZEN |


## 12. Additional domains: manufacturing, IT operations, finance (added 2026-10-23)

Specs and decisions: `docs/domains/` (README, one file per domain, each with an "As built" section). Generators,
reference simulators, renderers and validation: `domains/manufacturing/`, `domains/it_ops/`, `domains/finance/`
(each with VALIDATION.md, all PASS). Runs: `runs/mfg_d01-d05` + `mfg_dev`, `runs/itops_d01-d05` + `itops_dev`
(300 questions each, 75 per type), `runs/fin_d01-d03` + `fin_dev` (300 questions: 150 counterfactual + their 150
factual twins). The dev documents are for smoke tests only; no system is tuned on any new domain.

| Paper name | Data | Real | Simulated |
|---|---|---|---|
| Manufacturing | SupplyGraph (LGPL-2.1) | daily production and sales orders, plants, storage | stock and dispatch policy |
| IT operations | Google clusterdata-2011-2 (CC-BY 4.0) | task arrivals, priorities, requests, durations, failures | scheduler policy (capacity 1/8 of real machines) |
| Finance | TAT-HQA (Apache-2.0) | tables, text, questions and gold | nothing |

**Harness integration (2026-10-23, after the v3 freeze; same for every system).** A run's `manifest.json`
"domain" selects the answer contract, the prompt's first line and the scorer; no domain = CLEVRER, unchanged:
- prompt line 1 = the scope title (CLEVRER: "Video <n>"); answer instructions: `GENERIC_ANSWER_INSTRUCTIONS`
  (manufacturing, IT operations: CLEVRER's JSON contract without CLEVRER wording) or
  `FINANCE_ANSWER_INSTRUCTIONS` (`{"answer", "scale"}`, numbers / text spans / lists; domains/finance/ANSWER_CONTRACT.md);
- a question is multiple-choice only if it lists choices (finance counterfactuals are open-ended);
- finance is scored with TAT-QA's metric (`domains/finance/score.py`): question accuracy = exact match with the
  right scale; em, f1 and scale_correct are stored per question.
Verified before any live run picked it up: all 3,541 CLEVRER prompts, stripped items, the answer instructions and
the E1 split report are byte-identical, and all 25,126 stored CLEVRER predictions parse and score identically
under the old (91f5893) and new harness; on every new-domain document the generated prompts equal
`questions.jsonl`, the answer format is right for every item, and gold scores 100%; an offline end-to-end run
(stub system) wrote predictions and split reports for all three domains without errors.
