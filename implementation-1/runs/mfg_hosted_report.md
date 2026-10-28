# CLEVRER document-QA benchmark: mfg (5 documents)

- Videos: 56 (validation split, seed None), questions: 300
- Document: `mfg_d01 .. mfg_d05` (257 pages), rendered from ground-truth annotations (observed 128 frames only; motion log every None frames + event frames)
- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy (all options of the question correct). Overall question accuracy counts each question once.

## Overall

| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 300/300 | 0 | 64.00 | 83.30 | 0 |
| full_context_text | or-gpt-oss-20b | 300/300 | 0 | 54.33 | 63.28 | 59 |
| rag | or-gpt-oss-20b | 300/300 | 0 | 25.33 | 64.52 | 0 |
| pageindex | or-gpt-oss-20b | 300/300 | 0 | 46.00 | 68.05 | 22 |
| otf | or-qwen3.6-27b | 300/300 | 0 | 69.00 | 86.31 | 0 |
| full_context_text | or-qwen3.6-27b | 300/300 | 0 | 79.00 | 91.29 | 0 |
| rag | or-qwen3.6-27b | 300/300 | 0 | 27.33 | 66.49 | 0 |
| pageindex | or-qwen3.6-27b | 300/300 | 3 | 77.33 | 76.24 | 52 |
| otf | or-gemma-4-31b-think | 300/300 | 0 | 82.00 | 91.29 | 0 |
| full_context_text | or-gemma-4-31b-think | 300/300 | 0 | 83.33 | 92.95 | 0 |
| rag | or-gemma-4-31b-think | 300/300 | 0 | 30.00 | 67.01 | 0 |
| pageindex | or-gemma-4-31b-think | 300/300 | 0 | 80.33 | 90.98 | 2 |
| otf_reading_only | or-qwen3.6-27b | 300/300 | 0 | 74.67 | 88.80 | 1 |

## Accuracy by question type

Descriptive: accuracy. Others: per-option / per-question.

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 90.67 (n=75) | 82.67 / 48.00 (n=75) | 72.66 / 42.67 (n=75) | 92.33 / 74.67 (n=75) |
| full_context_text | 84.00 (n=75) | 78.67 / 56.00 (n=75) | 49.83 / 30.67 (n=75) | 55.67 / 46.67 (n=75) |
| rag | 33.33 (n=75) | 67.00 / 21.33 (n=75) | 58.13 / 8.00 (n=75) | 76.00 / 38.67 (n=75) |
| pageindex | 77.33 (n=75) | 71.00 / 34.67 (n=75) | 56.06 / 29.33 (n=75) | 74.33 / 42.67 (n=75) |
| otf | 98.67 (n=75) | 83.00 / 48.00 (n=75) | 88.24 / 70.67 (n=75) | 84.67 / 58.67 (n=75) |
| full_context_text | 100.00 (n=75) | 88.67 / 64.00 (n=75) | 91.35 / 78.67 (n=75) | 91.67 / 73.33 (n=75) |
| rag | 37.33 (n=75) | 66.33 / 17.33 (n=75) | 62.28 / 14.67 (n=75) | 78.00 / 40.00 (n=75) |
| pageindex | 100.00 (n=75) | 80.33 / 74.67 (n=75) | 73.36 / 69.33 (n=75) | 69.00 / 65.33 (n=75) |
| otf | 100.00 (n=75) | 91.33 / 81.33 (n=75) | 91.35 / 76.00 (n=75) | 89.00 / 70.67 (n=75) |
| full_context_text | 98.67 (n=75) | 95.67 / 88.00 (n=75) | 90.66 / 72.00 (n=75) | 91.00 / 74.67 (n=75) |
| rag | 34.67 (n=75) | 66.00 / 21.33 (n=75) | 59.17 / 10.67 (n=75) | 83.67 / 53.33 (n=75) |
| pageindex | 94.67 (n=75) | 95.00 / 86.67 (n=75) | 92.04 / 78.67 (n=75) | 85.00 / 61.33 (n=75) |
| otf_reading_only | 97.33 (n=75) | 89.33 / 70.67 (n=75) | 86.85 / 66.67 (n=75) | 88.00 / 64.00 (n=75) |

### Question accuracy (%) with 95% bootstrap CI

