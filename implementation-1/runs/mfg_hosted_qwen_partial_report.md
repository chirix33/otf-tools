# CLEVRER document-QA benchmark: mfg (5 documents)

- Videos: 56 (validation split, seed None), questions: 300
- Document: `mfg_d01 .. mfg_d05` (257 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every None frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| otf | or-qwen3.6-27b | 300/300 | 0 | 64.33 | 83.82 | 0 |
| otf_reading_only | or-qwen3.6-27b | 300/300 | 0 | 74.67 | 88.80 | 1 |
| full_context_text | or-qwen3.6-27b | 300/300 | 0 | 79.00 | 91.29 | 0 |
| pageindex | or-qwen3.6-27b | 149/300 | 94 | 85.23 | 82.25 | 16 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 98.67 (n=75) | 75.00 / 29.33 (n=75) | 88.24 / 70.67 (n=75) | 84.67 / 58.67 (n=75) |
| otf_reading_only | 97.33 (n=75) | 89.33 / 70.67 (n=75) | 86.85 / 66.67 (n=75) | 88.00 / 64.00 (n=75) |
| full_context_text | 100.00 (n=75) | 88.67 / 64.00 (n=75) | 91.35 / 78.67 (n=75) | 91.67 / 73.33 (n=75) |
| pageindex | 100.00 (n=64) | 83.33 / 77.78 (n=27) | 85.29 / 80.00 (n=35) | 64.13 / 60.87 (n=23) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | or-qwen3.6-27b | 64.3 [58.7, 69.7] | 98.7 [96.0, 100.0] | 29.3 [20.0, 40.0] | 70.7 [60.0, 80.0] | 58.7 [48.0, 70.7] |
| otf_reading_only | or-qwen3.6-27b | 74.7 [69.7, 79.3] | 97.3 [93.3, 100.0] | 70.7 [60.0, 81.3] | 66.7 [56.0, 77.3] | 64.0 [53.3, 74.7] |
| full_context_text | or-qwen3.6-27b | 79.0 [74.3, 83.7] | 100.0 [100.0, 100.0] | 64.0 [52.0, 74.7] | 78.7 [69.3, 88.0] | 73.3 [62.7, 82.7] |
| pageindex | or-qwen3.6-27b | 85.2 [79.2, 90.6] | 100.0 [100.0, 100.0] | 77.8 [62.9, 92.6] | 80.0 [65.7, 91.4] | 60.9 [39.1, 78.3] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| or-qwen3.6-27b | otf vs otf_reading_only | -10.3 [-16.0, -5.0] p=1.000 | +1.3 [+0.0, +4.0] p=0.375 | -41.3 [-56.0, -26.7] p=1.000 | +4.0 [-4.0, +10.7] p=0.205 | -5.3 [-16.0, +4.0] p=0.876 |
| or-qwen3.6-27b | otf vs full_context_text | -14.7 [-20.3, -9.0] p=1.000 | -1.3 [-4.0, +0.0] p=1.000 | -34.7 [-49.3, -20.0] p=1.000 | -8.0 [-20.0, +4.0] p=0.935 | -14.7 [-26.7, -4.0] p=0.996 |
| or-qwen3.6-27b | otf vs pageindex | -10.7 [-18.1, -2.7] p=0.998 | +0.0 [+0.0, +0.0] p=1.000 | -48.1 [-70.4, -25.9] p=1.000 | -8.6 [-25.7, +11.4] p=0.853 | +0.0 [-30.4, +30.4] p=0.555 |

### Descriptive subtypes (accuracy %)

| System | backordered | capacity_days | first_stockout | max_backlog | shipped | stock | stockout_products |
|---|---|---|---|---|---|---|---|
| otf | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 90.00 |
| otf_reading_only | 100.00 | 90.91 | 100.00 | 100.00 | 100.00 | 100.00 | 90.00 |
| full_context_text | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 |
| pageindex | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 19,123.0 | 0.0 | 4,431.3 | 4,343.5 | 23,554.3 | 429,995 | 24,987.6 | 7,066,290 | 2.50 | 0.00 | 75.72 |
| otf_reading_only | 8,202.8 | 0.0 | 3,863.4 | 3,826.7 | 12,066.2 | 429,995 | 13,499.5 | 3,619,853 | 2.00 | 0.00 | 60.17 |
| full_context_text | 82,138.8 | 0.0 | 4,017.2 | 3,993.1 | 86,156.0 | 0 | 86,156.0 | 25,846,814 | 1.00 | 0.00 | 80.62 |
| pageindex | 61,098.6 | 0.0 | 15,220.3 | 15,052.8 | 76,318.9 | 1,061,796 | 83,445.0 | 11,371,516 | 0.00 | 0.00 | 273.02 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 9,170.8 | 35,065.2 | 23,733.3 | 26,247.9 |
| otf_reading_only | 9,162.7 | 12,235.0 | 14,071.1 | 12,795.9 |
| full_context_text | 82,725.4 | 85,457.5 | 88,868.1 | 87,573.2 |
| pageindex | 36,017.0 | 96,247.3 | 100,735.9 | 127,912.8 |

### Setup details

- **otf**: 429,995 tokens (289,035 in / 140,960 out, 23 calls), 2186.5s, info: `{"documents": 5}`
- **otf_reading_only**: 429,995 tokens (289,035 in / 140,960 out, 23 calls), 2186.5s, info: `{"documents": 5}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 1.5s, info: `{"documents": 5}`
- **pageindex**: 1,061,796 tokens (575,329 in / 486,467 out, 194 calls), 1583.0s, info: `{"documents": 5}`
