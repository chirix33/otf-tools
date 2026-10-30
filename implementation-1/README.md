# OTF-Tools: compile a document once, answer its questions cheaply

OTF-Tools answers questions about long documents that record a process, such as a physics event log, a production ledger, or a cluster scheduler log. It does not reread the document for every question. Instead it does this:

1. **Map (no LLM).** It builds a Navigation Map from the PDF's outline, tables, and lines, so a question can go straight to the part of the document it names (its *scope*).
2. **Compile (once per document).** The LLM writes reader functions that pull the recorded inputs, outcomes, and constants out of the map, and a `simulate` function that reruns the process.
3. **Check.** The program is accepted only if it can forecast outcomes hidden from it, with mean F1 ≥ 0.4, and passes three tests against shortcuts. A program that passes is stored in a library and reused on other documents with the same structure, after it passes the check on each new document too.
4. **Answer (2–3 calls per question).** A router picks the question type (descriptive, explanatory, predictive, or counterfactual) and runs that type's tool in a sandbox. A what-if question becomes a patch on the recorded inputs, and the checked simulator reruns from the point where the change first matters. One final LLM call then writes the answer from the tool's evidence. If no program passed, the system falls back to reading the named scope.

Every LLM call, including PageIndex's tree building and OTF-Tools' program writing, uses the model under test. One-time setup tokens are reported and spread over the questions.

## Benchmarks

| Workload | Runs | Source | Question types |
|---|---|---|---|
| Physics E1 | `runs/e1_d01`–`e1_d15` | CLEVRER validation: 300 test videos, 15 documents of 20 videos (~54k tokens each) | all four |
| Physics E2 | `runs/e2_d01` | The same 300 videos in one 784-page document (~838k tokens). It has the same 1,067 explanatory and counterfactual questions as E1. | explanatory, counterfactual |
| Manufacturing | `runs/mfg_d01`–`mfg_d05` | SupplyGraph production and sales records, with a reference stock-and-dispatch simulator | all four |
| IT operations | `runs/itops_d01`–`itops_d05` | Google cluster trace 2011, with a reference scheduler simulator | all four |
| Finance | `runs/fin_d01`–`fin_d03` | TAT-HQA annual-report tables and text (no process to simulate) | descriptive, counterfactual |

`runs/pilot20` and the `*_dev` documents are development data. Prompts and the router were tuned only there, and none of their results appear in the paper. Gold answers come from the dataset or from the reference simulator, never from an LLM. The domain specs are in [docs/domains/](docs/domains/README.md), and each domain's checks are in `domains/<domain>/VALIDATION.md`.

## Systems

Pass these names to `run.py run --system`:

| Name | What it is |
|---|---|
| `otf` | OTF-Tools ([clevrer_bench/systems/otf_system.py](clevrer_bench/systems/otf_system.py), which wraps the [otf/](otf/) package) |
| `otf_oracle` | The same engine with a hand-written process model ([oracle/oracle_model.py](oracle/oracle_model.py)). This is an upper bound for physics. |
| `full_context_text` | The whole document text plus the question, in one call. On E2 it keeps whole pages up to the context limit. |
| `rag` | 512-token chunks with section paths, `bge-small-en-v1.5` embeddings, top 5 chunks, one answer call |
| `pageindex` | `pageindex==0.4.0` in local mode |
| `module:Class` | Any subclass of `QASystem` ([clevrer_bench/systems/base.py](clevrer_bench/systems/base.py)) |

The GraphRAG, ReAct-R, ReAct-C, and ReCode baselines and their predictions are on the `react-baselines` branch. Their design is in [docs/new_baselines_design.md](docs/new_baselines_design.md).

The OTF-Tools ablations are selected with `--system-arg`: `ablation=reading_only`, `ablation=no_replay`, and `use_library=false`.

## Setup

```bash
pip install -r requirements.txt fastembed
```

Put `OPENROUTER_API_KEY=...` in `.env`. Never commit that file; it is git-ignored.

**Models.** Models are aliases in [configs/models.json](configs/models.json). The paper uses the hosted aliases. Each is pinned to one OpenRouter provider with no fallbacks, a 16,384-token output cap, and a 131,072-token context:

