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
| otf | or-qwen3.6-27b | 300/300 | 0 | 83.67 | 83.67 | 0 |
| full_context_text | or-qwen3.6-27b | 300/300 | 0 | 82.67 | 82.67 | 0 |
| rag | or-qwen3.6-27b | 300/300 | 0 | 76.33 | 76.33 | 0 |
| pageindex | or-qwen3.6-27b | 300/300 | 0 | 83.00 | 83.00 | 0 |
| otf | or-gemma-4-31b-think | 300/300 | 0 | 80.00 | 80.00 | 0 |
| full_context_text | or-gemma-4-31b-think | 300/300 | 0 | 78.00 | 78.00 | 0 |
| rag | or-gemma-4-31b-think | 300/300 | 0 | 73.00 | 73.00 | 0 |
| pageindex | or-gemma-4-31b-think | 300/300 | 0 | 79.67 | 79.67 | 0 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 70.67 (n=150) | - | - | 67.33 / 67.33 (n=150) |
| full_context_text | 67.33 (n=150) | - | - | 63.33 / 63.33 (n=150) |
| rag | 62.67 (n=150) | - | - | 65.33 / 65.33 (n=150) |
| pageindex | 55.33 (n=150) | - | - | 49.33 / 49.33 (n=150) |
| otf | 85.33 (n=150) | - | - | 82.00 / 82.00 (n=150) |
| full_context_text | 86.00 (n=150) | - | - | 79.33 / 79.33 (n=150) |
| rag | 75.33 (n=150) | - | - | 77.33 / 77.33 (n=150) |
| pageindex | 84.67 (n=150) | - | - | 81.33 / 81.33 (n=150) |
| otf | 81.33 (n=150) | - | - | 78.67 / 78.67 (n=150) |
| full_context_text | 82.00 (n=150) | - | - | 74.00 / 74.00 (n=150) |
| rag | 72.00 (n=150) | - | - | 74.00 / 74.00 (n=150) |
| pageindex | 79.33 (n=150) | - | - | 80.00 / 80.00 (n=150) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 69.0 [63.7, 74.3] | 70.7 [63.3, 78.0] | - | - | 67.3 [59.3, 74.7] |
| full_context_text | or-gpt-oss-20b | 65.3 [60.0, 70.7] | 67.3 [59.3, 74.7] | - | - | 63.3 [55.3, 71.3] |
| rag | or-gpt-oss-20b | 64.0 [58.3, 69.3] | 62.7 [55.3, 70.0] | - | - | 65.3 [58.0, 72.7] |
| pageindex | or-gpt-oss-20b | 52.3 [46.7, 58.0] | 55.3 [47.3, 63.3] | - | - | 49.3 [41.3, 56.7] |
| otf | or-qwen3.6-27b | 83.7 [79.7, 88.0] | 85.3 [79.3, 90.7] | - | - | 82.0 [76.0, 88.0] |
| full_context_text | or-qwen3.6-27b | 82.7 [78.0, 86.7] | 86.0 [80.7, 91.3] | - | - | 79.3 [72.7, 86.0] |
| rag | or-qwen3.6-27b | 76.3 [71.3, 81.3] | 75.3 [68.0, 82.0] | - | - | 77.3 [70.7, 83.3] |
| pageindex | or-qwen3.6-27b | 83.0 [78.7, 87.0] | 84.7 [78.7, 90.0] | - | - | 81.3 [74.7, 87.3] |
| otf | or-gemma-4-31b-think | 80.0 [75.7, 84.3] | 81.3 [75.3, 86.7] | - | - | 78.7 [72.0, 84.7] |
| full_context_text | or-gemma-4-31b-think | 78.0 [73.0, 82.3] | 82.0 [75.3, 88.0] | - | - | 74.0 [67.3, 80.7] |
| rag | or-gemma-4-31b-think | 73.0 [68.0, 77.7] | 72.0 [65.3, 78.7] | - | - | 74.0 [67.3, 80.7] |
| pageindex | or-gemma-4-31b-think | 79.7 [75.3, 84.3] | 79.3 [72.7, 86.0] | - | - | 80.0 [74.0, 86.0] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| or-gpt-oss-20b | otf vs full_context_text | +3.7 [-1.3, +8.7] p=0.086 | +3.3 [-3.3, +10.0] p=0.195 | - | - | +4.0 [-2.7, +11.3] p=0.144 |
| or-gpt-oss-20b | otf vs rag | +5.0 [+0.0, +10.0] p=0.025 | +8.0 [+1.3, +14.7] p=0.017 | - | - | +2.0 [-4.7, +8.7] p=0.327 |
| or-gpt-oss-20b | otf vs pageindex | +16.7 [+11.0, +22.0] p=0.000 | +15.3 [+8.0, +22.7] p=0.000 | - | - | +18.0 [+10.0, +26.7] p=0.000 |
| or-qwen3.6-27b | otf vs full_context_text | +1.0 [-2.0, +4.0] p=0.308 | -0.7 [-4.7, +2.7] p=0.699 | - | - | +2.7 [-1.3, +7.3] p=0.152 |
| or-qwen3.6-27b | otf vs rag | +7.3 [+3.0, +11.7] p=0.001 | +10.0 [+4.0, +15.3] p=0.001 | - | - | +4.7 [-1.3, +10.7] p=0.080 |
| or-qwen3.6-27b | otf vs pageindex | +0.7 [-2.7, +4.0] p=0.394 | +0.7 [-3.3, +5.3] p=0.444 | - | - | +0.7 [-4.7, +6.0] p=0.455 |
| or-gemma-4-31b-think | otf vs full_context_text | +2.0 [-1.3, +5.3] p=0.141 | -0.7 [-5.3, +3.3] p=0.667 | - | - | +4.7 [+0.0, +10.0] p=0.041 |
| or-gemma-4-31b-think | otf vs rag | +7.0 [+2.7, +11.3] p=0.002 | +9.3 [+2.7, +16.0] p=0.003 | - | - | +4.7 [-0.7, +10.7] p=0.061 |
| or-gemma-4-31b-think | otf vs pageindex | +0.3 [-3.0, +4.0] p=0.457 | +2.0 [-2.0, +6.7] p=0.216 | - | - | -1.3 [-6.0, +4.0] p=0.736 |

