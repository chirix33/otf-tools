# OTF Tier B baselines: all results and analysis

**Benchmark:** CLEVRER document QA, E1-core test set (`e1_d03, e1_d06, e1_d09, e1_d12, e1_d15`), 694 questions over 100 videos.
**Models:** Qwen3.6-27B, gpt-oss-20b, Gemma-4-31B (thinking).
**Systems:** ReAct-R, ReAct-C, GraphRAG, ReCode.
**Status:** 10 of the 12 model-system runs are complete. Gemma's GraphRAG and ReCode are partial because they were cut off at the 3 PM CDT deadline on Oct 28.

The other files in this folder:
- `TIER_B_RESULTS.md`: the automatically generated tables for the complete runs.
- `FINDINGS.md`: the earlier write-up for Qwen and gpt-oss.
- `analysis_data.json`: every number in this file, as machine-readable data.

---

## 1. Summary

1. **A simple tool-using agent is the strongest baseline on every model.**
   - Qwen and Gemma both reach about 80% with ReAct-C and ReAct-R; gpt-oss reaches about 50%.
   - GraphRAG and ReCode trail by 20–35 points on Qwen and gpt-oss.
2. **Gemma and Qwen are tied; gpt-oss is far behind.**
   - Gemma vs Qwen on ReAct: no significant difference (p = 0.40–0.67).
   - gpt-oss is 27–32 points lower on ReAct (p < 0.001).
3. **Counterfactual questions are the ceiling for every model and system.**
   - The best score is 44.9% (Gemma ReAct-C).
   - 72 of the 185 counterfactual questions are solved by none of the 10 complete runs.
4. **The model matters most for ReCode.** Accuracy ranges from 9% (gpt-oss) to 50–60% (Gemma, Qwen).
5. **gpt-oss's deficit is partly formatting:** 10–47% of its answers are not valid answer objects, against 0.4–1.9% for Qwen and Gemma on ReAct and GraphRAG.
6. **GraphRAG is expensive and weak.**
   - Indexing costs 15–23M tokens over the five documents.
   - With Gemma it matches Qwen (48% vs 44% on the same questions), and entity extraction never failed (0 of 205 chunks).
7. **Costs differ enormously.** The whole Tier B budget at list prices was about $156 for Qwen (hosted runs), $4.50 for gpt-oss and $10.70 for Gemma.

---

## 2. What was run

| Model alias | Model | Served by | Systems |
|---|---|---|---|
| `qwen3.6-27b` | Qwen3.6-27B (NVFP4) | local RTX 5090, vLLM 0.32 | ReAct-C |
| `or-qwen3.6-27b` | Qwen3.6-27B | OpenRouter, provider Alibaba | ReAct-R, GraphRAG, ReCode |
| `or-gpt-oss-20b` | gpt-oss-20b (MXFP4) | OpenRouter, provider CoreWeave | all four |
| `or-gemma-4-31b-think` | Gemma-4-31B-it, thinking on (bf16) | OpenRouter, provider Crusoe | all four |

**Systems:**
- **ReAct-R:** a native tool-calling agent with tools to list sections, read sections, search, and finish.
- **ReAct-C:** ReAct-R plus a sandboxed Python tool.
- **GraphRAG 3.3.0:** a knowledge-graph index, then local search.
- **ReCode** (commit 6e7223f): a recursive code agent that runs its code in the OTF sandbox.

**Shared rules:**
- at most 12 model calls per question;
- at most 16,384 output tokens per call;
- frozen sampling settings from `configs/models.json`;
- the same answer contract and scorer as Tier A.

**Selection protocol:**
- **Qwen and gpt-oss:** each system had up to 3 predefined settings ("slots"), each run on all 308 pilot20 questions. The winner (accuracy, then fewer tokens) was frozen with a config hash before any E1 question.
- **Gemma (deviation):** no pilot20 stage. Each system reused the slot frozen for Qwen. The Gemma freeze files record the reused slot, Qwen's config hash and Gemma's own config hash.

### Completion status

| Model | ReAct-C | ReAct-R | GraphRAG | ReCode |
|---|---|---|---|---|
| Qwen | 694/694 | 694/694 | 694/694 | 694/694 |
| gpt-oss | 694/694 | 694/694 | 694/694 | 694/694 |
| Gemma | 694/694 | 694/694 | **428/694** (d03, d06, d09; d12 indexed only) | **314/694** (d03, d06, 33 of d09) |

