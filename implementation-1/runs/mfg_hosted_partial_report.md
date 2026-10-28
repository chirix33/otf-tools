# CLEVRER document-QA benchmark: mfg (5 documents)

- Videos: 56 (validation split, seed None), questions: 300
- Document: `mfg_d01 .. mfg_d05` (257 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every None frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 300/300 | 0 | 60.00 | 80.29 | 0 |
| full_context_text | or-gpt-oss-20b | 300/300 | 0 | 54.33 | 63.28 | 59 |
| rag | or-gpt-oss-20b | 300/300 | 0 | 25.33 | 64.52 | 0 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 90.67 (n=75) | 76.67 / 44.00 (n=75) | 69.55 / 36.00 (n=75) | 91.67 / 69.33 (n=75) |
| full_context_text | 84.00 (n=75) | 78.67 / 56.00 (n=75) | 49.83 / 30.67 (n=75) | 55.67 / 46.67 (n=75) |
| rag | 33.33 (n=75) | 67.00 / 21.33 (n=75) | 58.13 / 8.00 (n=75) | 76.00 / 38.67 (n=75) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 60.0 [54.7, 65.7] | 90.7 [84.0, 96.0] | 44.0 [33.3, 54.7] | 36.0 [25.3, 48.0] | 69.3 [58.7, 80.0] |
| full_context_text | or-gpt-oss-20b | 54.3 [48.7, 60.0] | 84.0 [76.0, 92.0] | 56.0 [45.3, 66.7] | 30.7 [20.0, 41.3] | 46.7 [36.0, 58.7] |
| rag | or-gpt-oss-20b | 25.3 [20.7, 30.3] | 33.3 [22.7, 44.0] | 21.3 [12.0, 30.7] | 8.0 [2.7, 14.7] | 38.7 [28.0, 49.3] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| or-gpt-oss-20b | otf vs full_context_text | +5.7 [-1.3, +12.3] p=0.057 | +6.7 [-2.7, +16.0] p=0.100 | -12.0 [-28.0, +4.0] p=0.941 | +5.3 [-9.3, +20.0] p=0.288 | +22.7 [+9.3, +36.0] p=0.002 |
| or-gpt-oss-20b | otf vs rag | +34.7 [+27.7, +41.3] p=0.000 | +57.3 [+44.0, +69.3] p=0.000 | +22.7 [+9.3, +36.0] p=0.001 | +28.0 [+16.0, +41.3] p=0.000 | +30.7 [+17.3, +44.0] p=0.000 |

### Descriptive subtypes (accuracy %)

| System | backordered | capacity_days | first_stockout | max_backlog | shipped | stock | stockout_products |
|---|---|---|---|---|---|---|---|
| otf | 90.91 | 90.91 | 100.00 | 80.00 | 90.91 | 100.00 | 80.00 |
| full_context_text | 81.82 | 90.91 | 72.73 | 100.00 | 90.91 | 72.73 | 80.00 |
| rag | 45.45 | 36.36 | 54.55 | 40.00 | 9.09 | 9.09 | 40.00 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 8,140.5 | 863.6 | 3,128.9 | 2,985.9 | 11,269.4 | 291,786 | 12,242.1 | 3,380,834 | 2.49 | 0.00 | 21.75 |
| full_context_text | 54,704.9 | 30,213.7 | 8,271.0 | 6,931.5 | 62,975.9 | 0 | 62,975.9 | 18,892,779 | 1.00 | 0.00 | 85.59 |
| rag | 2,387.4 | 338.6 | 1,732.0 | 1,713.3 | 4,119.4 | 0 | 4,119.4 | 1,235,810 | 1.00 | 0.00 | 14.26 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 6,297.1 | 15,286.8 | 10,307.7 | 13,186.1 |
| full_context_text | 56,100.6 | 62,445.8 | 66,410.5 | 66,946.8 |
| rag | 2,487.3 | 4,300.6 | 5,049.5 | 4,640.1 |

### Setup details

- **otf**: 291,786 tokens (236,199 in / 55,587 out, 25 calls), 486.9s, info: `{"documents": 5}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.5s, info: `{"documents": 5}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 16.9s, info: `{"documents": 5}`
