# Experiment design: GraphRAG, ReAct and ReCode as additional baselines

Status: **design only** (2026-10-22). Nothing here changes the experiments that are already running. All
settings below get frozen in `SPEC.md` (section 11) **before** any of these baselines sees an E1 or E2 question.

---

## 1. Why these three, in one sentence each

Each new baseline isolates one ingredient of OTF, so that a win (or a loss) tells us *which* ingredient matters.
Think of it like testing a new recipe: to show the sauce is what makes the dish, you also cook it with the
same pan, the same oven and the same ingredients, swapping one thing at a time.

| Baseline | What it has in common with OTF | What it lacks | The reviewer attack it answers |
|---|---|---|---|
| **GraphRAG** (Edge et al. 2024; `microsoft/graphrag`) | A structured index of the whole document, built once, with a one-time setup cost | Executable tools; the index is a graph of entities and summaries, not a model you can run | "Your gain comes from structuring the document, not from tools." |
| **ReAct, retrieval only** (Yao et al., ICLR 2023) | A multi-step agent that decides what to read next | Code execution | "Any agent that can iterate would do as well." |
| **ReAct + code** (ReAct with a Python tool; CodeAct-style) | Multi-step agent, the **same** Navigation Map and the **same** sandbox as OTF | Tools written once per document, *checked against the record*, and *reused* | "This is just program-of-thought; any agent that can run code would do this." **This is the most important comparison.** |
| **ReCode** (Yu et al., ICML 2026; `FoundationAgents/ReCode`) | Writes code on the fly, recursively, from plans down to primitive actions | The document-level forecast check and the tool library; code is written per question | "Recent code-as-plan agents already create tools on the fly; what is new?" |

Together with the baselines we already run (vanilla, RAG, PageIndex) and OTF's own ablations (section 6),
this covers the three things a reviewer will try to explain our gains away with: **structure**, **agentic
iteration**, and **code execution**.

---

## 2. Reviewer questions and the experiment that answers each

Each row is a question we expect in reviews, the measurement that answers it, and what result would hurt us
(we report it either way: SPEC reporting rule, 2026-10-21).

| # | Expected attack | Experiment / measurement | Result that would hurt us |
|---|---|---|---|
| Q1 | "Gains come from the structured map, not the tools." | GraphRAG vs OTF; and OTF **reading-only** ablation (same map, no tools) vs OTF | GraphRAG or OTF reading-only within CI of OTF on counterfactual/predictive |
| Q2 | "Any iterative agent would do it." | ReAct-R vs OTF, same model, same answer contract | ReAct-R within CI of OTF on counterfactual |
| Q3 | "It's just code execution / program-of-thought." | **ReAct-C vs OTF**, both with the same map + sandbox; per-question code vs per-document checked, reused tools | ReAct-C matches OTF accuracy at similar or lower total cost |
| Q4 | "On-the-fly tool creation is not new (ReCode, CREATOR, LATM)." | ReCode vs OTF; plus OTF **no-check** ablation (use the first generated simulator without the forecast check) | ReCode matches OTF; or no-check ≈ OTF (would mean the check adds nothing) |
| Q5 | "Generating tools is expensive." | Cumulative tokens vs number of questions answered, per document and per split; **break-even point** against each baseline; setup counted in full, including failed attempts | OTF's break-even is above the questions-per-document we actually have |
| Q6 | "It won't hold on long documents." | E2 (784 pages): GraphRAG (local + global search), ReAct-R, ReAct-C, ReCode vs OTF; E1 → E2 change per system | OTF degrades as much as the others from E1 to E2 |
| Q7 | "Only works with strong models; generation is brittle." | Generation success rate per model and per document; fallback rate; compare with ReAct-C's and ReCode's per-question code-failure rate | OTF's document-level failure rate is worse than per-question code failure |
| Q8 | "Baselines were weakened (prompts, budgets, versions)." | Pre-registered protocol (section 4): official code pinned by commit, same model, same caps, equal and dev-only tuning budget | Any baseline got less tuning or budget than OTF |
| Q9 | "Statistically meaningless differences." | Paired bootstrap CIs (already in the reports) and McNemar's test on the same questions | CIs overlap zero on counterfactual |
| Q10 | "Why does it help counterfactuals in particular?" | Error-overlap analysis on counterfactual questions; OTF **no-divergence-replay** ablation (simulate from time 0) | No-replay ≈ OTF (the replay idea would not be the reason) |
| Q11 | "Where does OTF lose?" | Descriptive questions; documents where generation failed; cost when few questions per document; latency of setup | (Expected; we report it as limitations) |

