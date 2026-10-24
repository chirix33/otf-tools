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

Hosted models (OpenRouter): put `OPENROUTER_API_KEY=...` in `.env` and use an `or-*` alias from
`configs/models.json`, for example `python run.py run --run "mfg_d*" --system rag --model or-gpt-oss-20b`.
Each alias is locked to one provider; see SPEC.md sec. 2.

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