### Descriptive subtypes (accuracy %)

| System | arithmetic | count | multi-span | span |
|---|---|---|---|---|
| otf | 69.05 | 75.00 | 50.00 | 85.71 |
| full_context_text | 65.87 | 75.00 | 50.00 | 78.57 |
| rag | 61.90 | 62.50 | 50.00 | 71.43 |
| pageindex | 50.79 | 75.00 | 100.00 | 78.57 |
| otf | 86.51 | 87.50 | 50.00 | 78.57 |
| full_context_text | 85.71 | 87.50 | 100.00 | 85.71 |
| rag | 76.19 | 75.00 | 50.00 | 71.43 |
| pageindex | 84.13 | 87.50 | 100.00 | 85.71 |
| otf | 83.33 | 87.50 | 0.00 | 71.43 |
| full_context_text | 80.16 | 87.50 | 100.00 | 92.86 |
| rag | 72.22 | 75.00 | 50.00 | 71.43 |
| pageindex | 79.37 | 87.50 | 50.00 | 78.57 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 1,394.9 | 705.9 | 576.7 | 511.9 | 1,971.6 | 1,259,183 | 6,168.9 | 591,473 | 2.13 | 0.00 | 4.88 |
| full_context_text | 43,030.7 | 35,180.4 | 640.0 | 564.1 | 43,670.7 | 0 | 43,670.7 | 13,101,196 | 1.00 | 0.00 | 29.60 |
| rag | 1,198.1 | 348.7 | 445.6 | 376.8 | 1,643.8 | 0 | 1,643.8 | 493,126 | 1.00 | 0.00 | 19.81 |
| pageindex | 61,712.8 | 8,350.7 | 859.0 | 738.6 | 62,571.8 | 609,293 | 64,602.8 | 18,771,551 | 0.00 | 0.00 | 80.16 |
| otf | 1,325.3 | 0.0 | 1,816.9 | 1,783.5 | 3,142.1 | 607,636 | 5,167.6 | 942,644 | 2.00 | 0.00 | 31.24 |
| full_context_text | 50,655.1 | 0.0 | 1,438.3 | 1,417.6 | 52,093.5 | 0 | 52,093.5 | 15,628,038 | 1.00 | 0.00 | 43.65 |
| rag | 1,390.7 | 0.0 | 1,561.8 | 1,541.2 | 2,952.6 | 0 | 2,952.6 | 885,766 | 1.00 | 0.00 | 24.79 |
| pageindex | 65,088.7 | 0.0 | 1,081.2 | 966.2 | 66,169.9 | 1,222,921 | 70,246.3 | 19,850,963 | 0.00 | 0.00 | 27.10 |
| otf | 1,319.4 | 491.7 | 706.2 | 514.7 | 2,025.5 | 104,308 | 2,373.2 | 607,662 | 2.00 | 0.00 | 62.16 |
| full_context_text | 52,650.3 | 24,916.6 | 504.9 | 328.0 | 53,155.2 | 0 | 53,155.2 | 15,946,562 | 1.00 | 0.00 | 148.45 |
| rag | 1,425.2 | 92.8 | 640.6 | 434.9 | 2,065.8 | 0 | 2,065.8 | 619,746 | 1.00 | 0.00 | 169.77 |
| pageindex | 52,951.4 | 23,304.4 | 1,130.5 | 788.7 | 54,082.0 | 382,426 | 55,356.7 | 16,224,588 | 0.00 | 0.00 | 164.59 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 1,668.8 | - | - | 2,274.4 |
| full_context_text | 43,541.2 | - | - | 43,800.1 |
| rag | 1,522.4 | - | - | 1,765.1 |
| pageindex | 59,287.4 | - | - | 65,856.2 |
| otf | 2,850.8 | - | - | 3,433.5 |
| full_context_text | 51,892.8 | - | - | 52,294.1 |
| rag | 2,658.3 | - | - | 3,246.8 |
| pageindex | 65,076.2 | - | - | 67,263.5 |
| otf | 1,891.4 | - | - | 2,159.7 |
| full_context_text | 53,113.1 | - | - | 53,197.3 |
| rag | 1,932.1 | - | - | 2,199.5 |
| pageindex | 53,427.3 | - | - | 54,736.6 |

### Setup details

- **otf**: 1,259,183 tokens (1,111,587 in / 147,596 out, 102 calls), 1699.2s, info: `{"documents": 3}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.6s, info: `{"documents": 3}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 16.1s, info: `{"documents": 3}`
- **pageindex**: 609,293 tokens (338,986 in / 270,307 out, 276 calls), 650.1s, info: `{"documents": 3}`
- **otf**: 607,636 tokens (361,981 in / 245,655 out, 34 calls), 4204.4s, info: `{"documents": 3}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.5s, info: `{"documents": 3}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 43.6s, info: `{"documents": 3}`
- **pageindex**: 1,222,921 tokens (350,667 in / 872,254 out, 276 calls), 491.2s, info: `{"documents": 3}`
- **otf**: 104,308 tokens (62,612 in / 41,696 out, 9 calls), 1270.2s, info: `{"documents": 3}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.5s, info: `{"documents": 3}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 0.0s, info: `{"documents": 3}`
- **pageindex**: 382,426 tokens (334,568 in / 47,858 out, 276 calls), 4613.0s, info: `{"documents": 3}`
