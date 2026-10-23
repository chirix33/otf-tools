# CLEVRER document-QA benchmark (PageIndex vs. full-PDF-in-context)

This benchmark tests how well document-QA systems answer CLEVRER's four question types (descriptive,
explanatory, predictive, counterfactual) when each video is given as a text-based PDF chapter.

## Design decisions

| Decision | Choice |
|---|---|
| Split | CLEVRER **validation**, the only split with public answers |
| PDF content | Rendered from ground-truth annotations: object table, event timeline (enter / exit / collide), and a motion log (x, y, vx, vy, speed every 8 frames plus event frames). Only objects visible in the camera view are logged. |
| Leakage | Annotations cover exactly the 128 observed frames. Predictive events after the video are not in them (checked), so predictive questions need extrapolation. |
| Layout | **One PDF** holding many videos, one chapter per video, with an embedded outline. Each question names its video ("Video 10331"). |
| Pilot | 20 videos, seed 0: 52 pages, ~54k tokens, 308 questions (220 desc / 36 expl / 14 pred / 38 cf) |
| Answer contract | Strict JSON: `{"answer": "<word>"}` or `{"choices": {"<id>": true/false}}`. The same instructions go to every system ([clevrer_bench/prompts.py](clevrer_bench/prompts.py)). |
| Scoring | Descriptive: exact match after normalization. MC: per-option and per-question (every option correct), as in the CLEVRER paper. Unparseable output scores 0. |
| Tokens | Per question: input / cached input / output / reasoning. One-time setup tokens (PageIndex indexing) are reported separately and amortized over all questions. |
| Model | `gpt-5.5` for every LLM role (PageIndex index + chat, full-context baseline) |

## Systems

- `pageindex`: open-source PageIndex 0.4 in local mode. Flash tree indexing runs with `gpt-5.5`, then PageIndex's own QA agent does tree search over that index. Indexing tokens are metered by wrapping LiteLLM, and chat usage and tool calls come from the Responses envelope.
- `full_context_text`: the whole PDF's extracted text plus the question, sent through the OpenAI Responses API. The document comes first so OpenAI's prompt cache can reuse it.
- `full_context_file`: the PDF file itself, uploaded once and attached to every question. OpenAI also feeds page images, so this costs more tokens.
- Your own system: subclass `QASystem` (see [examples/my_system_template.py](examples/my_system_template.py)) and pass `--system module:Class`.

## Usage

```bash
pip install -r requirements.txt
# put OPENAI_API_KEY=... in .env (or the environment)
python run.py build  --run pilot20 --videos 20          # already done
python run.py run    --run pilot20 --system full_context_text --limit 10   # smoke test
python run.py run    --run pilot20 --system full_context_text
python run.py run    --run pilot20 --system pageindex
python run.py report --run pilot20                       # runs/pilot20/report.md + report.json
```

Runs can be resumed: answered questions are skipped, and failed ones are retried on the next
invocation. Useful flags: `--workers`, `--reasoning-effort`, `--types predictive counterfactual`,
`--system-arg key=value`.

## Layout

```
data/raw/                  CLEVRER validation questions + annotations (downloaded)
clevrer_bench/
  data.py                  sampling, QAItem
  render.py                annotations -> PDF (+ text extraction)
  prompts.py               shared instructions, question prompt, JSON parsing
  scoring.py               per-question / per-option scoring
  runner.py                build + resumable threaded runner
  report.py                aggregation -> report.md / report.json
  systems/base.py          QASystem / Usage / Prediction interface
  systems/full_context.py  baseline 1
  systems/pageindex_system.py baseline 2
runs/<run>/                document.pdf, manifest.json, items.jsonl, systems/<name>/{setup.json,predictions.jsonl}
```

## Tier B baselines (GraphRAG, ReAct-R, ReAct-C, ReCode)

One command runs (or resumes) everything for Qwen3.6-27B, then Gemma-4-31B-think, on pilot20 (dev) and E1-core
(`e1_d03, d06, d09, d12, d15`, 694 questions). Windows 11 + Python 3.11 + WSL2 Ubuntu-24.04 + one RTX 5090.
The first line runs or resumes everything; `--status` shows where it is:

```cmd
cd implementation-1
py -3.11 run_tier_b.py
py -3.11 run_tier_b.py --status
```

Put `clevrer_docqa_package` next to the repository (it is found automatically) or pass `--package <path>`.
The first run creates `.venv-tierb` from `requirements-tierb.lock`, installs vLLM in WSL (`~/venvs/vllm`) if it is
missing, and downloads the pinned checkpoints. Ctrl+C is safe: run the same command again to continue.

| Stage | What happens |
|---|---|
| Import | pilot20 + E1-core copied from the package after SHA-256 checks into `runs/<doc>/` (`items.jsonl` = questions + gold) |
| Preflight | disk, GPU in WSL, vLLM, checkpoint revisions vs SPEC sec. 2, embedding model |
| Dev (per model, per system) | pilot20 smoke test, then up to 3 predefined candidate slots on all 308 pilot questions (`runs/pilot20/systems/<system>_c<slot>__<model>/`); GraphRAG first checks extraction reliability (>10% failed chunks -> `fast` indexing) |
| Freeze | `runs/tier_b/freeze/<system>__<model>.json` + a generated block in SPEC sec. 11; E1 refuses to run if the configuration later differs |
| E1 | `runs/e1_dXX/systems/<system>__<model>/{predictions.jsonl, setup.json}` |
| Delivery | `runs/tier_b/delivery_manifest.json`, `runs/tier_b/DELIVERY.md`, `runs/e1_report.md`, `runs/e1_dXX/report.md` |

Systems: `clevrer_bench/systems/{react_system,graphrag_system,recode_system}.py`; prompts (all newly authored
method text, scanned by the domain-word guard) in `baseline_prompts.py`; metering and the 12-call cap in
`metered.py`. Every model call (setup and per question, failed attempts too) is in `calls.jsonl` next to the
predictions. Tests: `python -m pytest tests` (uses `tests/mock_vllm.py`, no GPU).
