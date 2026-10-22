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
| Compute tiers | Tier A (must): gpt-oss-20b, all four baselines on full E1 and on E2 (~20-25 GPU-h). Tier B (if time): Gemma and Qwen on E1-core = `e1_d03, d06, d09, d12, d15` (~720 questions; ~10 GPU-h per model). Go/no-go on Oct 25 09:00: if fewer than 40 GPU-h remain before the Oct 27 evening freeze, Tier B runs for Qwen only | FROZEN |
| Reporting | Same reports as the other systems (accuracy with bootstrap CIs, paired differences vs OTF, McNemar), plus: cost-accuracy frontier, break-even curve (setup amortization), E1 to E2 degradation, counterfactual error overlap (UpSet), code-reliability table | FROZEN |