---

## 3. Main results: full E1-core (694 questions)

Question accuracy counts a multiple-choice question as right only if every option is right. The 95% CIs are bootstrap intervals. Cost is at OpenRouter list prices; the local run has no API cost.

| System | Model | Accuracy % [95% CI] | Option acc. % | Invalid answers | Tokens / q | Calls / q | API cost (E1) |
|---|---|---|---|---|---|---|---|
| ReAct-C | Qwen (local) | **81.0** [78.0, 83.7] | 82.8 | 48 | 20,772 | 5.1 | local |
| ReAct-C | Gemma | **79.8** [76.8, 82.8] | 84.9 | 4 | 17,124 | 5.7 | $2.33 |
| ReAct-R | Gemma | **79.8** [76.8, 82.7] | 85.2 | 3 | 16,184 | 6.0 | $2.18 |
| ReAct-R | Qwen | **79.2** [76.1, 82.1] | 86.5 | 4 | 16,627 | 5.0 | $13.22 |
| ReCode | Qwen | 59.9 [56.3, 63.4] | 69.9 | 70 | 35,041 | 5.0 | $28.06 |
| ReAct-C | gpt-oss | 52.5 [49.0, 56.3] | 65.8 | 71 | 10,815 | 6.0 | $0.30 |
| ReAct-R | gpt-oss | 47.4 [43.5, 51.1] | 59.1 | 124 | 11,087 | 6.8 | $0.30 |
| GraphRAG | Qwen | 46.5 [42.8, 50.1] | 63.5 | 13 | 14,549 (+ indexing) | 1.0 | $49.04 |
| GraphRAG | gpt-oss | 16.1 [13.4, 19.0] | 32.9 | 151 | 11,419 (+ indexing) | 1.0 | $1.39 |
| ReCode | gpt-oss | 9.4 [7.2, 11.4] | 27.1 | 323 | 11,548 | 2.0 | $0.52 |
| *GraphRAG* | *Gemma, partial* | *48.4 on 428 answered* | *68.7* | *9* | *14,113 (+ indexing)* | *1.0* | *$3.72* |
| *ReCode* | *Gemma, partial* | *50.3 on 314 answered* | *45.1* | *117* | *38,489* | – | *$2.50* |

The partial rows are not comparable with the full-set rows. Use section 4 to compare them.

### Model × system matrix (accuracy %)

| | ReAct-C | ReAct-R | GraphRAG | ReCode |
|---|---|---|---|---|
| Qwen3.6-27B | 81.0 | 79.2 | 46.5 | 59.9 |
| Gemma-4-31B | 79.8 | 79.8 | *48.4 (partial)* | *50.3 (partial)* |
| gpt-oss-20b | 52.5 | 47.4 | 16.1 | 9.4 |

---

## 4. Fair comparison of all 12 runs on the same 314 questions

Every run, including Gemma's two partial ones, answered the same 314 questions: all of e1_d03 and e1_d06, plus 33 from e1_d09. The mix is 126 descriptive, 76 explanatory, 30 predictive and 82 counterfactual. This is the only set on which all twelve runs can be ranked together.

| Rank | System | Model | Accuracy on the 314 % | Its full-set accuracy % |
|---|---|---|---|---|
| 1 | ReAct-C | Qwen (local) | 80.3 | 81.0 |
| 2 | ReAct-R | Qwen | 79.9 | 79.2 |
| 3 | ReAct-C | Gemma | 79.0 | 79.8 |
| 3 | ReAct-R | Gemma | 79.0 | 79.8 |
| 5 | ReCode | Qwen | 59.9 | 59.9 |
| 6 | ReAct-C | gpt-oss | 51.9 | 52.5 |
| 7 | ReCode | Gemma | 50.3 | (partial) |
| 8 | GraphRAG | Gemma | 49.4 | (partial) |
| 9 | ReAct-R | gpt-oss | 48.4 | 47.4 |
| 10 | GraphRAG | Qwen | 46.2 | 46.5 |
| 11 | GraphRAG | gpt-oss | 13.4 | 16.1 |
| 12 | ReCode | gpt-oss | 6.7 | 9.4 |

Accuracy on this subset is within about 3 points of each run's full-set accuracy, so it is representative.