| System | Model | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| otf | or-gpt-oss-20b | 64.0 [58.3, 69.3] | 90.7 [84.0, 96.0] | 48.0 [37.3, 58.7] | 42.7 [32.0, 54.7] | 74.7 [65.3, 84.0] |
| full_context_text | or-gpt-oss-20b | 54.3 [48.7, 60.0] | 84.0 [76.0, 92.0] | 56.0 [45.3, 66.7] | 30.7 [20.0, 41.3] | 46.7 [36.0, 58.7] |
| rag | or-gpt-oss-20b | 25.3 [20.7, 30.3] | 33.3 [22.7, 44.0] | 21.3 [12.0, 30.7] | 8.0 [2.7, 14.7] | 38.7 [28.0, 49.3] |
| pageindex | or-gpt-oss-20b | 46.0 [40.3, 51.3] | 77.3 [68.0, 86.7] | 34.7 [24.0, 45.3] | 29.3 [20.0, 38.7] | 42.7 [32.0, 53.3] |
| otf | or-qwen3.6-27b | 69.0 [63.7, 74.3] | 98.7 [96.0, 100.0] | 48.0 [36.0, 60.0] | 70.7 [60.0, 80.0] | 58.7 [48.0, 70.7] |
| full_context_text | or-qwen3.6-27b | 79.0 [74.3, 83.7] | 100.0 [100.0, 100.0] | 64.0 [52.0, 74.7] | 78.7 [69.3, 88.0] | 73.3 [62.7, 82.7] |
| rag | or-qwen3.6-27b | 27.3 [22.3, 33.0] | 37.3 [26.7, 48.0] | 17.3 [9.3, 26.7] | 14.7 [6.7, 22.7] | 40.0 [28.0, 50.7] |
| pageindex | or-qwen3.6-27b | 77.3 [72.3, 81.7] | 100.0 [100.0, 100.0] | 74.7 [64.0, 84.0] | 69.3 [58.7, 80.0] | 65.3 [54.7, 76.0] |
| otf | or-gemma-4-31b-think | 82.0 [77.7, 86.3] | 100.0 [100.0, 100.0] | 81.3 [72.0, 89.3] | 76.0 [65.3, 85.3] | 70.7 [60.0, 81.3] |
| full_context_text | or-gemma-4-31b-think | 83.3 [79.0, 87.7] | 98.7 [96.0, 100.0] | 88.0 [80.0, 94.7] | 72.0 [61.3, 81.3] | 74.7 [64.0, 84.0] |
| rag | or-gemma-4-31b-think | 30.0 [25.0, 35.3] | 34.7 [24.0, 46.7] | 21.3 [12.0, 30.7] | 10.7 [4.0, 18.7] | 53.3 [42.7, 64.0] |
| pageindex | or-gemma-4-31b-think | 80.3 [75.7, 84.3] | 94.7 [89.3, 98.7] | 86.7 [78.7, 93.3] | 78.7 [69.3, 86.7] | 61.3 [49.3, 72.0] |
| otf_reading_only | or-qwen3.6-27b | 74.7 [69.7, 79.3] | 97.3 [93.3, 100.0] | 70.7 [60.0, 81.3] | 66.7 [56.0, 77.3] | 64.0 [53.3, 74.7] |

### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, p = share of resamples <= 0)

