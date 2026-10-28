# CLEVRER document-QA benchmark: e1 (15 documents)

- Videos: 300 (validation split, seed 1), questions: 2166
- Document: `e1_d01 .. e1_d15` (798 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every 8 frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 2166/2166 | 0 | 67.77 | 79.41 | 0 |
| full_context_text | or-gpt-oss-20b | 2166/2166 | 0 | 61.17 | 75.15 | 16 |
| rag | or-gpt-oss-20b | 2166/2166 | 0 | 49.08 | 68.19 | 7 |
| pageindex | or-gpt-oss-20b | 2166/2166 | 0 | 53.19 | 68.85 | 16 |
| otf_oracle | or-gpt-oss-20b | 2166/2166 | 0 | 76.64 | 85.26 | 2 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 96.60 (n=882) | 76.96 / 48.54 (n=513) | 72.35 / 57.60 (n=217) | 75.61 / 43.68 (n=554) |
| full_context_text | 95.35 (n=882) | 73.72 / 37.04 (n=513) | 55.99 / 26.73 (n=217) | 71.70 / 42.60 (n=554) |
| rag | 68.14 (n=882) | 73.45 / 40.16 (n=513) | 56.45 / 30.41 (n=217) | 65.88 / 34.30 (n=554) |
| pageindex | 89.34 (n=882) | 68.38 / 33.14 (n=513) | 49.77 / 12.44 (n=217) | 64.38 / 30.14 (n=554) |
| otf_oracle | 97.62 (n=882) | 83.59 / 62.96 (n=513) | 95.39 / 91.24 (n=217) | 79.13 / 50.18 (n=554) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 67.8 [65.7, 69.8] | 96.6 [95.3, 97.7] | 48.5 [44.2, 53.0] | 57.6 [51.1, 64.1] | 43.7 [39.7, 48.0] |
| full_context_text | or-gpt-oss-20b | 61.2 [59.1, 63.2] | 95.3 [93.9, 96.7] | 37.0 [32.9, 41.1] | 26.7 [20.7, 32.7] | 42.6 [38.5, 46.6] |
| rag | or-gpt-oss-20b | 49.1 [47.0, 51.1] | 68.1 [65.1, 71.2] | 40.2 [36.3, 44.4] | 30.4 [24.4, 36.9] | 34.3 [30.3, 38.5] |
| pageindex | or-gpt-oss-20b | 53.2 [51.0, 55.3] | 89.3 [87.3, 91.3] | 33.1 [29.2, 37.2] | 12.4 [8.3, 17.1] | 30.1 [26.5, 34.1] |
| otf_oracle | or-gpt-oss-20b | 76.6 [74.9, 78.3] | 97.6 [96.6, 98.5] | 63.0 [58.9, 67.1] | 91.2 [87.6, 94.9] | 50.2 [46.0, 54.5] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| or-gpt-oss-20b | otf vs full_context_text | +6.6 [+4.8, +8.4] p=0.000 | +1.2 [-0.3, +2.8] p=0.072 | +11.5 [+7.2, +15.8] p=0.000 | +30.9 [+22.6, +39.2] p=0.000 | +1.1 [-2.9, +4.9] p=0.306 |
| or-gpt-oss-20b | otf vs rag | +18.7 [+16.5, +21.0] p=0.000 | +28.5 [+25.2, +31.6] p=0.000 | +8.4 [+4.3, +12.7] p=0.000 | +27.2 [+18.4, +35.5] p=0.000 | +9.4 [+5.6, +13.4] p=0.000 |
| or-gpt-oss-20b | otf vs pageindex | +14.6 [+12.7, +16.3] p=0.000 | +7.3 [+5.2, +9.3] p=0.000 | +15.4 [+11.7, +19.7] p=0.000 | +45.2 [+36.9, +53.0] p=0.000 | +13.5 [+9.6, +17.3] p=0.000 |
| or-gpt-oss-20b | otf vs otf_oracle | -8.9 [-10.8, -7.0] p=1.000 | -1.0 [-2.4, +0.2] p=0.951 | -14.4 [-19.3, -9.6] p=1.000 | -33.6 [-41.0, -26.3] p=1.000 | -6.5 [-10.5, -2.5] p=0.999 |

### Descriptive subtypes (accuracy %)

| System | count | exist | query_color | query_material | query_shape |
|---|---|---|---|---|---|
| otf | 93.23 | 96.97 | 99.32 | 100.00 | 98.51 |
| full_context_text | 93.23 | 95.15 | 98.64 | 97.30 | 95.52 |
| rag | 60.92 | 70.91 | 71.43 | 70.27 | 76.87 |
| pageindex | 80.31 | 91.52 | 96.60 | 97.30 | 94.03 |
| otf_oracle | 96.62 | 97.58 | 100.00 | 98.20 | 97.01 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 3,717.9 | 1,213.1 | 969.0 | 969.7 | 4,686.8 | 9,952,795 | 9,281.8 | 10,151,662 | 2.00 | 0.00 | 7.32 |
| full_context_text | 56,357.6 | 47,346.6 | 2,359.7 | 2,252.9 | 58,717.4 | 0 | 58,717.4 | 127,181,850 | 1.00 | 0.00 | 25.68 |
| rag | 1,271.5 | 346.4 | 736.0 | 811.8 | 2,007.6 | 0 | 2,007.6 | 4,348,401 | 1.00 | 0.00 | 12.07 |
| pageindex | 13,918.9 | 3,834.0 | 861.9 | 906.0 | 14,780.8 | 1,537,892 | 15,490.8 | 32,015,219 | 0.00 | 0.00 | 27.38 |
| otf_oracle | 2,494.5 | 993.7 | 1,356.9 | 1,435.8 | 3,851.4 | 0 | 3,851.4 | 8,342,049 | 2.48 | 0.00 | 11.64 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 3,934.6 | 4,836.4 | 4,887.8 | 5,667.2 |
| full_context_text | 56,966.9 | 58,273.1 | 59,093.6 | 61,768.3 |
| rag | 1,629.3 | 2,150.9 | 1,999.1 | 2,480.4 |
| pageindex | 16,002.4 | 12,663.8 | 13,385.4 | 15,342.9 |
| otf_oracle | 3,932.7 | 4,981.3 | 1,431.0 | 3,623.6 |

### Setup details

- **otf**: 9,952,795 tokens (8,873,694 in / 1,079,101 out, 704 calls), 8746.0s, info: `{"documents": 15}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.9s, info: `{"documents": 15}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 0.0s, info: `{"documents": 15}`
- **pageindex**: 1,537,892 tokens (1,280,062 in / 257,830 out, 330 calls), 754.3s, info: `{"documents": 15}`
- **otf_oracle**: 0 tokens (0 in / 0 out, 0 calls), 28.2s, info: `{"documents": 15}`
