# CLEVRER document-QA benchmark: mfg (5 documents)

- Videos: 56 (validation split, seed None), questions: 300
- Document: `mfg_d01 .. mfg_d05` (257 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every None frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| otf | or-qwen3.6-27b | 300/300 | 0 | 69.00 | 86.31 | 0 |
| full_context_text | or-qwen3.6-27b | 300/300 | 0 | 79.00 | 91.29 | 0 |
| rag | or-qwen3.6-27b | 300/300 | 0 | 27.33 | 66.49 | 0 |
| pageindex | or-qwen3.6-27b | 297/300 | 1 | 78.11 | 77.21 | 49 |
| otf_reading_only | or-qwen3.6-27b | 300/300 | 0 | 74.67 | 88.80 | 1 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 98.67 (n=75) | 83.00 / 48.00 (n=75) | 88.24 / 70.67 (n=75) | 84.67 / 58.67 (n=75) |
| full_context_text | 100.00 (n=75) | 88.67 / 64.00 (n=75) | 91.35 / 78.67 (n=75) | 91.67 / 73.33 (n=75) |
| rag | 37.33 (n=75) | 66.33 / 17.33 (n=75) | 62.28 / 14.67 (n=75) | 78.00 / 40.00 (n=75) |
| pageindex | 100.00 (n=75) | 80.33 / 74.67 (n=75) | 75.44 / 71.23 (n=73) | 69.93 / 66.22 (n=74) |
| otf_reading_only | 97.33 (n=75) | 89.33 / 70.67 (n=75) | 86.85 / 66.67 (n=75) | 88.00 / 64.00 (n=75) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | or-qwen3.6-27b | 69.0 [63.7, 74.3] | 98.7 [96.0, 100.0] | 48.0 [36.0, 60.0] | 70.7 [60.0, 80.0] | 58.7 [48.0, 70.7] |
| full_context_text | or-qwen3.6-27b | 79.0 [74.3, 83.7] | 100.0 [100.0, 100.0] | 64.0 [52.0, 74.7] | 78.7 [69.3, 88.0] | 73.3 [62.7, 82.7] |
| rag | or-qwen3.6-27b | 27.3 [22.3, 33.0] | 37.3 [26.7, 48.0] | 17.3 [9.3, 26.7] | 14.7 [6.7, 22.7] | 40.0 [28.0, 50.7] |
| pageindex | or-qwen3.6-27b | 78.1 [73.4, 82.8] | 100.0 [100.0, 100.0] | 74.7 [64.0, 84.0] | 71.2 [60.3, 80.8] | 66.2 [55.4, 77.0] |
| otf_reading_only | or-qwen3.6-27b | 74.7 [69.7, 79.3] | 97.3 [93.3, 100.0] | 70.7 [60.0, 81.3] | 66.7 [56.0, 77.3] | 64.0 [53.3, 74.7] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| or-qwen3.6-27b | otf vs full_context_text | -10.0 [-15.7, -4.7] p=1.000 | -1.3 [-4.0, +0.0] p=1.000 | -16.0 [-30.7, +0.0] p=0.982 | -8.0 [-20.0, +4.0] p=0.935 | -14.7 [-26.7, -4.0] p=0.996 |
| or-qwen3.6-27b | otf vs rag | +41.7 [+35.0, +48.3] p=0.000 | +61.3 [+50.7, +72.0] p=0.000 | +30.7 [+17.3, +44.0] p=0.000 | +56.0 [+42.7, +69.3] p=0.000 | +18.7 [+5.3, +30.7] p=0.004 |
| or-qwen3.6-27b | otf vs pageindex | -8.8 [-14.5, -2.7] p=0.998 | -1.3 [-4.0, +0.0] p=1.000 | -26.7 [-40.0, -13.3] p=1.000 | +0.0 [-12.3, +12.3] p=0.538 | -6.8 [-21.6, +6.8] p=0.847 |
| or-qwen3.6-27b | otf vs otf_reading_only | -5.7 [-11.3, -0.7] p=0.987 | +1.3 [+0.0, +4.0] p=0.375 | -22.7 [-38.7, -6.7] p=0.997 | +4.0 [-4.0, +10.7] p=0.205 | -5.3 [-16.0, +4.0] p=0.876 |

### Descriptive subtypes (accuracy %)

| System | backordered | capacity_days | first_stockout | max_backlog | shipped | stock | stockout_products |
|---|---|---|---|---|---|---|---|
| otf | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 90.00 |
| full_context_text | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 |
| rag | 54.55 | 45.45 | 54.55 | 50.00 | 9.09 | 9.09 | 40.00 |
| pageindex | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 |
| otf_reading_only | 100.00 | 90.91 | 100.00 | 100.00 | 100.00 | 100.00 | 90.00 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 19,123.7 | 0.0 | 4,545.0 | 4,455.5 | 23,668.7 | 429,995 | 25,102.0 | 7,100,612 | 2.50 | 0.00 | 75.34 |
| full_context_text | 82,138.8 | 0.0 | 4,017.2 | 3,993.1 | 86,156.0 | 0 | 86,156.0 | 25,846,814 | 1.00 | 0.00 | 80.62 |
| rag | 3,180.1 | 0.0 | 2,673.0 | 2,649.0 | 5,853.2 | 0 | 5,853.2 | 1,755,946 | 1.00 | 0.00 | 62.26 |
| pageindex | 67,716.0 | 0.0 | 19,218.9 | 19,018.3 | 86,934.9 | 1,061,796 | 90,510.0 | 25,819,668 | 0.00 | 0.00 | 314.63 |
| otf_reading_only | 8,202.8 | 0.0 | 3,863.4 | 3,826.7 | 12,066.2 | 429,995 | 13,499.5 | 3,619,853 | 2.00 | 0.00 | 60.17 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 9,170.8 | 35,522.8 | 23,733.3 | 26,247.9 |
| full_context_text | 82,725.4 | 85,457.5 | 88,868.1 | 87,573.2 |
| rag | 4,036.4 | 5,632.9 | 7,486.7 | 6,256.7 |
| pageindex | 36,309.6 | 90,946.4 | 118,251.5 | 103,285.3 |
| otf_reading_only | 9,162.7 | 12,235.0 | 14,071.1 | 12,795.9 |

### Setup details

- **otf**: 429,995 tokens (289,035 in / 140,960 out, 23 calls), 2186.5s, info: `{"documents": 5}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 1.5s, info: `{"documents": 5}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 0.0s, info: `{"documents": 5}`
- **pageindex**: 1,061,796 tokens (575,329 in / 486,467 out, 194 calls), 1583.0s, info: `{"documents": 5}`
- **otf_reading_only**: 429,995 tokens (289,035 in / 140,960 out, 23 calls), 2186.5s, info: `{"documents": 5}`
