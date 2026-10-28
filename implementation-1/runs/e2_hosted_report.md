# CLEVRER document-QA benchmark: e2 (1 documents)

- Videos: 300 (validation split, seed 1), questions: 1067
- Document: `e2_d01 .. e2_d01` (784 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every 8 frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 1067/1067 | 0 | 45.74 | 75.92 | 1 |
| full_context_text | or-gpt-oss-20b | 1067/1067 | 0 | 13.21 | 50.86 | 71 |
| rag | or-gpt-oss-20b | 1067/1067 | 0 | 17.15 | 56.19 | 15 |
| pageindex | or-gpt-oss-20b | 1067/1067 | 0 | 24.18 | 59.65 | 24 |
| otf | or-qwen3.6-27b | 1067/1067 | 0 | 51.08 | 77.38 | 0 |
| full_context_text | or-qwen3.6-27b | 1067/1067 | 0 | 17.62 | 56.89 | 0 |
| rag | or-qwen3.6-27b | 1067/1067 | 0 | 20.15 | 58.68 | 0 |
| pageindex | or-qwen3.6-27b | 1067/1067 | 0 | 51.64 | 75.30 | 17 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | - | 76.90 / 48.34 (n=513) | - | 75.01 / 43.32 (n=554) |
| full_context_text | - | 55.48 / 12.48 (n=513) | - | 46.56 / 13.90 (n=554) |
| rag | - | 61.25 / 23.39 (n=513) | - | 51.48 / 11.37 (n=554) |
| pageindex | - | 59.15 / 23.59 (n=513) | - | 60.11 / 24.73 (n=554) |
| otf | - | 85.21 / 62.96 (n=513) | - | 70.10 / 40.07 (n=554) |
| full_context_text | - | 63.19 / 20.08 (n=513) | - | 51.03 / 15.34 (n=554) |
| rag | - | 66.43 / 25.93 (n=513) | - | 51.48 / 14.80 (n=554) |
| pageindex | - | 83.54 / 62.96 (n=513) | - | 67.64 / 41.16 (n=554) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 45.7 [42.7, 48.7] | - | 48.3 [44.0, 52.6] | - | 43.3 [39.4, 47.5] |
| full_context_text | or-gpt-oss-20b | 13.2 [11.2, 15.3] | - | 12.5 [9.8, 15.4] | - | 13.9 [11.2, 17.0] |
| rag | or-gpt-oss-20b | 17.1 [15.0, 19.5] | - | 23.4 [19.9, 27.1] | - | 11.4 [8.7, 14.1] |
| pageindex | or-gpt-oss-20b | 24.2 [21.7, 26.7] | - | 23.6 [19.9, 27.3] | - | 24.7 [21.3, 28.3] |
| otf | or-qwen3.6-27b | 51.1 [48.0, 53.9] | - | 63.0 [58.7, 67.1] | - | 40.1 [36.3, 44.0] |
| full_context_text | or-qwen3.6-27b | 17.6 [15.3, 20.1] | - | 20.1 [16.6, 23.6] | - | 15.3 [12.4, 18.4] |
| rag | or-qwen3.6-27b | 20.1 [17.8, 22.5] | - | 25.9 [22.2, 29.6] | - | 14.8 [11.9, 17.9] |
| pageindex | or-qwen3.6-27b | 51.6 [48.5, 55.0] | - | 63.0 [58.7, 67.2] | - | 41.2 [37.0, 45.3] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| or-gpt-oss-20b | otf vs full_context_text | +32.5 [+29.2, +35.5] p=0.000 | - | +35.9 [+31.6, +40.4] p=0.000 | - | +29.4 [+24.9, +33.9] p=0.000 |
| or-gpt-oss-20b | otf vs rag | +28.6 [+25.4, +31.8] p=0.000 | - | +24.9 [+20.1, +29.8] p=0.000 | - | +31.9 [+27.8, +36.1] p=0.000 |
| or-gpt-oss-20b | otf vs pageindex | +21.6 [+18.5, +24.6] p=0.000 | - | +24.8 [+20.5, +29.0] p=0.000 | - | +18.6 [+14.6, +22.7] p=0.000 |
| or-qwen3.6-27b | otf vs full_context_text | +33.5 [+30.3, +36.7] p=0.000 | - | +42.9 [+38.6, +47.4] p=0.000 | - | +24.7 [+20.2, +29.1] p=0.000 |
| or-qwen3.6-27b | otf vs rag | +30.9 [+27.7, +34.1] p=0.000 | - | +37.0 [+32.8, +41.9] p=0.000 | - | +25.3 [+20.9, +29.6] p=0.000 |
| or-qwen3.6-27b | otf vs pageindex | -0.6 [-3.2, +2.1] p=0.682 | - | +0.0 [-4.1, +4.3] p=0.525 | - | -1.1 [-4.3, +2.0] p=0.767 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 3,795.3 | 875.8 | 1,495.4 | 1,544.5 | 5,290.6 | 829,310 | 6,067.9 | 5,645,123 | 2.00 | 0.00 | 10.10 |
| full_context_text | 111,335.3 | 105,927.8 | 1,696.2 | 1,866.0 | 113,031.5 | 0 | 113,031.5 | 120,604,653 | 1.00 | 0.00 | 16.94 |
| rag | 1,235.4 | 326.7 | 895.3 | 1,014.8 | 2,130.7 | 0 | 2,130.7 | 2,273,471 | 1.00 | 0.00 | 9.89 |
| pageindex | 165,274.3 | 19,757.3 | 1,378.2 | 927.9 | 166,652.5 | 1,562,850 | 168,117.3 | 177,818,268 | 0.00 | 0.00 | 20.00 |
| otf | 5,340.5 | 0.0 | 4,754.8 | 4,655.7 | 10,095.3 | 177,174 | 10,261.3 | 10,771,667 | 3.00 | 0.00 | 75.13 |
| full_context_text | 135,879.6 | 0.0 | 3,060.7 | 3,034.7 | 138,940.3 | 0 | 138,940.3 | 148,249,263 | 1.00 | 0.00 | 58.97 |
| rag | 1,329.7 | 0.0 | 2,745.6 | 2,719.6 | 4,075.4 | 0 | 4,075.4 | 4,348,437 | 1.00 | 0.00 | 46.15 |
| pageindex | 188,531.0 | 0.0 | 5,418.0 | 5,207.9 | 193,949.1 | 2,148,168 | 195,962.3 | 206,943,646 | 0.00 | 0.00 | 119.29 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | - | 4,822.6 | - | 5,724.0 |
| full_context_text | - | 112,758.1 | - | 113,284.8 |
| rag | - | 2,050.0 | - | 2,205.5 |
| pageindex | - | 164,842.4 | - | 168,328.7 |
| otf | - | 11,175.5 | - | 9,095.0 |
| full_context_text | - | 138,611.2 | - | 139,244.9 |
| rag | - | 3,793.0 | - | 4,336.9 |
| pageindex | - | 183,386.3 | - | 203,730.1 |

### Setup details

- **otf**: 829,310 tokens (734,380 in / 94,930 out, 62 calls), 768.7s, info: `{"nodes": 1201, "scopes": 300, "model_passed": false, "model_f1": 0.0, "model_tries": 21, "model_reused_from": null, "cached_model": true}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.8s, info: `{"pages": 784, "doc_tokens_est": 838113, "kept_tokens_est": 111049, "kept_pages": 106, "truncated": true, "budget_tokens": 111688, "doc_chars": 237910}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 0.0s, info: `{"chunks": 2667, "embed_model": "BAAI/bge-small-en-v1.5", "top_k": 5}`
- **pageindex**: 1,562,850 tokens (1,268,899 in / 293,951 out, 302 calls), 143.9s, info: `{"doc_id": "pi-343314605b4944a8bd5b7a61e98f340f", "cached_index": true, "tree_nodes": 301}`
- **otf**: 177,174 tokens (94,074 in / 83,100 out, 10 calls), 1295.9s, info: `{"nodes": 1201, "scopes": 300, "model_passed": true, "model_f1": 0.444, "model_tries": 10, "model_reused_from": null, "cached_model": true}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.8s, info: `{"pages": 784, "doc_tokens_est": 838113, "kept_tokens_est": 111049, "kept_pages": 106, "truncated": true, "budget_tokens": 111688, "doc_chars": 237910}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 0.0s, info: `{"chunks": 2667, "embed_model": "BAAI/bge-small-en-v1.5", "top_k": 5}`
- **pageindex**: 2,148,168 tokens (1,450,309 in / 697,859 out, 302 calls), 369.3s, info: `{"doc_id": "pi-7af25c7979c64f98a076656f98d74b85", "cached_index": true, "tree_nodes": 301}`
