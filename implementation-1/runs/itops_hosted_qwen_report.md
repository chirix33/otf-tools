# CLEVRER document-QA benchmark: itops (5 documents)

- Videos: 26 (validation split, seed None), questions: 300
- Document: `itops_d01 .. itops_d05` (240 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every None frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| otf | or-qwen3.6-27b | 300/300 | 0 | 52.33 | 73.54 | 0 |
| full_context_text | or-qwen3.6-27b | 300/300 | 0 | 43.00 | 64.72 | 0 |
| rag | or-qwen3.6-27b | 300/300 | 0 | 26.00 | 57.44 | 0 |
| pageindex | or-qwen3.6-27b | 290/300 | 2 | 46.55 | 63.21 | 26 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 96.00 (n=75) | 64.67 / 30.67 (n=75) | 74.67 / 45.33 (n=75) | 75.67 / 37.33 (n=75) |
| full_context_text | 94.67 (n=75) | 57.00 / 22.67 (n=75) | 75.00 / 46.67 (n=75) | 54.67 / 8.00 (n=75) |
| rag | 42.67 (n=75) | 55.33 / 16.00 (n=75) | 62.00 / 25.33 (n=75) | 58.67 / 20.00 (n=75) |
| pageindex | 97.33 (n=75) | 58.56 / 21.92 (n=73) | 69.44 / 51.39 (n=72) | 52.50 / 12.86 (n=70) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | or-qwen3.6-27b | 52.3 [47.0, 58.0] | 96.0 [90.7, 100.0] | 30.7 [20.0, 41.3] | 45.3 [34.7, 57.3] | 37.3 [26.7, 48.0] |
| full_context_text | or-qwen3.6-27b | 43.0 [37.0, 48.7] | 94.7 [89.3, 98.7] | 22.7 [13.3, 32.0] | 46.7 [36.0, 57.4] | 8.0 [2.7, 14.7] |
| rag | or-qwen3.6-27b | 26.0 [21.0, 31.0] | 42.7 [32.0, 53.3] | 16.0 [8.0, 24.0] | 25.3 [16.0, 36.0] | 20.0 [12.0, 29.3] |
| pageindex | or-qwen3.6-27b | 46.5 [40.3, 52.4] | 97.3 [93.3, 100.0] | 21.9 [12.3, 31.5] | 51.4 [38.9, 62.5] | 12.9 [5.7, 20.0] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| or-qwen3.6-27b | otf vs full_context_text | +9.3 [+3.7, +14.7] p=0.000 | +1.3 [-4.0, +8.0] p=0.406 | +8.0 [-5.3, +21.3] p=0.145 | -1.3 [-13.3, +9.3] p=0.655 | +29.3 [+17.3, +41.3] p=0.000 |
| or-qwen3.6-27b | otf vs rag | +26.3 [+19.7, +33.0] p=0.000 | +53.3 [+42.7, +64.0] p=0.000 | +14.7 [+1.3, +26.7] p=0.015 | +20.0 [+5.3, +34.7] p=0.002 | +17.3 [+4.0, +30.7] p=0.009 |
| or-qwen3.6-27b | otf vs pageindex | +7.2 [+1.4, +13.1] p=0.009 | -1.3 [-5.3, +2.7] p=0.812 | +9.6 [-5.5, +23.3] p=0.116 | -4.2 [-18.1, +9.7] p=0.761 | +25.7 [+14.3, +38.6] p=0.000 |

### Descriptive subtypes (accuracy %)

| System | finish_time | first_machine | n_evictions | n_starts | running_on | wait |
|---|---|---|---|---|---|---|
| otf | 100.00 | 100.00 | 100.00 | 100.00 | 75.00 | 100.00 |
| full_context_text | 91.67 | 100.00 | 100.00 | 100.00 | 83.33 | 92.31 |
| rag | 41.67 | 69.23 | 92.31 | 16.67 | 25.00 | 7.69 |
| pageindex | 100.00 | 100.00 | 92.31 | 100.00 | 91.67 | 100.00 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 40,577.4 | 0.0 | 5,263.5 | 5,174.5 | 45,841.0 | 115,244 | 46,225.1 | 13,752,293 | 2.51 | 0.00 | 92.93 |
| full_context_text | 69,065.0 | 0.0 | 6,270.5 | 6,246.5 | 75,335.5 | 0 | 75,335.5 | 22,600,648 | 1.00 | 0.00 | 125.03 |
| rag | 3,682.9 | 0.0 | 3,149.5 | 3,125.6 | 6,832.4 | 0 | 6,832.4 | 2,049,734 | 1.00 | 0.00 | 68.49 |
| pageindex | 55,242.2 | 0.0 | 32,371.3 | 32,181.2 | 87,613.5 | 913,094 | 90,762.1 | 25,407,927 | 0.00 | 0.00 | 507.37 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 15,080.7 | 67,330.7 | 40,683.1 | 60,269.4 |
| full_context_text | 70,031.4 | 76,389.0 | 77,876.2 | 77,045.4 |
| rag | 6,156.5 | 6,281.0 | 7,944.5 | 6,947.7 |
| pageindex | 32,227.9 | 115,492.9 | 81,945.8 | 123,710.7 |

### Setup details

- **otf**: 115,244 tokens (62,436 in / 52,808 out, 8 calls), 826.6s, info: `{"documents": 5}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.5s, info: `{"documents": 5}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 0.0s, info: `{"documents": 5}`
- **pageindex**: 913,094 tokens (622,442 in / 290,652 out, 126 calls), 2029.4s, info: `{"documents": 5}`