---

## 3. What stays identical for every system (fairness)

These are the same as for the running experiments, so the new baselines plug into the same reports:

- **Model**: every LLM call (indexing, agent steps, code writing, answering) uses the model under test, with the
  frozen sampling settings in `configs/models.json` and the 16,384-token output cap per call.
- **Question input**: the harness's stripped item (no question type, no gold), the shared answer instructions
  and question prompt, and the shared JSON answer parser and scorer.
- **Document input**: the same PDF. Text comes from the same extraction (`extract_pdf_pages`); systems that use
  structure get the same Navigation Map (`otf/navmap.py`), which is deterministic and LLM-free.
- **Code execution**: the same sandbox (`otf/sandbox.py`: isolated process, import whitelist, 20 s timeout).
- **Budgets**: an agent gets at most **12 model calls per question**; hitting the cap scores as a parse error,
  counted and reported (same treatment as truncation).
- **Token accounting**: all calls counted (input, cached, output, reasoning). One-time costs (GraphRAG indexing;
  OTF generation) are setup cost, reported separately and amortized, exactly like PageIndex's index build.
- **No benchmark-specific hints**: no system's prompts mention videos, collisions or physics. Domain knowledge
  may only come from the document's own front matter, which every system can read.

---

## 4. Pre-registered protocol (to defeat attack Q8)

1. **Official implementations, pinned.** GraphRAG: `microsoft/graphrag` (latest 3.x at install time; the exact
   version and commit go in SPEC). ReCode: `FoundationAgents/ReCode` at a pinned commit (MIT). ReAct: a minimal
   loop that follows the paper (Thought, Action, Observation) using the chat API's native tool calling, which
   already works for all three models in our vLLM setup (parsers `openai`, `qwen3_coder`, `gemma4`).
2. **Equal, dev-only tuning budget.** Each baseline, and OTF, gets at most **3 prompt or configuration variants**,
   compared on **pilot20 only** (the dev set; never E1 or E2). The variant with the best pilot accuracy is
   frozen. All variants tried are listed in the appendix.
3. **Defaults first.** Where a method has documented defaults (GraphRAG chunking, community levels, search
   parameters), we use them; deviations are listed with the reason.
4. **Frozen before testing.** Versions, prompts, budgets and tool sets are written into SPEC section 11 before
   the first E1 question is answered. Changes after that are allowed only for crashes, and are logged.
5. **Release.** The adapters (GraphRAG wiring, ReAct loop, ReCode environment) are released with the paper.

---

## 5. Each baseline in detail

### 5.1 GraphRAG

- **Index**: standard (LLM-based) indexing with GraphRAG's default prompts, run on the same extracted text. Its
  own prompt auto-tuning (`graphrag prompt-tune`) is part of the method, so it is allowed, but **only on the
  pilot20 document**, once, and the tuned prompts are then frozen.
- **LLM wiring**: GraphRAG calls models through LiteLLM and needs structured JSON output; our vLLM server supports
  guided JSON. Embeddings: the same `bge-small-en-v1.5` model as RAG, exposed through a small local
  OpenAI-compatible embedding endpoint on CPU, so retrieval quality matches RAG.
- **Query modes**: **local search** for E1 (each question names its video, which becomes an entity in the graph);
  **local + global search** on E2 (global search is GraphRAG's answer to whole-corpus questions, so a reviewer
  will ask for it on the long document). DRIFT search is optional and only run if time remains.
- **Setup cost**: every indexing call is metered (the same LiteLLM meter as PageIndex).
- **Known risk (pre-registered)**: GraphRAG's documentation warns that small local models often return malformed
  JSON. Rule: if more than 10% of chunks fail extraction on pilot20 for a model, that model runs GraphRAG with
  the documented `fast` (NLP-based) indexing method instead, and we report it.
