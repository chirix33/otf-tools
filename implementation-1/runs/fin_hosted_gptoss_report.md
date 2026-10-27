# CLEVRER document-QA benchmark: fin (3 documents)

- Videos: 274 (validation split, seed None), questions: 300
- Document: `fin_d01 .. fin_d03` (303 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every None frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 300/300 | 0 | 69.00 | 69.00 | 0 |
| full_context_text | or-gpt-oss-20b | 300/300 | 0 | 65.33 | 65.33 | 0 |
| rag | or-gpt-oss-20b | 300/300 | 0 | 64.00 | 64.00 | 0 |
| pageindex | or-gpt-oss-20b | 300/300 | 0 | 52.33 | 52.33 | 1 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 70.67 (n=150) | - | - | 67.33 / 67.33 (n=150) |
| full_context_text | 67.33 (n=150) | - | - | 63.33 / 63.33 (n=150) |
| rag | 62.67 (n=150) | - | - | 65.33 / 65.33 (n=150) |
| pageindex | 55.33 (n=150) | - | - | 49.33 / 49.33 (n=150) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 69.0 [63.7, 74.3] | 70.7 [63.3, 78.0] | - | - | 67.3 [59.3, 74.7] |
| full_context_text | or-gpt-oss-20b | 65.3 [60.0, 70.7] | 67.3 [59.3, 74.7] | - | - | 63.3 [55.3, 71.3] |
| rag | or-gpt-oss-20b | 64.0 [58.3, 69.3] | 62.7 [55.3, 70.0] | - | - | 65.3 [58.0, 72.7] |
| pageindex | or-gpt-oss-20b | 52.3 [46.7, 58.0] | 55.3 [47.3, 63.3] | - | - | 49.3 [41.3, 56.7] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| or-gpt-oss-20b | otf vs full_context_text | +3.7 [-1.3, +8.7] p=0.086 | +3.3 [-3.3, +10.0] p=0.195 | - | - | +4.0 [-2.7, +11.3] p=0.144 |
| or-gpt-oss-20b | otf vs rag | +5.0 [+0.0, +10.0] p=0.025 | +8.0 [+1.3, +14.7] p=0.017 | - | - | +2.0 [-4.7, +8.7] p=0.327 |
| or-gpt-oss-20b | otf vs pageindex | +16.7 [+11.0, +22.0] p=0.000 | +15.3 [+8.0, +22.7] p=0.000 | - | - | +18.0 [+10.0, +26.7] p=0.000 |

### Descriptive subtypes (accuracy %)

| System | arithmetic | count | multi-span | span |
|---|---|---|---|---|
| otf | 69.05 | 75.00 | 50.00 | 85.71 |
| full_context_text | 65.87 | 75.00 | 50.00 | 78.57 |
| rag | 61.90 | 62.50 | 50.00 | 71.43 |
| pageindex | 50.79 | 75.00 | 100.00 | 78.57 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 1,394.9 | 705.9 | 576.7 | 511.9 | 1,971.6 | 1,259,183 | 6,168.9 | 591,473 | 2.13 | 0.00 | 4.88 |
| full_context_text | 43,030.7 | 35,180.4 | 640.0 | 564.1 | 43,670.7 | 0 | 43,670.7 | 13,101,196 | 1.00 | 0.00 | 29.60 |
| rag | 1,198.1 | 348.7 | 445.6 | 376.8 | 1,643.8 | 0 | 1,643.8 | 493,126 | 1.00 | 0.00 | 19.81 |
| pageindex | 61,712.8 | 8,350.7 | 859.0 | 738.6 | 62,571.8 | 609,293 | 64,602.8 | 18,771,551 | 0.00 | 0.00 | 80.16 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 1,668.8 | - | - | 2,274.4 |
| full_context_text | 43,541.2 | - | - | 43,800.1 |
| rag | 1,522.4 | - | - | 1,765.1 |
| pageindex | 59,287.4 | - | - | 65,856.2 |

### Setup details

- **otf**: 1,259,183 tokens (1,111,587 in / 147,596 out, 102 calls), 1699.2s, info: `{"documents": 3}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.6s, info: `{"documents": 3}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 16.1s, info: `{"documents": 3}`
- **pageindex**: 609,293 tokens (338,986 in / 270,307 out, 276 calls), 650.1s, info: `{"documents": 3}`
