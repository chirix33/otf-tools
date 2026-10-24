# CLEVRER document-QA benchmark: e1 (15 documents)

- Videos: 300 (validation split, seed 1), questions: 2166
- Document: `e1_d01 .. e1_d15` (798 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every 8 frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| full_context_text | gemma-4-31b-think | 2166/2166 | 0 | 80.75 | 86.27 | 0 |
| full_context_text | gpt-oss-20b | 2166/2166 | 0 | 60.02 | 74.31 | 17 |
| otf_oracle_v2 | gpt-oss-20b | 2166/2166 | 0 | 77.52 | 86.63 | 0 |
| otf_single | gpt-oss-20b | 2166/2166 | 0 | 71.51 | 81.91 | 1 |
| otf_v2 | gpt-oss-20b | 2166/2166 | 0 | 75.72 | 85.53 | 0 |
| pageindex | gemma-4-31b-think | 2166/2166 | 0 | 76.08 | 82.43 | 0 |
| pageindex | gpt-oss-20b | 2166/2166 | 0 | 52.31 | 68.71 | 6 |
| rag | gemma-4-31b-think | 2166/2166 | 0 | 58.91 | 74.08 | 0 |
| rag | gpt-oss-20b | 2166/2166 | 0 | 47.32 | 67.28 | 10 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| full_context_text | 96.94 (n=882) | 95.79 / 89.28 (n=513) | 97.93 / 97.70 (n=217) | 70.15 / 40.43 (n=554) |
| full_context_text | 94.10 (n=882) | 74.64 / 39.38 (n=513) | 52.76 / 26.27 (n=217) | 69.94 / 38.09 (n=554) |
| otf_oracle_v2 | 96.94 (n=882) | 82.19 / 59.65 (n=513) | 94.70 / 89.40 (n=217) | 84.45 / 58.48 (n=554) |
| otf_single | 96.83 (n=882) | 79.55 / 53.41 (n=513) | 77.42 / 63.59 (n=217) | 78.47 / 51.08 (n=554) |
| otf_v2 | 96.71 (n=882) | 83.22 / 60.62 (n=513) | 78.57 / 65.44 (n=217) | 84.24 / 60.29 (n=554) |
| pageindex | 98.19 (n=882) | 86.02 / 64.13 (n=513) | 98.62 / 98.62 (n=217) | 68.59 / 43.14 (n=554) |
| pageindex | 88.55 (n=882) | 66.32 / 30.21 (n=513) | 47.00 / 9.68 (n=217) | 66.88 / 31.77 (n=554) |
| rag | 72.22 (n=882) | 86.62 / 69.20 (n=513) | 70.51 / 55.76 (n=217) | 64.02 / 29.42 (n=554) |
| rag | 66.21 (n=882) | 72.69 / 39.77 (n=513) | 54.15 / 26.27 (n=217) | 65.58 / 32.49 (n=554) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| full_context_text | gemma-4-31b-think | 80.8 [79.1, 82.4] | 96.9 [95.8, 98.0] | 89.3 [86.3, 91.8] | 97.7 [95.4, 99.5] | 40.4 [36.5, 44.6] |
| full_context_text | gpt-oss-20b | 60.0 [57.9, 62.1] | 94.1 [92.5, 95.7] | 39.4 [35.1, 43.7] | 26.3 [20.3, 32.3] | 38.1 [34.1, 42.1] |
| otf_oracle_v2 | gpt-oss-20b | 77.5 [75.7, 79.2] | 96.9 [95.8, 98.1] | 59.6 [55.6, 63.7] | 89.4 [85.2, 93.1] | 58.5 [54.3, 62.6] |
| otf_single | gpt-oss-20b | 71.5 [69.6, 73.4] | 96.8 [95.6, 98.0] | 53.4 [49.3, 57.9] | 63.6 [57.6, 69.6] | 51.1 [46.9, 55.4] |
| otf_v2 | gpt-oss-20b | 75.7 [73.9, 77.4] | 96.7 [95.5, 97.8] | 60.6 [56.3, 64.5] | 65.4 [59.5, 71.9] | 60.3 [56.3, 64.3] |
| pageindex | gemma-4-31b-think | 76.1 [74.2, 77.9] | 98.2 [97.3, 99.0] | 64.1 [59.8, 68.4] | 98.6 [96.8, 100.0] | 43.1 [39.0, 47.5] |
| pageindex | gpt-oss-20b | 52.3 [50.2, 54.4] | 88.5 [86.5, 90.6] | 30.2 [26.3, 34.1] | 9.7 [6.0, 13.8] | 31.8 [28.0, 35.6] |
| rag | gemma-4-31b-think | 58.9 [56.8, 60.9] | 72.2 [69.3, 75.1] | 69.2 [64.9, 72.9] | 55.8 [49.3, 62.2] | 29.4 [25.6, 33.2] |
| rag | gpt-oss-20b | 47.3 [45.2, 49.4] | 66.2 [63.1, 69.3] | 39.8 [35.3, 43.9] | 26.3 [20.7, 32.3] | 32.5 [28.5, 36.5] |

### Descriptive subtypes (accuracy %)

| System | count | exist | query_color | query_material | query_shape |
|---|---|---|---|---|---|
| full_context_text | 93.54 | 96.36 | 100.00 | 100.00 | 100.00 |
| full_context_text | 89.85 | 95.15 | 97.28 | 97.30 | 97.01 |
| otf_oracle_v2 | 93.54 | 96.97 | 100.00 | 99.10 | 100.00 |
| otf_single | 94.46 | 97.58 | 100.00 | 98.20 | 97.01 |
| otf_v2 | 94.46 | 96.36 | 99.32 | 99.10 | 97.76 |
| pageindex | 96.92 | 96.36 | 100.00 | 100.00 | 100.00 |
| pageindex | 82.77 | 89.09 | 93.20 | 92.79 | 93.28 |
| rag | 64.62 | 75.15 | 70.75 | 80.18 | 82.09 |
| rag | 59.08 | 71.52 | 68.71 | 68.47 | 72.39 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| full_context_text | 70,644.5 | 69,568.9 | 1,695.5 | 1,673.5 | 72,340.0 | 0 | 72,340.0 | 156,688,532 | 1.00 | 0.00 | 51.98 |
| full_context_text | 56,362.6 | 55,110.2 | 2,240.9 | 2,219.0 | 58,603.6 | 0 | 58,603.6 | 126,935,329 | 1.00 | 0.00 | 29.08 |
| otf_oracle_v2 | 2,278.1 | 1,248.4 | 734.0 | 692.0 | 3,012.1 | 0 | 3,012.1 | 6,524,299 | 2.22 | 0.00 | 5.64 |
| otf_single | 2,989.5 | 1,994.1 | 931.2 | 891.1 | 3,920.7 | 4,047,971 | 5,789.6 | 8,492,267 | 2.10 | 0.00 | 7.05 |
| otf_v2 | 2,506.2 | 1,499.9 | 719.5 | 677.5 | 3,225.7 | 4,047,971 | 5,094.6 | 6,986,906 | 2.20 | 0.00 | 5.50 |
| pageindex | 22,856.5 | 9,418.3 | 2,309.0 | 2,233.1 | 25,165.5 | 1,500,343 | 25,858.2 | 54,508,481 | 0.00 | 0.00 | 67.40 |
| pageindex | 15,014.4 | 6,629.4 | 921.2 | 861.3 | 15,935.6 | 1,510,456 | 16,633.0 | 34,516,516 | 0.00 | 0.00 | 10.67 |
| rag | 1,407.2 | 405.0 | 2,315.3 | 2,293.2 | 3,722.5 | 0 | 3,722.5 | 8,062,947 | 1.00 | 0.00 | 51.25 |
| rag | 1,276.5 | 473.5 | 727.0 | 704.9 | 2,003.6 | 0 | 2,003.6 | 4,339,755 | 1.00 | 0.00 | 9.25 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| full_context_text | 71,036.3 | 72,614.2 | 72,487.0 | 74,104.1 |
| full_context_text | 56,978.2 | 58,173.9 | 58,837.5 | 61,497.5 |
| otf_oracle_v2 | 3,821.0 | 3,060.3 | 1,212.5 | 2,384.7 |
| otf_single | 3,818.1 | 3,997.3 | 3,270.5 | 4,267.9 |
| otf_v2 | 3,953.6 | 2,810.7 | 2,078.6 | 2,900.6 |
| pageindex | 23,406.3 | 25,428.2 | 24,783.8 | 27,872.5 |
| pageindex | 16,285.1 | 14,660.0 | 14,631.1 | 17,071.3 |
| rag | 3,018.4 | 3,730.6 | 3,638.6 | 4,868.9 |
| rag | 1,625.4 | 2,146.2 | 1,941.6 | 2,497.8 |

### Setup details

- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 1.2s, info: `{"documents": 15}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.6s, info: `{"documents": 15}`
- **otf_oracle_v2**: 0 tokens (0 in / 0 out, 0 calls), 27.7s, info: `{"documents": 15}`
- **otf_single**: 4,047,971 tokens (3,480,307 in / 567,664 out, 447 calls), 2347.9s, info: `{"documents": 15}`
- **otf_v2**: 4,047,971 tokens (3,480,307 in / 567,664 out, 447 calls), 2360.6s, info: `{"documents": 15}`
- **pageindex**: 1,500,343 tokens (1,452,459 in / 47,884 out, 330 calls), 343.6s, info: `{"documents": 15}`
- **pageindex**: 1,510,456 tokens (1,280,181 in / 230,275 out, 330 calls), 404.5s, info: `{"documents": 15}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 122.8s, info: `{"documents": 15}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 99.1s, info: `{"documents": 15}`
