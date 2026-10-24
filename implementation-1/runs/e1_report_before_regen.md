# CLEVRER document-QA benchmark: e1 (15 documents)

- Videos: 300 (validation split, seed 1), questions: 2166
- Document: `e1_d01 .. e1_d15` (798 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every 8 frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| otf | gpt-oss-20b | 2166/2166 | 0 | 75.72 | 85.53 | 0 |
| otf_single | gpt-oss-20b | 2166/2166 | 0 | 71.51 | 81.91 | 1 |
| otf_oracle | gpt-oss-20b | 2166/2166 | 0 | 77.52 | 86.63 | 0 |
| full_context_text | gpt-oss-20b | 2166/2166 | 0 | 60.02 | 74.31 | 17 |
| pageindex | gpt-oss-20b | 2166/2166 | 0 | 52.31 | 68.71 | 6 |
| rag | gpt-oss-20b | 2166/2166 | 0 | 47.32 | 67.28 | 10 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 96.71 (n=882) | 83.22 / 60.62 (n=513) | 78.57 / 65.44 (n=217) | 84.24 / 60.29 (n=554) |
| otf_single | 96.83 (n=882) | 79.55 / 53.41 (n=513) | 77.42 / 63.59 (n=217) | 78.47 / 51.08 (n=554) |
| otf_oracle | 96.94 (n=882) | 82.19 / 59.65 (n=513) | 94.70 / 89.40 (n=217) | 84.45 / 58.48 (n=554) |
| full_context_text | 94.10 (n=882) | 74.64 / 39.38 (n=513) | 52.76 / 26.27 (n=217) | 69.94 / 38.09 (n=554) |
| pageindex | 88.55 (n=882) | 66.32 / 30.21 (n=513) | 47.00 / 9.68 (n=217) | 66.88 / 31.77 (n=554) |
| rag | 66.21 (n=882) | 72.69 / 39.77 (n=513) | 54.15 / 26.27 (n=217) | 65.58 / 32.49 (n=554) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | gpt-oss-20b | 75.7 [73.9, 77.4] | 96.7 [95.5, 97.8] | 60.6 [56.3, 64.5] | 65.4 [59.5, 71.9] | 60.3 [56.3, 64.3] |
| otf_single | gpt-oss-20b | 71.5 [69.6, 73.4] | 96.8 [95.6, 98.0] | 53.4 [49.3, 57.9] | 63.6 [57.6, 69.6] | 51.1 [46.9, 55.4] |
| otf_oracle | gpt-oss-20b | 77.5 [75.7, 79.2] | 96.9 [95.8, 98.1] | 59.6 [55.6, 63.7] | 89.4 [85.2, 93.1] | 58.5 [54.3, 62.6] |
| full_context_text | gpt-oss-20b | 60.0 [57.9, 62.1] | 94.1 [92.5, 95.7] | 39.4 [35.1, 43.7] | 26.3 [20.3, 32.3] | 38.1 [34.1, 42.1] |
| pageindex | gpt-oss-20b | 52.3 [50.2, 54.4] | 88.5 [86.5, 90.6] | 30.2 [26.3, 34.1] | 9.7 [6.0, 13.8] | 31.8 [28.0, 35.6] |
| rag | gpt-oss-20b | 47.3 [45.2, 49.4] | 66.2 [63.1, 69.3] | 39.8 [35.3, 43.9] | 26.3 [20.7, 32.3] | 32.5 [28.5, 36.5] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| gpt-oss-20b | otf vs otf_single | +4.2 [+2.5, +6.0] p=0.000 | -0.1 [-1.4, +1.1] p=0.624 | +7.2 [+2.3, +12.1] p=0.002 | +1.8 [-5.5, +9.2] p=0.322 | +9.2 [+5.6, +12.4] p=0.000 |
| gpt-oss-20b | otf vs otf_oracle | -1.8 [-3.6, +0.0] p=0.975 | -0.2 [-1.5, +1.0] p=0.669 | +1.0 [-4.1, +6.2] p=0.363 | -24.0 [-30.4, -18.0] p=1.000 | +1.8 [-2.2, +5.6] p=0.192 |
| gpt-oss-20b | otf vs full_context_text | +15.7 [+13.8, +17.7] p=0.000 | +2.6 [+0.8, +4.4] p=0.004 | +21.2 [+16.6, +26.3] p=0.000 | +39.2 [+30.4, +47.5] p=0.000 | +22.2 [+17.9, +26.5] p=0.000 |
| gpt-oss-20b | otf vs pageindex | +23.4 [+21.4, +25.5] p=0.000 | +8.2 [+6.0, +10.3] p=0.000 | +30.4 [+25.7, +35.5] p=0.000 | +55.8 [+47.9, +63.1] p=0.000 | +28.5 [+23.8, +33.2] p=0.000 |
| gpt-oss-20b | otf vs rag | +28.4 [+26.0, +30.7] p=0.000 | +30.5 [+27.1, +33.7] p=0.000 | +20.9 [+15.6, +26.3] p=0.000 | +39.2 [+29.9, +47.9] p=0.000 | +27.8 [+23.5, +32.3] p=0.000 |

### Descriptive subtypes (accuracy %)

| System | count | exist | query_color | query_material | query_shape |
|---|---|---|---|---|---|
| otf | 94.46 | 96.36 | 99.32 | 99.10 | 97.76 |
| otf_single | 94.46 | 97.58 | 100.00 | 98.20 | 97.01 |
| otf_oracle | 93.54 | 96.97 | 100.00 | 99.10 | 100.00 |
| full_context_text | 89.85 | 95.15 | 97.28 | 97.30 | 97.01 |
| pageindex | 82.77 | 89.09 | 93.20 | 92.79 | 93.28 |
| rag | 59.08 | 71.52 | 68.71 | 68.47 | 72.39 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 2,506.2 | 1,499.9 | 719.5 | 677.5 | 3,225.7 | 4,047,971 | 5,094.6 | 6,986,906 | 2.20 | 0.00 | 5.50 |
| otf_single | 2,989.5 | 1,994.1 | 931.2 | 891.1 | 3,920.7 | 4,047,971 | 5,789.6 | 8,492,267 | 2.10 | 0.00 | 7.05 |
| otf_oracle | 2,278.1 | 1,248.4 | 734.0 | 692.0 | 3,012.1 | 0 | 3,012.1 | 6,524,299 | 2.22 | 0.00 | 5.64 |
| full_context_text | 56,362.6 | 55,110.2 | 2,240.9 | 2,219.0 | 58,603.6 | 0 | 58,603.6 | 126,935,329 | 1.00 | 0.00 | 29.08 |
| pageindex | 15,014.4 | 6,629.4 | 921.2 | 861.3 | 15,935.6 | 1,510,456 | 16,633.0 | 34,516,516 | 0.00 | 0.00 | 10.67 |
| rag | 1,276.5 | 473.5 | 727.0 | 704.9 | 2,003.6 | 0 | 2,003.6 | 4,339,755 | 1.00 | 0.00 | 9.25 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 3,953.6 | 2,810.7 | 2,078.6 | 2,900.6 |
| otf_single | 3,818.1 | 3,997.3 | 3,270.5 | 4,267.9 |
| otf_oracle | 3,821.0 | 3,060.3 | 1,212.5 | 2,384.7 |
| full_context_text | 56,978.2 | 58,173.9 | 58,837.5 | 61,497.5 |
| pageindex | 16,285.1 | 14,660.0 | 14,631.1 | 17,071.3 |
| rag | 1,625.4 | 2,146.2 | 1,941.6 | 2,497.8 |

### Setup details

- **otf**: 4,047,971 tokens (3,480,307 in / 567,664 out, 447 calls), 2360.6s, info: `{"documents": 15}`
- **otf_single**: 4,047,971 tokens (3,480,307 in / 567,664 out, 447 calls), 2347.9s, info: `{"documents": 15}`
- **otf_oracle**: 0 tokens (0 in / 0 out, 0 calls), 27.7s, info: `{"documents": 15}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.6s, info: `{"documents": 15}`
- **pageindex**: 1,510,456 tokens (1,280,181 in / 230,275 out, 330 calls), 404.5s, info: `{"documents": 15}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 99.1s, info: `{"documents": 15}`
