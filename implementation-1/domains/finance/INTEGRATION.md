# Wiring the finance domain into the shared harness (not applied)

Status: 2026-10-23. Nothing below has been changed: the harness is in use by live experiments, which import it
at process start. Line references are to the files as of today.

## Shortest path (no harness change for scoring)

`score.py` already reads the harness's own `systems/<name>/predictions.jsonl` (it parses each row's
`raw_text`), so once systems have answered, scoring is:

```bash
python -m domains.finance.score --gold runs/fin_d01/gold.jsonl runs/fin_d02/gold.jsonl runs/fin_d03/gold.jsonl --pred runs/fin_d01/systems/<name>/predictions.jsonl runs/fin_d02/systems/<name>/predictions.jsonl runs/fin_d03/systems/<name>/predictions.jsonl --out runs/fin_<name>_score.json
```

What does need changing is how questions are put to systems (items 1 to 3 below); items 4 and 5 make
`run.py report` show the right numbers.

## Changes, file by file

1. **`clevrer_bench/data.py`, `QAItem.is_mc` (line 29).** It returns True for any item whose
   `question_type` is `counterfactual` (CLEVRER's counterfactuals are multiple-choice). Finance counterfactuals
   are open-ended, so as is they would be stripped to `multiple_choice` and prompted with an empty choice list.
   Change to decide by format, e.g. `return bool(self.choices) or self.question_type == HIDDEN_MC` (CLEVRER MC
   items always have choices, so CLEVRER behaviour is unchanged). Manufacturing's counterfactuals are
   multiple-choice with choices, so it is unaffected (IT operations not checked: its benchmark is still being
   built).

2. **`clevrer_bench/prompts.py`.**
   - `ANSWER_INSTRUCTIONS` (line 10) names CLEVRER videos. Add `FINANCE_ANSWER_INSTRUCTIONS` with the text in
     `ANSWER_CONTRACT.md` and an `answer_instructions(domain)` lookup (domain from `manifest.json["domain"]`;
     absent = CLEVRER).
   - `build_question_prompt` (line 26) writes `Video {scene_index}` as line 1. For finance `scene_index` is the
     scope title (`Report R-031`), so line 1 must be `str(item.scene_index)` when it is a string, or the runner
     can use `questions.jsonl` `prompt` directly (identical text).
   - `parse_prediction` (line 63): for finance keep the answer as given and keep the scale, i.e. return
     `{"answer": obj["answer"], "scale": obj.get("scale")}`. `normalize_word` must not be applied (it lowercases,
     strips punctuation and would turn a list into its string form).

3. **`clevrer_bench/runner.py`, `run_system` (lines ~60-130).** Read `domain` from `manifest.json`; pass
   `answer_instructions(domain)` instead of `ANSWER_INSTRUCTIONS` to `system.answer` (line 103); call the
   finance scorer (item 4) with the gold row. Gold rows are in `run_dir/gold.jsonl` (keyed by uid); the
   `gold_answer` string in `items.jsonl` is informational only (a flat string; lists are JSON-encoded) and is
   not enough to score (no scale, no answer type).

4. **`clevrer_bench/scoring.py`, `score` (line 7).** Dispatch on domain: for finance,
   `s = domains.finance.score.score_one(gold_row, normalize_answer_value(parsed["answer"]), normalize_scale(parsed.get("scale"))[0])`
   and return `{"question_correct": s["em"] == 1, "options_correct": int(s["em"] == 1), "options_total": 1,
   "em": s["em"], "f1": s["f1"], "scale_correct": s["scale_correct"]}`; parse errors score 0. With
   `question_correct` = exact match, `report.py`'s question accuracy is the TAT EM headline without change.

5. **`clevrer_bench/report.py`.**
   - `make_split_report` (line ~250) reads `build_config["n_videos"]` and `["motion_stride"]`, which only CLEVRER
     build configs have (manufacturing's lack them too); use `n_scopes` and `.get("motion_stride")`.
   - Optional: an F1 column (mean of `score.f1`) and the paired factual/counterfactual table that
     `domains.finance.score.score_predictions` computes (`pairs`). Per-type rows already work
     (`question_type` is descriptive or counterfactual).
   - `to_markdown` says "Videos"; cosmetic.

## Not needed

- Systems (`clevrer_bench/systems/*`): they read `document.pdf` and the manifest's outline; the finance PDF has
  the same structure (scope = level-0 outline entry, children `Text` and `Table`), and `manifest.json` carries
  the CLEVRER-shaped `videos` list that the report code reads.
- `items.jsonl` loads with `clevrer_bench.data.load_items` as is (checked: 100 items, `scene_index` =
  `"Report R-002"`); all files are ASCII JSON, so the default-encoding `read_text()` is safe.
- No `navmap.json` is written (it comes from `otf/navmap.py`, which the benchmark must not import).
- OTF-specific notes (header rule for numeric year headers, guard-test vocabulary) belong to the OTF session;
  see `docs/domains/otf_v3_design.md`.