### Same system, different model (paired exact McNemar test on the 314)

| System | Comparison | Difference (pts) | p |
|---|---|---|---|
| ReAct-C | Qwen vs Gemma | +1.3 | 0.58 (not significant) |
| ReAct-R | Qwen vs Gemma | +1.0 | 0.68 (not significant) |
| GraphRAG | Qwen vs Gemma | −3.2 | 0.32 (not significant) |
| ReCode | Qwen vs Gemma | **+9.6** | **0.004** |
| ReAct-C | Gemma vs gpt-oss | +27.1 | < 0.001 |
| ReAct-R | Gemma vs gpt-oss | +30.6 | < 0.001 |
| GraphRAG | Gemma vs gpt-oss | +36.0 | < 0.001 |
| ReCode | Gemma vs gpt-oss | +43.6 | < 0.001 |

Gemma vs Qwen on each partial run's own answered set:
- **GraphRAG** (428 questions): 48.4 vs 44.4, p = 0.15.
- **ReCode** (314 questions): 50.3 vs 59.9, p = 0.004.

### Same model, different system (full set for complete runs)

| Model | Comparison | Difference (pts) | p |
|---|---|---|---|
| Qwen | ReAct-C vs ReAct-R | +1.7 | 0.14 (not significant) |
| Gemma | ReAct-C vs ReAct-R | 0.0 | 1.00 (not significant) |
| gpt-oss | ReAct-C vs ReAct-R | +5.0 | 0.008 |

Every other comparison between systems within a model is significant (p < 0.001), except Gemma GraphRAG vs Gemma ReCode on the 314 questions (p = 0.86).

---

## 5. Accuracy by question type

Question accuracy %. The complete runs use all of E1-core (descriptive n = 271, explanatory 170, predictive 68, counterfactual 185). The partial runs use their answered questions.

| System | Model | Descriptive | Explanatory | Predictive | Counterfactual | Counterfactual, per option |
|---|---|---|---|---|---|---|
| ReAct-C | Qwen | 97.0 | **91.8** | 95.6 | 42.2 | 63.8 |
| ReAct-R | Qwen | 97.4 | 82.4 | **100.0** | 42.2 | **73.2** |
| GraphRAG | Qwen | 72.3 | 41.8 | 26.5 | 20.5 | 54.2 |
| ReCode | Qwen | 74.9 | 52.9 | 94.1 | 31.9 | 57.2 |
| ReAct-C | Gemma | **98.9** | 79.4 | **100.0** | **44.9** | 70.5 |
| ReAct-R | Gemma | **98.9** | 85.3 | 98.5 | 40.0 | 69.2 |
| GraphRAG | Gemma (partial) | 60.8 | 76.5 | 6.7 | 20.0 | 58.5 |
| ReCode | Gemma (partial) | 80.2 | 34.2 | 63.3 | 14.6 | 26.4 |
| ReAct-C | gpt-oss | 85.6 | 35.9 | 23.5 | 29.7 | 61.5 |
| ReAct-R | gpt-oss | 80.1 | 31.2 | 11.8 | 27.6 | 57.2 |
| GraphRAG | gpt-oss | 24.4 | 15.9 | 5.9 | 8.1 | 33.4 |
| ReCode | gpt-oss | 15.1 | 8.2 | 5.9 | 3.2 | 27.4 |

Observations:
- **Descriptive questions** (counting, existence, attributes) are nearly solved by ReAct on Qwen and Gemma (97–99%).
- **Explanatory and predictive questions** separate the models. Qwen and Gemma reach 79–100% with ReAct; gpt-oss only 12–36%.
- **Counterfactual questions** cap everyone at 40–45% question accuracy. Option-level accuracy is 64–73%, so systems get most options right but rarely all of them.
- **GraphRAG with Gemma** is unusually strong on explanatory questions (76.5%, against 41.8% for Qwen GraphRAG) and fails almost completely on predictive ones (6.7%).

---

## 6. Which questions nobody solves

- **Upper bound:** if a question counts as solved when any of the 10 complete runs got it, accuracy would be 89.2%.
  - By model, counting that model's complete runs only: Qwen 85.9%, Gemma (ReAct-C and ReAct-R only) 82.9%, gpt-oss 65.7%.
- **Solved by no complete run:** 75 questions (10.8%).
  - 72 are counterfactual, which is 39% of all 185 counterfactual questions.
  - The other 3 are explanatory.
