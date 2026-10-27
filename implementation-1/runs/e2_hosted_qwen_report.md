# CLEVRER document-QA benchmark: e2 (1 documents)

- Videos: 300 (validation split, seed 1), questions: 1067
- Document: `e2_d01 .. e2_d01` (784 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every 8 frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| otf | or-qwen3.6-27b | 1067/1067 | 0 | 51.08 | 77.38 | 0 |
| full_context_text | or-qwen3.6-27b | 1067/1067 | 0 | 17.62 | 56.89 | 0 |
| rag | or-qwen3.6-27b | 1067/1067 | 0 | 20.15 | 58.68 | 0 |
| pageindex | or-qwen3.6-27b | 1066/1067 | 1 | 51.59 | 75.27 | 17 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | - | 85.21 / 62.96 (n=513) | - | 70.10 / 40.07 (n=554) |
| full_context_text | - | 63.19 / 20.08 (n=513) | - | 51.03 / 15.34 (n=554) |
| rag | - | 66.43 / 25.93 (n=513) | - | 51.48 / 14.80 (n=554) |
| pageindex | - | 83.54 / 62.96 (n=513) | - | 67.57 / 41.05 (n=553) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | or-qwen3.6-27b | 51.1 [48.0, 53.9] | - | 63.0 [58.7, 67.1] | - | 40.1 [36.3, 44.0] |
| full_context_text | or-qwen3.6-27b | 17.6 [15.3, 20.1] | - | 20.1 [16.6, 23.6] | - | 15.3 [12.4, 18.4] |
| rag | or-qwen3.6-27b | 20.1 [17.8, 22.5] | - | 25.9 [22.2, 29.6] | - | 14.8 [11.9, 17.9] |
| pageindex | or-qwen3.6-27b | 51.6 [48.6, 54.9] | - | 63.0 [58.7, 67.2] | - | 41.0 [36.9, 45.2] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| or-qwen3.6-27b | otf vs full_context_text | +33.5 [+30.3, +36.7] p=0.000 | - | +42.9 [+38.6, +47.4] p=0.000 | - | +24.7 [+20.2, +29.1] p=0.000 |
| or-qwen3.6-27b | otf vs rag | +30.9 [+27.7, +34.1] p=0.000 | - | +37.0 [+32.8, +41.9] p=0.000 | - | +25.3 [+20.9, +29.6] p=0.000 |
| or-qwen3.6-27b | otf vs pageindex | -0.5 [-3.1, +2.2] p=0.655 | - | +0.0 [-4.1, +4.3] p=0.525 | - | -0.9 [-4.0, +2.2] p=0.738 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 5,340.5 | 0.0 | 4,754.8 | 4,655.7 | 10,095.3 | 177,174 | 10,261.3 | 10,771,667 | 3.00 | 0.00 | 75.13 |
| full_context_text | 135,879.6 | 0.0 | 3,060.7 | 3,034.7 | 138,940.3 | 0 | 138,940.3 | 148,249,263 | 1.00 | 0.00 | 58.97 |
| rag | 1,329.7 | 0.0 | 2,745.6 | 2,719.6 | 4,075.4 | 0 | 4,075.4 | 4,348,437 | 1.00 | 0.00 | 46.15 |
| pageindex | 188,374.3 | 0.0 | 5,418.6 | 5,208.6 | 193,792.9 | 2,148,168 | 195,808.1 | 206,583,250 | 0.00 | 0.00 | 119.28 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | - | 11,175.5 | - | 9,095.0 |
| full_context_text | - | 138,611.2 | - | 139,244.9 |
| rag | - | 3,793.0 | - | 4,336.9 |
| pageindex | - | 183,386.3 | - | 203,446.8 |

### Setup details

- **otf**: 177,174 tokens (94,074 in / 83,100 out, 10 calls), 1295.9s, info: `{"nodes": 1201, "scopes": 300, "model_passed": true, "model_f1": 0.444, "model_tries": 10, "model_reused_from": null, "cached_model": true}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.8s, info: `{"pages": 784, "doc_tokens_est": 838113, "kept_tokens_est": 111049, "kept_pages": 106, "truncated": true, "budget_tokens": 111688, "doc_chars": 237910}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 0.0s, info: `{"chunks": 2667, "embed_model": "BAAI/bge-small-en-v1.5", "top_k": 5}`
- **pageindex**: 2,148,168 tokens (1,450,309 in / 697,859 out, 302 calls), 369.3s, info: `{"doc_id": "pi-7af25c7979c64f98a076656f98d74b85", "cached_index": true, "tree_nodes": 301}`