- **What we expect and why it is still informative**: entity graphs summarise *who interacted with whom*, but
  they drop the numeric state (positions, velocities) that counterfactual and predictive questions need. If that
  shows up in the numbers, it is direct evidence for our claim that **structure without execution is not
  enough**.

### 5.2 ReAct (two variants)

Shared: one system prompt that describes the tools generically; the document's front matter; max 12 calls.

- **ReAct-R (retrieval only)**
  - `search(query, k=5)`: the same chunk index and embedder as RAG.
  - `read_section(title)`: one node of the Navigation Map, rendered as text.
  - `list_sections(scope)`: the node titles under a scope (a table of contents).
  - `finish(answer_json)`.
- **ReAct-C (retrieval + code)**: all of the above plus
  - `python(code)`: runs in the **same sandbox** with the **same `doc` (Navigation Map) and helpers** as OTF's
    generated tools, and returns printed output.

  This is deliberate: ReAct-C gets everything OTF's tools get. The only differences are *when* code is written
  (every question vs once per document), whether it is *checked* against the record, and whether it is
  *reused*. That is exactly the claim the paper makes, so this comparison carries the most weight.

### 5.3 ReCode

- **Adapter**: a `docqa` environment that implements ReCode's `Env` contract (`reset`, `_run`, `is_done`,
  `is_success`, `report`). Observation: question + front matter + table of contents. Primitive actions
  (ReCode's `run(...)` calls): the same four tools as ReAct-C plus `answer(json)`.
- **Prompts and few-shots**: ReCode needs environment-specific prompts and few-shot examples. We write 2–3
  generic few-shots from **pilot20 questions only**, and list them in the appendix.
- **Hyperparameters**: the repository's examples use recursion depth 10–12 for embodied tasks; for document QA
  we pre-register **max depth 6** and the shared **12-call** cap per question, plus the frozen sampling settings.
- **Fairness note for the paper**: ReCode was designed for interactive environments, so an adapter is
  unavoidable. We use the repository's own structure, the same primitives as ReAct-C, and release the adapter.

---

## 6. OTF ablations that pair with the new baselines (cheap; reuse existing runs and artifacts)

| Ablation | How | Pairs with |
|---|---|---|
| **OTF reading-only** | Force the fallback path (map + scope reading, no tools) | GraphRAG, ReAct-R (Q1, Q2) |
| **OTF no-check** | Use the first generated simulator per document regardless of the forecast check | ReCode, ReAct-C (Q4) |
| **OTF no-divergence-replay** | Counterfactual tool simulates from time 0 instead of from the divergence point | Q10 |
| **OTF gold router** | Route with the true question type (upper bound on routing) | Router attack (already planned) |
| **OTF library off** | Each document generates its own model only (= the existing "OTF single pass" numbers) | Q5, Q7 |
| **OTF oracle model** | Hand-written simulator (already running as `otf_oracle`) | Upper bound for all |

---

## 7. Metrics and the analyses (tables and figures) they feed

Per system, model and question type, reported with 95% bootstrap CIs and paired differences against OTF:

1. **Accuracy** (question-level and option-level), overall and per type.
2. **Cost**: tokens per question; one-time setup tokens; amortized tokens per question; LLM calls and tool calls
   per question; wall-clock latency per question and for setup.
3. **Failure modes**: parse errors, call-cap exhaustion, code errors (ReAct-C, ReCode), JSON extraction failures
   (GraphRAG), OTF generation failures and fallback rate.

Planned figures and tables:

- **F1 Accuracy by type** for all systems (bars with CIs), one panel per model.
- **F2 Cost–accuracy frontier**: amortized tokens per question (log scale) vs accuracy. A reviewer wants to see
  that OTF is not bought with tokens.
- **F3 Break-even curve** (answers Q5): cumulative tokens vs number of questions on one document, for OTF
  (setup + per-question) and each baseline. The crossing point is the number of questions after which OTF's
  setup has paid for itself. Reported per model, with the actual questions-per-document marked.
- **F4 E1 → E2 degradation** (Q6): accuracy change from the 20-video documents to the 784-page document, per
  system, on the identical 1,067 counterfactual + explanatory questions.
- **F5 Paired differences, OTF minus each system** (forest plot), per question type.
- **F6 Overlap of correctly answered counterfactual questions** (UpSet plot): which questions only OTF solves,
  which only ReAct-C or ReCode solves. Followed by a short qualitative error analysis of 20 sampled
  disagreements.
- **T1 Code reliability** (Q3, Q4, Q7): share of questions where ReAct-C/ReCode wrote code that ran; share where it
  produced events at all; compared with OTF's per-document check pass rate and the check's F1.

---

## 8. Which runs, on which models (compute plan)

The GPU is fully booked by the current runs until about Oct 24–25. The new baselines can be **implemented and
tuned on pilot20** while those run (testing against whichever model is being served), and **run** afterwards.

Rough cost per run on gpt-oss-20b (the fastest model), full E1 (2,166 questions):

| Run | Estimated GPU hours (gpt-oss) | Basis |
|---|---|---|
| GraphRAG index, 15 E1 documents | 1–2 | ~5–8M extraction tokens |
| GraphRAG local search, E1 | ~1 | ~5–10k tokens per question |
| ReAct-R, E1 | ~2 | ~4–6 calls per question |
| ReAct-C, E1 | ~2.5 | as ReAct-R plus code |
| ReCode, E1 | 3–4 | ~8–10 calls per question |
| E2 (1,067 questions): GraphRAG index + local + global, ReAct-R, ReAct-C, ReCode | 8–12 | global search is map-reduce over all communities |

Gemma and Qwen are 4–8 times slower per question, so full E1 for them is not affordable before the deadline.

**Tiers (pre-registered):**

- **Tier A (must)**: gpt-oss-20b, all four new baselines on **full E1**, and on **E2**. About 20–25 GPU hours.
- **Tier B (if time)**: Gemma and Qwen on **E1-core**, a fixed subset of 5 of the 15 documents (`e1_d03, d06,
  d09, d12, d15`: every third, chosen by rule, not by results), about 720 questions including ~185
  counterfactual. OTF and the existing baselines already have results on these documents, so comparisons are
  paired. About 10 GPU hours per model.
- **Go/no-go**: on Oct 25 at 09:00, if fewer than 40 GPU hours remain before the Oct 27 evening freeze,
  Tier B runs for one model only (Qwen first: its baselines were strongest, so it is the hardest test for OTF).

---

## 9. Threats to validity we will state openly

- **One domain.** All documents come from CLEVRER. The benchmark-word guard and generic prompts reduce the risk
  of domain tuning, but a second domain is future work.
- **Adapters.** ReCode and GraphRAG were not built for this task; our wiring may not be what their authors would
  choose. Mitigation: defaults, equal tuning budget, released adapters.
- **Quantized models.** All three models run at 4-bit (NVFP4) or MXFP4 on one GPU; absolute numbers may differ from
  full-precision serving. Relative comparisons use identical serving for every system.
- **Order dependence of the tool library.** Which document generates first affects setup cost; the end-of-split
  re-check rule and the single-pass numbers bound this.

---

## 10. Implementation checklist (no changes to running experiments)

1. `clevrer_bench/systems/graphrag_system.py`: wrapper around `graphrag` (index + local/global query), LiteLLM
   meter for setup tokens, embedding endpoint for bge-small.
2. `clevrer_bench/systems/react_system.py`: ReAct loop with native tool calling; `variant=retrieve|code`.
3. `clevrer_bench/systems/recode_system.py` + `third_party/ReCode` (pinned) + `docqa` environment, prompts, few-shots
   from pilot20.
4. Register `graphrag`, `react_r`, `react_c`, `recode` as built-in systems so the orchestrator and reports treat them
   like the others.
5. Pilot20 smoke test and dev tuning (at most 3 variants each), then freeze everything in SPEC section 11.
6. Add the OTF ablation switches: reading-only, no-check, no-divergence-replay, gold router.
7. Add the new jobs to `scripts/resume_after_reboot.ps1` when they are launched (as independent processes, never in
  Claude terminal tabs).

### References
- Edge et al., *From Local to Global: A Graph RAG Approach to Query-Focused Summarization*, 2024; `microsoft/graphrag`.
- Yao et al., *ReAct: Synergizing Reasoning and Acting in Language Models*, ICLR 2023.
- Yu et al., *ReCode: Unify Plan and Action for Universal Granularity Control*, ICML 2026, arXiv:2510.23564;
  `github.com/FoundationAgents/ReCode` (MIT).
