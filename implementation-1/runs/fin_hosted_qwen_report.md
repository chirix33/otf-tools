# CLEVRER document-QA benchmark: fin (3 documents)

- Videos: 274 (validation split, seed None), questions: 300
- Document: `fin_d01 .. fin_d03` (303 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every None frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| otf | or-qwen3.6-27b | 300/300 | 0 | 83.67 | 83.67 | 0 |
| full_context_text | or-qwen3.6-27b | 300/300 | 0 | 82.67 | 82.67 | 0 |
| rag | or-qwen3.6-27b | 300/300 | 0 | 76.33 | 76.33 | 0 |
| pageindex | or-qwen3.6-27b | 300/300 | 0 | 83.00 | 83.00 | 0 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 85.33 (n=150) | - | - | 82.00 / 82.00 (n=150) |
| full_context_text | 86.00 (n=150) | - | - | 79.33 / 79.33 (n=150) |
| rag | 75.33 (n=150) | - | - | 77.33 / 77.33 (n=150) |
| pageindex | 84.67 (n=150) | - | - | 81.33 / 81.33 (n=150) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | or-qwen3.6-27b | 83.7 [79.7, 88.0] | 85.3 [79.3, 90.7] | - | - | 82.0 [76.0, 88.0] |
| full_context_text | or-qwen3.6-27b | 82.7 [78.0, 86.7] | 86.0 [80.7, 91.3] | - | - | 79.3 [72.7, 86.0] |
| rag | or-qwen3.6-27b | 76.3 [71.3, 81.3] | 75.3 [68.0, 82.0] | - | - | 77.3 [70.7, 83.3] |
| pageindex | or-qwen3.6-27b | 83.0 [78.7, 87.0] | 84.7 [78.7, 90.0] | - | - | 81.3 [74.7, 87.3] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| or-qwen3.6-27b | otf vs full_context_text | +1.0 [-2.0, +4.0] p=0.308 | -0.7 [-4.7, +2.7] p=0.699 | - | - | +2.7 [-1.3, +7.3] p=0.152 |
| or-qwen3.6-27b | otf vs rag | +7.3 [+3.0, +11.7] p=0.001 | +10.0 [+4.0, +15.3] p=0.001 | - | - | +4.7 [-1.3, +10.7] p=0.080 |
| or-qwen3.6-27b | otf vs pageindex | +0.7 [-2.7, +4.0] p=0.394 | +0.7 [-3.3, +5.3] p=0.444 | - | - | +0.7 [-4.7, +6.0] p=0.455 |

### Descriptive subtypes (accuracy %)

| System | arithmetic | count | multi-span | span |
|---|---|---|---|---|
| otf | 86.51 | 87.50 | 50.00 | 78.57 |
| full_context_text | 85.71 | 87.50 | 100.00 | 85.71 |
| rag | 76.19 | 75.00 | 50.00 | 71.43 |
| pageindex | 84.13 | 87.50 | 100.00 | 85.71 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 1,325.3 | 0.0 | 1,816.9 | 1,783.5 | 3,142.1 | 607,636 | 5,167.6 | 942,644 | 2.00 | 0.00 | 31.24 |
| full_context_text | 50,655.1 | 0.0 | 1,438.3 | 1,417.6 | 52,093.5 | 0 | 52,093.5 | 15,628,038 | 1.00 | 0.00 | 43.65 |
| rag | 1,390.7 | 0.0 | 1,561.8 | 1,541.2 | 2,952.6 | 0 | 2,952.6 | 885,766 | 1.00 | 0.00 | 24.79 |
| pageindex | 65,088.7 | 0.0 | 1,081.2 | 966.2 | 66,169.9 | 1,222,921 | 70,246.3 | 19,850,963 | 0.00 | 0.00 | 27.10 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 2,850.8 | - | - | 3,433.5 |
| full_context_text | 51,892.8 | - | - | 52,294.1 |
| rag | 2,658.3 | - | - | 3,246.8 |
| pageindex | 65,076.2 | - | - | 67,263.5 |

### Setup details

- **otf**: 607,636 tokens (361,981 in / 245,655 out, 34 calls), 4204.4s, info: `{"documents": 3}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.5s, info: `{"documents": 3}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 43.6s, info: `{"documents": 3}`
- **pageindex**: 1,222,921 tokens (350,667 in / 872,254 out, 276 calls), 491.2s, info: `{"documents": 3}`
