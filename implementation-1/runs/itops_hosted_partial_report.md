# CLEVRER document-QA benchmark: itops (5 documents)

- Videos: 26 (validation split, seed None), questions: 300
- Document: `itops_d01 .. itops_d05` (240 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every None frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 300/300 | 0 | 27.67 | 57.13 | 0 |
| full_context_text | or-gpt-oss-20b | 300/300 | 0 | 18.33 | 35.38 | 101 |
| rag | or-gpt-oss-20b | 300/300 | 0 | 16.67 | 54.05 | 0 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 76.00 (n=75) | 54.33 / 4.00 (n=75) | 63.33 / 25.33 (n=75) | 49.00 / 5.33 (n=75) |
| full_context_text | 40.00 (n=75) | 34.00 / 5.33 (n=75) | 41.00 / 24.00 (n=75) | 30.00 / 4.00 (n=75) |
| rag | 32.00 (n=75) | 54.00 / 8.00 (n=75) | 61.33 / 21.33 (n=75) | 52.33 / 5.33 (n=75) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 27.7 [22.7, 33.0] | 76.0 [66.7, 85.3] | 4.0 [0.0, 9.3] | 25.3 [16.0, 34.7] | 5.3 [1.3, 10.7] |
| full_context_text | or-gpt-oss-20b | 18.3 [14.0, 22.7] | 40.0 [29.3, 50.7] | 5.3 [1.3, 10.7] | 24.0 [14.7, 34.7] | 4.0 [0.0, 9.3] |
| rag | or-gpt-oss-20b | 16.7 [12.3, 20.7] | 32.0 [21.3, 42.7] | 8.0 [2.7, 14.7] | 21.3 [12.0, 30.7] | 5.3 [1.3, 10.7] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| or-gpt-oss-20b | otf vs full_context_text | +9.3 [+4.3, +14.3] p=0.000 | +36.0 [+24.0, +48.0] p=0.000 | -1.3 [-8.0, +5.3] p=0.710 | +1.3 [-10.7, +13.3] p=0.456 | +1.3 [-4.0, +6.7] p=0.399 |
| or-gpt-oss-20b | otf vs rag | +11.0 [+6.0, +16.0] p=0.000 | +44.0 [+30.7, +57.3] p=0.000 | -4.0 [-10.7, +2.7] p=0.922 | +4.0 [-6.7, +13.3] p=0.266 | +0.0 [-5.3, +5.3] p=0.599 |

### Descriptive subtypes (accuracy %)

| System | finish_time | first_machine | n_evictions | n_starts | running_on | wait |
|---|---|---|---|---|---|---|
| otf | 58.33 | 92.31 | 100.00 | 75.00 | 58.33 | 69.23 |
| full_context_text | 25.00 | 46.15 | 69.23 | 50.00 | 33.33 | 15.38 |
| rag | 25.00 | 46.15 | 92.31 | 8.33 | 8.33 | 7.69 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 9,450.7 | 2,286.0 | 4,963.4 | 4,450.4 | 14,414.2 | 1,241,923 | 18,553.9 | 4,324,252 | 2.22 | 0.00 | 32.30 |
| full_context_text | 44,045.4 | 19,693.3 | 11,072.8 | 9,677.2 | 55,118.1 | 0 | 55,118.1 | 16,535,439 | 1.00 | 0.00 | 138.88 |
| rag | 2,639.3 | 309.5 | 1,915.5 | 1,812.0 | 4,554.9 | 0 | 4,554.9 | 1,366,457 | 1.00 | 0.00 | 43.77 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 10,812.3 | 15,981.4 | 14,308.7 | 16,554.3 |
| full_context_text | 50,665.6 | 56,694.4 | 56,239.5 | 56,873.1 |
| rag | 3,405.9 | 4,172.7 | 5,372.0 | 5,268.7 |

### Setup details

- **otf**: 1,241,923 tokens (1,079,529 in / 162,394 out, 92 calls), 1165.2s, info: `{"documents": 5}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.5s, info: `{"documents": 5}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 18.7s, info: `{"documents": 5}`
