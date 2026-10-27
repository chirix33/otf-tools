# CLEVRER document-QA benchmark: itops (5 documents)

- Videos: 26 (validation split, seed None), questions: 300
- Document: `itops_d01 .. itops_d05` (240 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every None frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| otf | or-qwen3.6-27b | 300/300 | 0 | 48.67 | 71.18 | 0 |
| full_context_text | or-qwen3.6-27b | 300/300 | 0 | 43.00 | 64.72 | 0 |
| rag | or-qwen3.6-27b | 300/300 | 0 | 26.00 | 57.44 | 0 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 96.00 (n=75) | 64.33 / 26.67 (n=75) | 70.33 / 37.33 (n=75) | 72.67 / 34.67 (n=75) |
| full_context_text | 94.67 (n=75) | 57.00 / 22.67 (n=75) | 75.00 / 46.67 (n=75) | 54.67 / 8.00 (n=75) |
| rag | 42.67 (n=75) | 55.33 / 16.00 (n=75) | 62.00 / 25.33 (n=75) | 58.67 / 20.00 (n=75) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | or-qwen3.6-27b | 48.7 [43.3, 54.7] | 96.0 [90.7, 100.0] | 26.7 [17.3, 37.3] | 37.3 [26.7, 48.0] | 34.7 [24.0, 45.3] |
| full_context_text | or-qwen3.6-27b | 43.0 [37.0, 48.7] | 94.7 [89.3, 98.7] | 22.7 [13.3, 32.0] | 46.7 [36.0, 57.4] | 8.0 [2.7, 14.7] |
| rag | or-qwen3.6-27b | 26.0 [21.0, 31.0] | 42.7 [32.0, 53.3] | 16.0 [8.0, 24.0] | 25.3 [16.0, 36.0] | 20.0 [12.0, 29.3] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| or-qwen3.6-27b | otf vs full_context_text | +5.7 [+0.3, +11.0] p=0.022 | +1.3 [-4.0, +8.0] p=0.406 | +4.0 [-8.0, +16.0] p=0.301 | -9.3 [-21.3, +2.7] p=0.952 | +26.7 [+14.7, +38.7] p=0.000 |
| or-qwen3.6-27b | otf vs rag | +22.7 [+16.0, +29.7] p=0.000 | +53.3 [+42.7, +64.0] p=0.000 | +10.7 [-2.7, +22.7] p=0.070 | +12.0 [-1.3, +25.3] p=0.054 | +14.7 [+1.3, +28.0] p=0.025 |

### Descriptive subtypes (accuracy %)

| System | finish_time | first_machine | n_evictions | n_starts | running_on | wait |
|---|---|---|---|---|---|---|
| otf | 100.00 | 100.00 | 100.00 | 100.00 | 75.00 | 100.00 |
| full_context_text | 91.67 | 100.00 | 100.00 | 100.00 | 83.33 | 92.31 |
| rag | 41.67 | 69.23 | 92.31 | 16.67 | 25.00 | 7.69 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 30,929.7 | 0.0 | 4,710.2 | 4,622.6 | 35,639.9 | 115,244 | 36,024.1 | 10,691,984 | 2.51 | 0.00 | 85.70 |
| full_context_text | 69,065.0 | 0.0 | 6,270.5 | 6,246.5 | 75,335.5 | 0 | 75,335.5 | 22,600,648 | 1.00 | 0.00 | 125.03 |
| rag | 3,682.9 | 0.0 | 3,149.5 | 3,125.6 | 6,832.4 | 0 | 6,832.4 | 2,049,734 | 1.00 | 0.00 | 68.49 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 15,080.7 | 53,042.6 | 27,318.2 | 47,118.3 |
| full_context_text | 70,031.4 | 76,389.0 | 77,876.2 | 77,045.4 |
| rag | 6,156.5 | 6,281.0 | 7,944.5 | 6,947.7 |

### Setup details

- **otf**: 115,244 tokens (62,436 in / 52,808 out, 8 calls), 826.6s, info: `{"documents": 5}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.5s, info: `{"documents": 5}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 0.0s, info: `{"documents": 5}`