| Alias | Model | Provider, precision | Sampling |
|---|---|---|---|
| `or-gpt-oss-20b` | gpt-oss-20b | CoreWeave, fp4 | reasoning effort medium |
| `or-qwen3.6-27b` | Qwen3.6-27B | Alibaba, precision not listed | T 1.0, top-p 0.95, top-k 20, thinking on |
| `or-gemma-4-31b-think` | Gemma-4-31B-it | Crusoe, bf16 | T 1.0, top-p 0.95, top-k 64, thinking on |

The aliases without `or-` point at a local vLLM server ([scripts/serve.sh](scripts/serve.sh)).

**Data.** The raw data is git-ignored. For physics, put CLEVRER's `validation.json` and `annotations/` in `data/raw/`. For the other domains, put the source data in `data/domains/raw/`, as listed in [docs/domains/README.md](docs/domains/README.md). The built benchmark documents, questions, and gold answers are already committed under `runs/`.

## Usage

Rebuild the benchmarks. The physics split excludes the pilot20 videos and keeps 25% of the descriptive questions:

```bash
python run.py build-split --name e1 --videos 300 --per-doc 20 --seed 1
```

```bash
python -m domains.manufacturing.build
```

`domains.it_ops.build` and `domains.finance.build` work the same way.

Run a system and write reports. `--run` accepts a glob, and runs resume: answered questions are skipped and failed ones are retried.

```bash
python run.py run --run "e1_d*" --system otf --model or-qwen3.6-27b --workers 8
```

```bash
python run.py report-split --name e1
```

```bash
python scripts/hosted_reports.py
```

`report-split` writes `runs/e1_report.md`. `hosted_reports.py` writes the final `runs/<split>_hosted_report.{md,json}` files for the hosted models only.

[scripts/run_hosted.py](scripts/run_hosted.py) runs every hosted job in the paper. It runs `run.py` per split, system, and model, with up to three passes, then the library recheck ([scripts/otf_library_pass.py](scripts/otf_library_pass.py)) and the ablations:

```bash
python scripts/run_hosted.py --phase main e2 ablations --dry-run
```

Other useful `run.py run` flags: `--limit`, `--per-type`, `--types`, `--shard k/n`, and `--reasoning-effort`.

**Scoring.** Descriptive answers are scored by exact match after normalization, and finance answers by TAT-QA's numeric match. Multiple-choice questions count as correct only when every option is right. A question with no valid answer, or one that ends in an error, counts as wrong. Reports give 95% bootstrap intervals and paired differences on the same questions.

## Layout

```
otf/                    the method; document-agnostic (no benchmark words, enforced by tests/)
  navmap.py             Navigation Map from the PDF (no LLM)
  records.py            inputs / outcomes / constants, blinding, patches, replay
  toolgen.py            writes the readers and simulate, and runs the forecast check
  engine.py             prepare(pdf) and answer(question): route, run the tool, answer
  library.py            stores checked programs by document structure; reuse after recheck
  sandbox.py            runs generated code in an isolated Python process with an import allowlist
  prompts.py            generic prompts; nothing names a domain
clevrer_bench/          harness: data, PDF rendering, shared prompts, scoring, runner, reports
  systems/              otf, full context, RAG, PageIndex adapters and the QASystem interface
domains/                manufacturing, it_ops, finance: data, reference simulators, questions, builders
oracle/                 hand-written physics process model (upper bound)
configs/models.json     model aliases, providers, sampling settings
scripts/                hosted and local orchestration, library recheck, reports, dev helpers
tests/                  python -m pytest tests
runs/<run>/             document.pdf, manifest.json, items.jsonl, gold, systems/<system>__<model>/{setup.json,predictions.jsonl}
SPEC.md                 the frozen experiment spec and its dated change log
```

## Tests

```bash
python -m pytest tests
```

Without pytest, run each file directly (`python tests/test_records.py`). `test_no_benchmark_words.py` keeps benchmark vocabulary out of `otf/`. `test_records.py` checks blinding, the forecast check, patches, and replay on two small hand-made documents, with no PDF and no LLM.