- **On the 314 shared questions, with all 12 runs:**
  - 33 are solved by none of them (32 counterfactual).
  - Only 14 are solved by 11 of the 12 runs.

So counterfactual reasoning is the shared ceiling. Retrieving the right section is not the bottleneck; simulating the counterfactual outcome is.

---

## 7. Development selection and the Gemma reuse

| System | Qwen candidates on pilot20 (frozen slot in bold) | gpt-oss candidates on pilot20 (frozen in bold) | Gemma |
|---|---|---|---|
| ReAct-C | **slot 1: 89.9** (only one slot run) | 71.1 / 69.5 / **71.4** | reused Qwen slot 1 (hash `2237726337f8b1ab`), own hash `00e443b1b2e9eb99` |
| ReAct-R | **89.9** / 89.6 / 87.3 | 65.6 / 66.9 / **68.5** | reused slot 1 (`40fe3497f1479208`), own `5cdb2503547f526d` |
| GraphRAG | 20.5 / 21.8 / **57.8** | 13.6 / 12.3 / **28.2** | reused slot 3 with Qwen's tuned prompts (`993f8f4f498ff189`), own `319ed863e10a70f8` |
| ReCode | 66.6 / 69.8 / **72.7** | 8.8 / 12.3 / **16.6** | reused slot 3 (`a85015f55f974ee3`), own `5f5d068874d5dc93` |

- **Settings barely matter for ReAct** (within 2–3 points). Prompt auto-tuning is the one change that matters a lot: GraphRAG's slot 3 roughly doubles dev accuracy on both models.
- **The dev-to-E1 drop is explained by question mix.** The frozen settings scored 7–21 points higher on pilot20 than on E1-core, and almost all of that is pilot20 being easier:
  - pilot20 is 71% descriptive questions, E1-core 39%;
  - weighting the pilot20 per-type accuracy to E1-core's mix predicts the E1 score to within 0–4 points.
- **Gemma reuse:** reusing Qwen's choices was reasonable for ReAct. The ReAct settings hardly differ on any model, and Gemma's ReAct scores match Qwen's.

---

## 8. GraphRAG indexing

| Model | Index method | E1-core extraction failures | Indexing tokens (5 docs) |
|---|---|---|---|
| Qwen | standard | 0 / 257 chunks (0.0%) | 22.7M |
| gpt-oss | standard | 0 / 257 chunks (0.0%) | 15.4M |
| Gemma | standard (reused; pilot20 check not run) | **0 / 205 chunks (0.0%)** over d03, d06, d09, d12; d15 not indexed | (partial) |

- Extraction never failed, so standard indexing held for every model, including Gemma with Qwen's tuned prompts.
- Even so, GraphRAG's entity/relationship summaries lose the frame-level detail the questions need. gpt-oss GraphRAG answered "unknown" to 37% of questions.

---

## 9. Cost, efficiency and throughput

| | Qwen (hosted runs) | gpt-oss | Gemma |
|---|---|---|---|
| Price per million tokens (input / output) | $0.45 / $2.70 | $0.03 / $0.13 | $0.14 / $0.40 |
| Whole Tier B budget at list prices | $156 (dev + indexing + E1) | $4.50 (dev + indexing + E1) | $10.70 (E1 only, no dev) |
| Best system: cost per 1,000 correct answers | $24 (ReAct-R) | $0.81 (ReAct-C) | $3.94 (ReAct-R) |
| Rate-limit refusals (429), retried and never scored | 0 | 0 | 15,777 |

- **Gemma is the best value:** Qwen-level accuracy at about a sixth of Qwen's cost per correct answer.
- **But Gemma was slow:** Crusoe's rate limits pushed ReAct latency to 2–4 minutes per question, and that is why GraphRAG and ReCode missed the deadline.
- **Token efficiency:** ReAct is the cheapest per correct answer on every model (about 20–26k tokens). GraphRAG (101–208k, because of indexing) and ReCode (58–123k) are much more expensive.

---

## 10. Failure modes