| Model | Reference vs other | overall | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|---|---|
| or-gpt-oss-20b | otf vs full_context_text | +9.7 [+3.0, +16.7] p=0.003 | +6.7 [-2.7, +16.0] p=0.100 | -8.0 [-22.7, +8.0] p=0.874 | +12.0 [-2.7, +26.7] p=0.069 | +28.0 [+14.7, +41.3] p=0.000 |
| or-gpt-oss-20b | otf vs rag | +38.7 [+32.0, +45.3] p=0.000 | +57.3 [+44.0, +69.3] p=0.000 | +26.7 [+13.3, +40.0] p=0.000 | +34.7 [+21.3, +48.0] p=0.000 | +36.0 [+24.0, +48.0] p=0.000 |
| or-gpt-oss-20b | otf vs pageindex | +18.0 [+12.0, +24.0] p=0.000 | +13.3 [+2.7, +24.0] p=0.007 | +13.3 [-1.3, +28.0] p=0.040 | +13.3 [+0.0, +26.7] p=0.030 | +32.0 [+20.0, +44.0] p=0.000 |
| or-qwen3.6-27b | otf vs full_context_text | -10.0 [-15.7, -4.7] p=1.000 | -1.3 [-4.0, +0.0] p=1.000 | -16.0 [-30.7, +0.0] p=0.982 | -8.0 [-20.0, +4.0] p=0.935 | -14.7 [-26.7, -4.0] p=0.996 |
| or-qwen3.6-27b | otf vs rag | +41.7 [+35.0, +48.3] p=0.000 | +61.3 [+50.7, +72.0] p=0.000 | +30.7 [+17.3, +44.0] p=0.000 | +56.0 [+42.7, +69.3] p=0.000 | +18.7 [+5.3, +30.7] p=0.004 |
| or-qwen3.6-27b | otf vs pageindex | -8.3 [-14.3, -2.3] p=0.996 | -1.3 [-4.0, +0.0] p=1.000 | -26.7 [-40.0, -13.3] p=1.000 | +1.3 [-12.0, +13.3] p=0.463 | -6.7 [-20.0, +6.7] p=0.863 |
| or-qwen3.6-27b | otf vs otf_reading_only | -5.7 [-11.3, -0.7] p=0.987 | +1.3 [+0.0, +4.0] p=0.375 | -22.7 [-38.7, -6.7] p=0.997 | +4.0 [-4.0, +10.7] p=0.205 | -5.3 [-16.0, +4.0] p=0.876 |
| or-gemma-4-31b-think | otf vs full_context_text | -1.3 [-6.0, +3.0] p=0.732 | +1.3 [+0.0, +4.0] p=0.368 | -6.7 [-16.0, +2.7] p=0.933 | +4.0 [-6.7, +14.7] p=0.260 | -4.0 [-14.7, +6.7] p=0.810 |
| or-gemma-4-31b-think | otf vs rag | +52.0 [+45.7, +58.3] p=0.000 | +65.3 [+54.7, +74.7] p=0.000 | +60.0 [+46.7, +73.3] p=0.000 | +65.3 [+53.3, +76.0] p=0.000 | +17.3 [+5.3, +29.3] p=0.004 |
| or-gemma-4-31b-think | otf vs pageindex | +1.7 [-2.7, +6.0] p=0.237 | +5.3 [+1.3, +10.7] p=0.015 | -5.3 [-14.7, +2.7] p=0.914 | -2.7 [-10.7, +6.7] p=0.763 | +9.3 [-1.3, +20.0] p=0.056 |

### Descriptive subtypes (accuracy %)

| System | backordered | capacity_days | first_stockout | max_backlog | shipped | stock | stockout_products |
|---|---|---|---|---|---|---|---|
| otf | 90.91 | 90.91 | 100.00 | 80.00 | 90.91 | 100.00 | 80.00 |
| full_context_text | 81.82 | 90.91 | 72.73 | 100.00 | 90.91 | 72.73 | 80.00 |
| rag | 45.45 | 36.36 | 54.55 | 40.00 | 9.09 | 9.09 | 40.00 |
| pageindex | 72.73 | 72.73 | 72.73 | 70.00 | 100.00 | 90.91 | 60.00 |
| otf | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 90.00 |
| full_context_text | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 |
| rag | 54.55 | 45.45 | 54.55 | 50.00 | 9.09 | 9.09 | 40.00 |
| pageindex | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 |
| otf | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 |
| full_context_text | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 90.91 | 100.00 |
| rag | 45.45 | 45.45 | 54.55 | 40.00 | 9.09 | 9.09 | 40.00 |
| pageindex | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 100.00 | 60.00 |
| otf_reading_only | 100.00 | 90.91 | 100.00 | 100.00 | 100.00 | 100.00 | 90.00 |

## Token consumption

Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query tokens) / questions answered.

| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| otf | 10,367.6 | 851.0 | 3,686.2 | 3,483.1 | 14,053.8 | 291,786 | 15,026.4 | 4,216,142 | 2.47 | 0.00 | 29.29 |
| full_context_text | 54,704.9 | 30,213.7 | 8,271.0 | 6,931.5 | 62,975.9 | 0 | 62,975.9 | 18,892,779 | 1.00 | 0.00 | 85.59 |
| rag | 2,387.4 | 338.6 | 1,732.0 | 1,713.3 | 4,119.4 | 0 | 4,119.4 | 1,235,810 | 1.00 | 0.00 | 14.26 |
| pageindex | 40,243.9 | 6,778.5 | 2,626.6 | 2,336.5 | 42,870.5 | 556,468 | 44,725.4 | 12,861,141 | 0.00 | 0.00 | 131.40 |
| otf | 19,123.7 | 0.0 | 4,545.0 | 4,455.5 | 23,668.7 | 429,995 | 25,102.0 | 7,100,612 | 2.50 | 0.00 | 75.34 |
| full_context_text | 82,138.8 | 0.0 | 4,017.2 | 3,993.1 | 86,156.0 | 0 | 86,156.0 | 25,846,814 | 1.00 | 0.00 | 80.62 |
| rag | 3,180.1 | 0.0 | 2,673.0 | 2,649.0 | 5,853.2 | 0 | 5,853.2 | 1,755,946 | 1.00 | 0.00 | 62.26 |
| pageindex | 67,038.8 | 0.0 | 19,026.7 | 18,828.1 | 86,065.6 | 1,061,796 | 89,604.9 | 25,819,668 | 0.00 | 0.00 | 311.49 |
| otf | 8,231.7 | 1,965.4 | 3,034.0 | 1,951.0 | 11,265.6 | 156,182 | 11,786.2 | 3,379,692 | 2.00 | 0.00 | 145.01 |
| full_context_text | 84,576.9 | 37,716.1 | 3,772.4 | 2,121.9 | 88,349.3 | 0 | 88,349.3 | 26,504,798 | 1.00 | 0.00 | 299.29 |
| rag | 3,255.0 | 200.0 | 3,448.3 | 2,493.2 | 6,703.4 | 0 | 6,703.4 | 2,011,005 | 1.00 | 0.00 | 250.78 |
| pageindex | 34,976.1 | 9,910.0 | 4,303.0 | 2,437.2 | 39,279.1 | 601,962 | 41,285.7 | 11,783,739 | 0.00 | 0.00 | 224.09 |
| otf_reading_only | 8,202.8 | 0.0 | 3,863.4 | 3,826.7 | 12,066.2 | 429,995 | 13,499.5 | 3,619,853 | 2.00 | 0.00 | 60.17 |

### Mean total tokens per question, by type

| System | descriptive | explanatory | predictive | counterfactual |
|---|---|---|---|---|
| otf | 6,297.1 | 19,217.8 | 13,045.8 | 17,654.4 |
| full_context_text | 56,100.6 | 62,445.8 | 66,410.5 | 66,946.8 |
| rag | 2,487.3 | 4,300.6 | 5,049.5 | 4,640.1 |
| pageindex | 34,660.9 | 45,999.3 | 49,196.0 | 41,625.7 |
| otf | 9,170.8 | 35,522.8 | 23,733.3 | 26,247.9 |
| full_context_text | 82,725.4 | 85,457.5 | 88,868.1 | 87,573.2 |
| rag | 4,036.4 | 5,632.9 | 7,486.7 | 6,256.7 |
| pageindex | 36,309.6 | 90,946.4 | 115,098.1 | 101,908.2 |
| otf | 8,740.2 | 11,612.9 | 12,612.3 | 12,097.1 |
| full_context_text | 84,856.1 | 88,166.7 | 91,148.6 | 89,225.8 |
| rag | 4,598.8 | 7,206.0 | 8,248.9 | 6,759.8 |
| pageindex | 32,595.0 | 37,732.3 | 45,774.3 | 41,014.9 |
| otf_reading_only | 9,162.7 | 12,235.0 | 14,071.1 | 12,795.9 |

### Setup details

- **otf**: 291,786 tokens (236,199 in / 55,587 out, 25 calls), 486.9s, info: `{"documents": 5}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.5s, info: `{"documents": 5}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 16.9s, info: `{"documents": 5}`
- **pageindex**: 556,468 tokens (424,520 in / 131,948 out, 194 calls), 1227.2s, info: `{"documents": 5}`
- **otf**: 429,995 tokens (289,035 in / 140,960 out, 23 calls), 2186.5s, info: `{"documents": 5}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 1.5s, info: `{"documents": 5}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 0.0s, info: `{"documents": 5}`
- **pageindex**: 1,061,796 tokens (575,329 in / 486,467 out, 194 calls), 1583.0s, info: `{"documents": 5}`
- **otf**: 156,182 tokens (84,264 in / 71,918 out, 15 calls), 1987.4s, info: `{"documents": 5}`
- **full_context_text**: 0 tokens (0 in / 0 out, 0 calls), 0.5s, info: `{"documents": 5}`
- **rag**: 0 tokens (0 in / 0 out, 0 calls), 0.0s, info: `{"documents": 5}`
- **pageindex**: 601,962 tokens (569,563 in / 32,399 out, 194 calls), 5346.4s, info: `{"documents": 5}`
- **otf_reading_only**: 429,995 tokens (289,035 in / 140,960 out, 23 calls), 2186.5s, info: `{"documents": 5}`
