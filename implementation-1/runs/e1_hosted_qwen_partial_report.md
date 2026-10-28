# CLEVRER document-QA benchmark: e1 (15 documents)

- Videos: 300 (validation split, seed 1), questions: 2166
- Document: `e1_d01 .. e1_d15` (798 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every 8 frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| otf | or-qwen3.6-27b | 2166/2166 | 0 | 74.88 | 82.93 | 1 |
| otf_reading_only | or-qwen3.6-27b | 2166/2166 | 0 | 73.68 | 80.80 | 1 |
| pageindex | or-qwen3.6-27b | 2166/2166 | 0 | 76.69 | 82.82 | 20 |
| full_context_text | or-qwen3.6-27b | 2166/2166 | 0 | 67.82 | 75.78 | 0 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 97.28 (n=882) | 84.67 / 61.21 (n=513) | 98.16 / 96.31 (n=217) | 71.65 / 43.50 (n=554) |
| otf_reading_only | 97.28 (n=882) | 84.40 / 61.01 (n=513) | 97.70 / 97.24 (n=217) | 66.48 / 38.63 (n=554) |
| pageindex | 98.19 (n=882) | 86.51 / 69.79 (n=513) | 93.78 / 93.09 (n=217) | 70.20 / 42.42 (n=554) |
| full_context_text | 96.71 (n=882) | 77.93 / 46.39 (n=513) | 85.02 / 84.79 (n=217) | 62.52 / 35.02 (n=554) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | or-qwen3.6-27b | 74.9 [73.0, 76.6] | 97.3 [96.2, 98.3] | 61.2 [56.9, 65.5] | 96.3 [93.5, 98.6] | 43.5 [39.4, 47.6] |
| otf_reading_only | or-qwen3.6-27b | 73.7 [71.8, 75.5] | 97.3 [96.2, 98.3] | 61.0 [56.9, 65.1] | 97.2 [94.9, 99.1] | 38.6 [34.7, 42.6] |
| pageindex | or-qwen3.6-27b | 76.7 [74.8, 78.5] | 98.2 [97.3, 99.0] | 69.8 [65.9, 73.5] | 93.1 [89.4, 96.3] | 42.4 [38.5, 46.8] |
| full_context_text | or-qwen3.6-27b | 67.8 [65.8, 69.8] | 96.7 [95.5, 97.8] | 46.4 [42.1, 51.1] | 84.8 [79.7, 89.4] | 35.0 [31.2, 38.8] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| or-qwen3.6-27b | otf vs otf_reading_only | +1.2 [-0.1, +2.5] p=0.029 | +0.0 [-0.6, +0.6] p=0.593 | +0.2 [-3.5, +3.9] p=0.487 | -0.9 [-4.2, +2.3] p=0.754 | +4.9 [+1.8, +7.8] p=0.001 |
| or-qwen3.6-27b | otf vs pageindex | -1.8 [-3.3, -0.3] p=0.994 | -0.9 [-1.9, +0.0] p=0.976 | -8.6 [-12.7, -4.9] p=1.000 | +3.2 [-0.5, +6.9] p=0.054 | +1.1 [-2.2, +4.3] p=0.288 |
| or-qwen3.6-27b | otf vs full_context_text | +7.1 [+5.8, +8.5] p=0.000 | +0.6 [-0.2, +1.4] p=0.088 | +14.8 [+11.3, +18.5] p=0.000 | +11.5 [+6.5, +17.1] p=0.000 | +8.5 [+5.2, +11.7] p=0.000 |

### Descriptive subtypes (accuracy %)

| System | count | exist | query_color | query_material | query_shape |
|---|---|---|---|---|---|
| otf | 94.46 | 96.36 | 100.00 | 100.00 | 100.00 |
| otf_reading_only | 95.08 | 95.76 | 99.32 | 100.00 | 100.00 |
| pageindex | 95.38 | 99.39 | 100.00 | 100.00 | 100.00 |
| full_context_text | 92.62 | 96.97 | 100.00 | 100.00 | 100.00 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 5,163.4 | 0.0 | 2,853.3 | 2,788.6 | 8,016.8 | 173,898 | 8,097.1 | 17,364,313 | 2.49 | 0.00 | 46.92 |
| otf_reading_only | 4,228.8 | 0.0 | 2,056.2 | 2,024.5 | 6,285.1 | 173,898 | 6,365.4 | 13,613,491 | 2.00 | 0.00 | 34.45 |
| pageindex | 28,627.1 | 0.0 | 4,071.7 | 3,955.6 | 32,698.8 | 2,194,480 | 33,711.9 | 70,825,602 | 0.00 | 0.00 | 80.69 |
| full_context_text | 68,398.2 | 0.0 | 2,039.4 | 2,020.2 | 70,437.6 | 0 | 70,437.6 | 152,567,796 | 1.00 | 0.00 | 42.16 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 4,913.0 | 12,596.5 | 5,522.7 | 9,694.3 |
| otf_reading_only | 4,918.5 | 6,879.8 | 6,069.4 | 7,994.5 |
| pageindex | 24,300.3 | 35,465.5 | 29,046.5 | 44,938.3 |
| full_context_text | 69,049.0 | 71,074.9 | 70,189.4 | 72,155.3 |

### Setup details

- **otf**: 173,898 tokens (89,422 in / 84,476 out, 10 calls), 2250.5s, info: `{"documents": 15}`
- **otf_reading_only**: 173,898 tokens (89,422 in / 84,476 out, 10 calls), 2250.5s, info: `{"documents": 15}`
- **pageindex**: 2,194,480 tokens (1,459,018 in / 735,462 out, 330 calls), 3063.7s, info: `{"documents": 15}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 2.3s, info: `{"documents": 15}`