| System | Model | Invalid answers | Main kind | Other outcomes |
|---|---|---|---|---|
| ReAct-C | Qwen (local) | 48 (6.9%) | 35 cut off at the 16,384-token cap | – |
| ReAct-R | Qwen | 4 (0.6%) | – | – |
| ReAct-C / ReAct-R | Gemma | 4 / 3 (0.5%) | – | answers mostly as a plain reply instead of the finish tool (571 and 512 of 694); scored normally |
| ReAct-C / ReAct-R | gpt-oss | 71 / 124 (10–18%) | empty replies, wrong answer format | 28 hit the 12-call cap (ReAct-R) |
| GraphRAG | gpt-oss | 151 (22%) | multiple-choice questions answered in the free-text format | 256 "unknown" answers |
| ReCode | Qwen | 70 (10%) | no answer submitted | 6 hit the call cap |
| ReCode | Gemma (partial) | 117 of 314 (37%) | 108 ended with no answer | 9 hit the call cap |
| ReCode | gpt-oss | 323 (47%) | 280 ended with no answer | guesses before reading |

ReCode is fragile. When the generated code crashes, or the model fills in an answer before looking at what it read, the agent ends without a usable answer. Qwen avoids this best, Gemma about half as well, and gpt-oss almost never.

---

## 11. Conclusions for the paper

- **Strongest baseline:** a tool-using ReAct agent, with about 80% on Qwen and Gemma and about 50% on gpt-oss. Adding a Python tool (ReAct-C) gives at most a small gain (0–5 points).
- **More complex pipelines don't pay off on this document type.** GraphRAG and ReCode are weaker and much more expensive per correct answer.
- **Counterfactual questions remain unsolved:** at most 45% question accuracy, and 39% of them are answered by no baseline. This is the clearest target for a simulation-based method such as OTF.
- **Model choice matters as much as system choice.** Gemma and Qwen are statistically tied on ReAct. gpt-oss is 27–32 points behind, partly because of formatting failures.

---

## 12. Caveats and deviations

1. **Mixed serving for Qwen:** ReAct-C ran on the local GPU (NVFP4, vLLM); the other Qwen systems ran on OpenRouter (Alibaba). Latency is not comparable across these setups.
2. **Gemma had no pilot20 selection** (agreed deviation). It reused Qwen's frozen slots, recorded in `freeze/*__or-gemma-4-31b-think.json`, and ran on E1-core only.
3. **Gemma's GraphRAG and ReCode are partial** because of the Oct 28 3 PM CDT cutoff. Compare them only on matched questions (section 4).
4. **Gemma ran into heavy rate limiting:** 15,777 requests were refused with 429. Each was retried with backoff and logged as `rate_limited` in `calls.jsonl`; none was scored.
5. **Two robustness fixes on Oct 26, before gpt-oss's dev stage, also used for Gemma:**
   - A reply that OpenRouter marks as a provider failure is now retried instead of scored. Qwen had none of these.
   - A ReAct finish call without its required answer argument now gets an error back, so the model can try again. Qwen hit this once (one ReAct-C question; at most 0.14 points).
6. **GraphRAG token correction:** 1,848 Qwen GraphRAG rows (mostly pilot20) were corrected for reasoning tokens that LiteLLM's streaming path had dropped. Answers were unaffected.
7. **Costs** are list-price estimates from the call logs. A spot check matched actual OpenRouter charges exactly.

---

## 13. Files in this folder

| Path | Contents |
|---|---|
| `ALL_RESULTS.md` | This analysis |
| `analysis_data.json` | Every statistic in this file |
| `TIER_B_RESULTS.md` | Generated tables for the complete runs: CIs, per-document results, tests, costs, failure modes |
| `FINDINGS.md` | Earlier write-up for Qwen and gpt-oss, with a Gemma addendum |
| `reports/` | The benchmark's own reports (`e1_report.md/.json`, per document), `DELIVERY.md`, `delivery_manifest.json` |
| `e1/<doc>/<system>__<model>/` | `predictions.jsonl` (answer, score, usage, full trace), `calls.jsonl` (every model call, including refused ones), `setup.json` |
| `dev/pilot20/<system>_c<slot>__<model>/` | Every development candidate for Qwen and gpt-oss |
| `freeze/` | Frozen selections for all three models (Gemma's with `reused_from`), GraphRAG decisions, tuned GraphRAG prompts, the SPEC sec. 11 block |
| `provenance.json`, `timing.json` | Code commit, dependency versions, providers and checkpoints; wall-clock time per stage |
| `SHA256SUMS.txt` | Checksums of every file |
