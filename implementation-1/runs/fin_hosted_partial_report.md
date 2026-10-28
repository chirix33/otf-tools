# CLEVRER document-QA benchmark: fin (3 documents)

- Videos: 274 (validation split, seed None), questions: 300
- Document: `fin_d01 .. fin_d03` (303 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every None frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 300/300 | 0 | 68.67 | 68.67 | 0 |
| full_context_text | or-gpt-oss-20b | 300/300 | 0 | 65.33 | 65.33 | 0 |
| rag | or-gpt-oss-20b | 300/300 | 0 | 64.00 | 64.00 | 0 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 70.67 (n=150) | - | - | 66.67 / 66.67 (n=150) |
| full_context_text | 67.33 (n=150) | - | - | 63.33 / 63.33 (n=150) |
| rag | 62.67 (n=150) | - | - | 65.33 / 65.33 (n=150) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 68.7 [63.3, 74.0] | 70.7 [63.3, 78.0] | - | - | 66.7 [58.7, 74.0] |
| full_context_text | or-gpt-oss-20b | 65.3 [60.0, 70.7] | 67.3 [59.3, 74.7] | - | - | 63.3 [55.3, 71.3] |
| rag | or-gpt-oss-20b | 64.0 [58.3, 69.3] | 62.7 [55.3, 70.0] | - | - | 65.3 [58.0, 72.7] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| or-gpt-oss-20b | otf vs full_context_text | +3.3 [-1.7, +8.7] p=0.110 | +3.3 [-3.3, +10.0] p=0.195 | - | - | +3.3 [-4.0, +10.7] p=0.204 |
| or-gpt-oss-20b | otf vs rag | +4.7 [-0.3, +9.7] p=0.034 | +8.0 [+1.3, +14.7] p=0.017 | - | - | +1.3 [-6.0, +8.0] p=0.400 |

### Descriptive subtypes (accuracy %)

| System | arithmetic | count | multi-span | span |
|---|---|---|---|---|
| otf | 69.05 | 75.00 | 50.00 | 85.71 |
| full_context_text | 65.87 | 75.00 | 50.00 | 78.57 |
| rag | 61.90 | 62.50 | 50.00 | 71.43 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 1,384.1 | 710.1 | 574.2 | 509.5 | 1,958.3 | 1,259,183 | 6,155.6 | 587,484 | 2.13 | 0.00 | 4.88 |
| full_context_text | 43,030.7 | 35,180.4 | 640.0 | 564.1 | 43,670.7 | 0 | 43,670.7 | 13,101,196 | 1.00 | 0.00 | 29.60 |
| rag | 1,198.1 | 348.7 | 445.6 | 376.8 | 1,643.8 | 0 | 1,643.8 | 493,126 | 1.00 | 0.00 | 19.81 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 1,668.8 | - | - | 2,247.8 |
| full_context_text | 43,541.2 | - | - | 43,800.1 |
| rag | 1,522.4 | - | - | 1,765.1 |

### Setup details

- **otf**: 1,259,183 tokens (1,111,587 in / 147,596 out, 102 calls), 1699.2s, info: `{"documents": 3}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.6s, info: `{"documents": 3}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 16.1s, info: `{"documents": 3}`
