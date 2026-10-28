# CLEVRER document-QA benchmark: itops (5 documents)

- Videos: 26 (validation split, seed None), questions: 300
- Document: `itops_d01 .. itops_d05` (240 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every None frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 300/300 | 0 | 28.33 | 57.03 | 0 |
| full_context_text | or-gpt-oss-20b | 300/300 | 0 | 18.33 | 35.38 | 101 |
| rag | or-gpt-oss-20b | 300/300 | 0 | 16.67 | 54.05 | 0 |
| pageindex | or-gpt-oss-20b | 300/300 | 0 | 32.00 | 59.08 | 3 |
| otf | or-qwen3.6-27b | 300/300 | 0 | 52.33 | 73.54 | 0 |
| full_context_text | or-qwen3.6-27b | 300/300 | 0 | 43.00 | 64.72 | 0 |
| rag | or-qwen3.6-27b | 300/300 | 0 | 26.00 | 57.44 | 0 |
| pageindex | or-qwen3.6-27b | 300/300 | 0 | 45.33 | 62.46 | 30 |
| otf | or-gemma-4-31b-think | 300/300 | 0 | 50.33 | 72.00 | 1 |
| full_context_text | or-gemma-4-31b-think | 300/300 | 0 | 44.00 | 68.31 | 2 |
| rag | or-gemma-4-31b-think | 300/300 | 0 | 24.67 | 58.77 | 0 |
| pageindex | or-gemma-4-31b-think | 300/300 | 0 | 50.67 | 70.67 | 2 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 76.00 (n=75) | 54.33 / 6.67 (n=75) | 63.67 / 26.67 (n=75) | 48.33 / 4.00 (n=75) |
| full_context_text | 40.00 (n=75) | 34.00 / 5.33 (n=75) | 41.00 / 24.00 (n=75) | 30.00 / 4.00 (n=75) |
| rag | 32.00 (n=75) | 54.00 / 8.00 (n=75) | 61.33 / 21.33 (n=75) | 52.33 / 5.33 (n=75) |
| pageindex | 82.67 (n=75) | 51.00 / 4.00 (n=75) | 68.33 / 33.33 (n=75) | 52.00 / 8.00 (n=75) |
| otf | 96.00 (n=75) | 64.67 / 30.67 (n=75) | 74.67 / 45.33 (n=75) | 75.67 / 37.33 (n=75) |
| full_context_text | 94.67 (n=75) | 57.00 / 22.67 (n=75) | 75.00 / 46.67 (n=75) | 54.67 / 8.00 (n=75) |
| rag | 42.67 (n=75) | 55.33 / 16.00 (n=75) | 62.00 / 25.33 (n=75) | 58.67 / 20.00 (n=75) |
| pageindex | 97.33 (n=75) | 58.67 / 21.33 (n=75) | 68.67 / 49.33 (n=75) | 51.33 / 13.33 (n=75) |
| otf | 97.33 (n=75) | 61.00 / 17.33 (n=75) | 86.00 / 69.33 (n=75) | 62.67 / 17.33 (n=75) |
| full_context_text | 88.00 (n=75) | 60.00 / 16.00 (n=75) | 79.00 / 58.67 (n=75) | 61.00 / 13.33 (n=75) |
| rag | 40.00 (n=75) | 56.67 / 12.00 (n=75) | 67.33 / 32.00 (n=75) | 57.00 / 14.67 (n=75) |
| pageindex | 100.00 (n=75) | 60.67 / 25.33 (n=75) | 85.67 / 65.33 (n=75) | 58.33 / 12.00 (n=75) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 28.3 [23.3, 33.7] | 76.0 [66.7, 85.3] | 6.7 [1.3, 12.0] | 26.7 [17.3, 37.3] | 4.0 [0.0, 9.3] |
| full_context_text | or-gpt-oss-20b | 18.3 [14.0, 22.7] | 40.0 [29.3, 50.7] | 5.3 [1.3, 10.7] | 24.0 [14.7, 34.7] | 4.0 [0.0, 9.3] |
| rag | or-gpt-oss-20b | 16.7 [12.3, 20.7] | 32.0 [21.3, 42.7] | 8.0 [2.7, 14.7] | 21.3 [12.0, 30.7] | 5.3 [1.3, 10.7] |
| pageindex | or-gpt-oss-20b | 32.0 [27.0, 37.3] | 82.7 [73.3, 90.7] | 4.0 [0.0, 9.3] | 33.3 [22.7, 44.0] | 8.0 [2.7, 14.7] |
| otf | or-qwen3.6-27b | 52.3 [47.0, 58.0] | 96.0 [90.7, 100.0] | 30.7 [20.0, 41.3] | 45.3 [34.7, 57.3] | 37.3 [26.7, 48.0] |
| full_context_text | or-qwen3.6-27b | 43.0 [37.0, 48.7] | 94.7 [89.3, 98.7] | 22.7 [13.3, 32.0] | 46.7 [36.0, 57.4] | 8.0 [2.7, 14.7] |
| rag | or-qwen3.6-27b | 26.0 [21.0, 31.0] | 42.7 [32.0, 53.3] | 16.0 [8.0, 24.0] | 25.3 [16.0, 36.0] | 20.0 [12.0, 29.3] |
| pageindex | or-qwen3.6-27b | 45.3 [39.7, 51.0] | 97.3 [93.3, 100.0] | 21.3 [12.0, 30.7] | 49.3 [38.7, 60.0] | 13.3 [6.7, 21.3] |
| otf | or-gemma-4-31b-think | 50.3 [44.7, 56.0] | 97.3 [93.3, 100.0] | 17.3 [9.3, 25.3] | 69.3 [58.7, 80.0] | 17.3 [9.3, 25.4] |
| full_context_text | or-gemma-4-31b-think | 44.0 [38.3, 50.0] | 88.0 [80.0, 94.7] | 16.0 [8.0, 25.3] | 58.7 [48.0, 69.3] | 13.3 [5.3, 21.3] |
| rag | or-gemma-4-31b-think | 24.7 [20.0, 29.7] | 40.0 [29.3, 50.7] | 12.0 [5.3, 20.0] | 32.0 [21.3, 42.7] | 14.7 [6.7, 22.7] |
| pageindex | or-gemma-4-31b-think | 50.7 [45.3, 56.3] | 100.0 [100.0, 100.0] | 25.3 [16.0, 36.0] | 65.3 [54.7, 76.0] | 12.0 [5.3, 20.0] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| or-gpt-oss-20b | otf vs full_context_text | +10.0 [+5.0, +15.0] p=0.000 | +36.0 [+24.0, +48.0] p=0.000 | +1.3 [-5.3, +9.3] p=0.432 | +2.7 [-9.3, +13.3] p=0.369 | +0.0 [-5.3, +5.3] p=0.600 |
| or-gpt-oss-20b | otf vs rag | +11.7 [+6.7, +16.7] p=0.000 | +44.0 [+30.7, +57.3] p=0.000 | -1.3 [-9.3, +8.0] p=0.688 | +5.3 [-5.3, +16.0] p=0.200 | -1.3 [-6.7, +2.7] p=0.820 |
| or-gpt-oss-20b | otf vs pageindex | -3.7 [-8.3, +1.3] p=0.938 | -6.7 [-17.3, +4.0] p=0.908 | +2.7 [-4.0, +9.3] p=0.277 | -6.7 [-20.0, +6.7] p=0.870 | -4.0 [-12.0, +4.0] p=0.881 |
| or-qwen3.6-27b | otf vs full_context_text | +9.3 [+3.7, +14.7] p=0.000 | +1.3 [-4.0, +8.0] p=0.406 | +8.0 [-5.3, +21.3] p=0.145 | -1.3 [-13.3, +9.3] p=0.655 | +29.3 [+17.3, +41.3] p=0.000 |
| or-qwen3.6-27b | otf vs rag | +26.3 [+19.7, +33.0] p=0.000 | +53.3 [+42.7, +64.0] p=0.000 | +14.7 [+1.3, +26.7] p=0.015 | +20.0 [+5.3, +34.7] p=0.002 | +17.3 [+4.0, +30.7] p=0.009 |
| or-qwen3.6-27b | otf vs pageindex | +7.0 [+1.3, +12.3] p=0.013 | -1.3 [-5.3, +2.7] p=0.812 | +9.3 [-4.0, +22.7] p=0.110 | -4.0 [-17.3, +9.3] p=0.753 | +24.0 [+12.0, +36.0] p=0.000 |
| or-gemma-4-31b-think | otf vs full_context_text | +6.3 [+1.3, +11.3] p=0.008 | +9.3 [+4.0, +16.0] p=0.001 | +1.3 [-8.0, +10.7] p=0.446 | +10.7 [-2.7, +24.0] p=0.071 | +4.0 [-5.3, +13.4] p=0.257 |
| or-gemma-4-31b-think | otf vs rag | +25.7 [+19.7, +31.7] p=0.000 | +57.3 [+45.3, +68.0] p=0.000 | +5.3 [-5.3, +16.0] p=0.202 | +37.3 [+25.3, +49.3] p=0.000 | +2.7 [-6.7, +12.0] p=0.359 |
| or-gemma-4-31b-think | otf vs pageindex | -0.3 [-5.0, +4.3] p=0.566 | -2.7 [-6.7, +0.0] p=1.000 | -8.0 [-17.3, +0.0] p=0.978 | +4.0 [-9.3, +17.3] p=0.321 | +5.3 [-2.7, +14.7] p=0.141 |

### Descriptive subtypes (accuracy %)

| System | finish_time | first_machine | n_evictions | n_starts | running_on | wait |
|---|---|---|---|---|---|---|
| otf | 58.33 | 92.31 | 100.00 | 75.00 | 58.33 | 69.23 |
| full_context_text | 25.00 | 46.15 | 69.23 | 50.00 | 33.33 | 15.38 |
| rag | 25.00 | 46.15 | 92.31 | 8.33 | 8.33 | 7.69 |
| pageindex | 83.33 | 92.31 | 100.00 | 100.00 | 25.00 | 92.31 |
| otf | 100.00 | 100.00 | 100.00 | 100.00 | 75.00 | 100.00 |
| full_context_text | 91.67 | 100.00 | 100.00 | 100.00 | 83.33 | 92.31 |
| rag | 41.67 | 69.23 | 92.31 | 16.67 | 25.00 | 7.69 |
| pageindex | 100.00 | 100.00 | 92.31 | 100.00 | 91.67 | 100.00 |
| otf | 100.00 | 100.00 | 100.00 | 100.00 | 83.33 | 100.00 |
| full_context_text | 100.00 | 84.62 | 92.31 | 83.33 | 83.33 | 84.62 |
| rag | 41.67 | 61.54 | 92.31 | 16.67 | 16.67 | 7.69 |
| pageindex | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 11,271.0 | 2,316.3 | 5,496.8 | 4,874.6 | 16,767.7 | 1,241,923 | 20,907.5 | 5,030,321 | 2.22 | 0.00 | 38.13 |
| full_context_text | 44,045.4 | 19,693.3 | 11,072.8 | 9,677.2 | 55,118.1 | 0 | 55,118.1 | 16,535,439 | 1.00 | 0.00 | 138.88 |
| rag | 2,639.3 | 309.5 | 1,915.5 | 1,812.0 | 4,554.9 | 0 | 4,554.9 | 1,366,457 | 1.00 | 0.00 | 43.77 |
| pageindex | 29,101.7 | 5,765.9 | 3,430.1 | 3,045.2 | 32,531.8 | 530,708 | 34,300.9 | 9,759,551 | 0.00 | 0.00 | 75.15 |
| otf | 40,577.4 | 0.0 | 5,263.5 | 5,174.5 | 45,841.0 | 115,244 | 46,225.1 | 13,752,293 | 2.51 | 0.00 | 92.93 |
| full_context_text | 69,065.0 | 0.0 | 6,270.5 | 6,246.5 | 75,335.5 | 0 | 75,335.5 | 22,600,648 | 1.00 | 0.00 | 125.03 |
| rag | 3,682.9 | 0.0 | 3,149.5 | 3,125.6 | 6,832.4 | 0 | 6,832.4 | 2,049,734 | 1.00 | 0.00 | 68.49 |
| pageindex | 55,798.1 | 0.0 | 33,506.6 | 33,316.1 | 89,304.7 | 913,094 | 92,348.3 | 26,791,398 | 0.00 | 0.00 | 522.13 |
| otf | 17,196.6 | 4,684.2 | 5,170.8 | 3,074.5 | 22,367.4 | 294,348 | 23,348.5 | 6,710,216 | 2.10 | 0.00 | 302.03 |
| full_context_text | 71,426.2 | 36,284.8 | 5,163.6 | 2,805.3 | 76,589.8 | 0 | 76,589.8 | 22,976,929 | 1.00 | 0.00 | 370.38 |
| rag | 3,784.8 | 176.6 | 4,868.3 | 3,023.5 | 8,653.1 | 0 | 8,653.1 | 2,595,918 | 1.00 | 0.00 | 314.11 |
| pageindex | 30,551.5 | 5,426.7 | 6,527.4 | 3,470.1 | 37,078.9 | 638,092 | 39,205.9 | 11,123,684 | 0.00 | 0.00 | 410.66 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 10,812.3 | 19,496.8 | 17,584.5 | 19,177.3 |
| full_context_text | 50,665.6 | 56,694.4 | 56,239.5 | 56,873.1 |
| rag | 3,405.9 | 4,172.7 | 5,372.0 | 5,268.7 |
| pageindex | 30,194.5 | 31,647.8 | 34,029.7 | 34,255.5 |
| otf | 15,080.7 | 67,330.7 | 40,683.1 | 60,269.4 |
| full_context_text | 70,031.4 | 76,389.0 | 77,876.2 | 77,045.4 |
| rag | 6,156.5 | 6,281.0 | 7,944.5 | 6,947.7 |
| pageindex | 32,227.9 | 114,799.8 | 88,787.4 | 121,403.5 |
| otf | 15,632.2 | 26,402.7 | 22,596.4 | 24,838.1 |
| full_context_text | 72,227.0 | 78,229.3 | 77,867.7 | 78,035.1 |
| rag | 7,170.1 | 8,370.4 | 10,547.8 | 8,523.9 |
| pageindex | 29,975.3 | 42,147.8 | 32,462.2 | 43,730.5 |

### Setup details

- **otf**: 1,241,923 tokens (1,079,529 in / 162,394 out, 92 calls), 1165.2s, info: `{"documents": 5}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.5s, info: `{"documents": 5}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 18.7s, info: `{"documents": 5}`
- **pageindex**: 530,708 tokens (423,720 in / 106,988 out, 126 calls), 743.8s, info: `{"documents": 5}`
- **otf**: 115,244 tokens (62,436 in / 52,808 out, 8 calls), 826.6s, info: `{"documents": 5}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.5s, info: `{"documents": 5}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 0.0s, info: `{"documents": 5}`
- **pageindex**: 913,094 tokens (622,442 in / 290,652 out, 126 calls), 2029.4s, info: `{"documents": 5}`
- **otf**: 294,348 tokens (197,087 in / 97,261 out, 22 calls), 5064.7s, info: `{"documents": 5}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 2.1s, info: `{"documents": 5}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 0.1s, info: `{"documents": 5}`
- **pageindex**: 638,092 tokens (619,590 in / 18,502 out, 126 calls), 6679.6s, info: `{"documents": 5}`
