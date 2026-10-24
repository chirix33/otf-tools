# Domain spec: Finance (TAT-HQA)

Status: DRAFT 2026-10-23. Paper name: "finance".

## Source

TAT-HQA (Li et al., "Learning to Imagine", ACL 2022), built on TAT-QA (Zhu et al., ACL 2021); repository
`NExTplusplus/TAT-HQA`, Apache-2.0. Real tables and paragraphs from company annual reports ("hybrid contexts"),
with crowd-annotated questions, answers, scale (thousand, million, percent) and derivations. Each hypothetical
question has `answer_type = counterfactual` and points to its factual twin via `rel_question`.

Splits with answers: dev (274 contexts; 824 counterfactual, 1,644 factual: 690 span, 216 multi-span,
706 arithmetic, 32 count) and train (2,207 contexts; 6,627 counterfactual). The test split's answers are hidden.

**Everything is real**, including gold. This is the domain where nobody can say we built the data to suit OTF.

## Question types

- **Descriptive** = factual questions (span, multi-span, count, arithmetic).
- **Counterfactual** = hypothetical questions ("What would be ... if the impairment in 2019 is doubled?").
- **No explanatory or predictive questions exist**; the paper reports this domain on two types and says so.

## Document layout

- Contexts are bundled into large PDFs, like CLEVRER's 20-video documents: about 90 contexts per document,
  each context one **scope** titled `Report R-001` ... (our id; the original `uid` is kept in the manifest).
- Each scope: the paragraphs as text, then the table rendered as a real PDF table (headers are years and labels,
  numbers as printed, including parentheses and dashes).
- Front matter: one short paragraph saying the document collects excerpts of annual reports, each with a
  table and its accompanying text, amounts as printed with their stated scale.
- 3 test documents from dev contexts + 1 dev document (from train contexts, smoke tests only).

## Questions

- The only change to a question: a scope prefix, e.g. `In Report R-031: What would be the company's average
  goodwill impairment ...` (TAT questions say "the company", which is ambiguous once contexts are bundled).
  Applied identically for every system; disclosed in the paper.
- Selection: ~150 counterfactual questions and their ~150 factual twins (paired, same contexts), stratified
  across contexts. Pairing allows a per-system "factual vs hypothetical drop" analysis, the TAT-HQA paper's own
  framing.

## Scoring (needs a harness extension; CLEVRER's contract unchanged)

TAT answers are numbers with a scale, or text spans, not one word. Plan:
- Answer contract for this domain: `{"answer": "<number or short text>", "scale": "<none|thousand|million|billion|percent>"}`
  (one domain-level addition to the shared instructions, same for every system).
- Score with TAT-QA's official evaluator (`tatqa_eval.py`, exact match and numeracy-aware F1 with scale);
  report exact match as the headline, F1 as secondary.

## Risks (state them in the paper)

- The counterfactuals are one-step arithmetic over table cells (no process unfolding over time), so OTF's
  simulator has no obvious advantage here; vanilla full-context may do well. This domain tests whether OTF
  degrades gracefully where there is no process to model.
- Table rendering: headers are numeric (years), which the current Navigation Map's header rule (short
  alphabetic words) does not detect; see the OTF review notes.

## As built (2026-10-23)

Code: `domains/finance/` (`data.py`, `render.py`, `questions.py`, `build.py`, `tatqa_metric.py`, `score.py`,
`validate.py`). Rebuild: `python -m domains.finance.build && python -m domains.finance.validate` (from
`implementation-1/`; deterministic, seed 2027). Report: `domains/finance/VALIDATION.md` (PASS). Answer contract
proposal: `domains/finance/ANSWER_CONTRACT.md`. Harness changes needed (not applied): `domains/finance/INTEGRATION.md`.

### Documents and questions

| run | TAT split | reports | pages | ~tokens | descriptive | counterfactual |
|---|---|---|---|---|---|---|
| fin_d01 | dev | 92 (R-001..R-092) | 105 | 46k | 50 | 50 |
| fin_d02 | dev | 91 (R-093..R-183) | 103 | 46k | 50 | 50 |
| fin_d03 | dev | 91 (R-184..R-274) | 95 | 33k | 50 | 50 |
| fin_dev | train | 30 (R-901..R-930) | 31 | 12k | 20 | 20 |

- All 274 dev contexts are used, shuffled (seed 2027) and dealt into the 3 test documents, each kept in
  released-file order; report numbers run across the three documents so every scope title is unique.
- Per test document, 50 contexts are drawn at random and one (counterfactual, factual twin) pair is taken from
  each: 300 questions, 150 pairs, 150 distinct contexts; the other 124 contexts are distractors. No context has
  more than one pair. The selected mix follows the dev population closely (counterfactual formats: 84%
  arithmetic vs 86%; scales and answer sources within about ten points; table in VALIDATION.md).
- Dev document: 30 train contexts drawn at random (seed 2028), 20 pairs, 40 questions. Smoke tests only.
- Pairs not used (gold doubtful): a counterfactual whose twin is shared with another counterfactual (1 in dev);
  a counterfactual whose answer or scale differs between `dataset_raw` and `dataset_extra_field` (3 in dev, 19 in
  train); a pair whose gold does not score full marks against itself (0 in dev; 1 in train, a multi-span answer
  with an empty span). 819 eligible pairs remain in dev.
- Question text: `In Report R-NNN: ` + the released question with outer whitespace stripped (42 dev questions
  have leading or trailing spaces); inner spacing, typos and casing are kept.
- uids: `fin-<NNN>-01` (factual twin) and `fin-<NNN>-02` (counterfactual); `gold.jsonl` has `pair_uid` and the
  TAT uids (`tat_uid`, `tat_pair_uid`, `tat_context_uid`); `manifest.json` has each scope's TAT table and
  paragraph uids.
- Files per run folder, as in `runs/mfg_d01`: `document.pdf`, `manifest.json` (with `scopes` and the
  CLEVRER-shaped `videos` list), `build_config.json`, `items.jsonl` = `items_all.jsonl` (QAItem fields,
  `scene_index` = scope title, `question_subtype` = TAT answer type), `questions.jsonl` (no type, no gold;
  `prompt` = CLEVRER prompt shape with the scope title as line 1), `gold.jsonl` (answer, scale, derivation,
  answer_type, eval_answer_type, answer_from, rel_paragraphs, req_comparison). No `gold_meta.jsonl`: there is no
  hidden intervention, all gold is TAT's.

### Rendering

- Front matter: the one paragraph from the spec (what the excerpts are, chapter titles, amounts as printed with
  their stated scale), then the list of chapter titles (as in the manufacturing documents). Each report starts
  on a new page; order inside a report: Text (paragraphs in released order), then Table.
- Outline: each report is a level-0 entry with level-1 children `Report R-NNN: Text` and `Report R-NNN: Table`.
- Tables are ruled grids (reportlab GRID). Every cell is printed as released: numbers keep parentheses, dashes,
  $, %, currency signs and spacing; multi-row headers and the row-label column are kept, empty cells stay empty.
  Styling only: leading header rows bold (repeated if a table ran onto a second page; none does); in a header
  row a label followed by empty cells spans them when the header row below has labels there ("Years Ended
  December 31," over 2019 | 2018); all-empty rows keep a visible height. Column widths are measured so that no
  number or word is ever broken inside a cell; all 304 tables fit at 7.5 pt.
- Fonts (revised 2026-10-23 after a report of `£m` extracting as U+FFFD): Helvetica / Helvetica-Bold, the
  standard PDF fonts with the standard WinAnsi encoding, for every character that encoding covers (all of
  fin_d01 and fin_dev). Arial (embedded TrueType) only for the rest: U+2212 minus (14), U+2015 bar (1) and
  U+2022 bullet (35), the last because reportlab writes it as WinAnsi code 127, which pdfminer reads as
  "(cid:127)". Reason: the first build used Arial for everything, and reportlab gives every non-ASCII character
  of a TrueType subset a private code (`£` was byte 0x01) that only the font's ToUnicode table explains. All four
  extractors installed here honour that table, and none returned U+FFFD on the old files, so I could not
  reproduce the report; but any reader that skips the table gets control bytes or U+FFFD. With the standard
  encoding, `£`, `€`, quotes and dashes need no table at all; only the 50 fallback characters still rely on it.
  Page counts, layout and every question/gold/manifest file are unchanged by the switch (same metrics).
- Character substitutions, the only changes to any text, made so the PDF text layer reads back exactly as the
  printed source (render.py `printable`):
  - no-break space and thin space -> space. Some paragraphs separate every word with U+00A0, which the layout
    engine treats as one unbreakable line and cuts mid-word.
  - U+2010 / U+2011 hyphens -> "-". reportlab maps those glyphs to no character in the text layer, so
    "in-store" read "instore". They occur only in paragraph text, never in cells, questions or answers.
  - ligatures U+FB01 / U+FB02 -> "fi" / "fl" (5 in dev). They are left over from the reports' own PDF
    extraction, and readers disagree on whether they return the ligature or the two letters.
  - U+207E and full-width ， ： ？ -> `)` `,` `:` `?` (no glyph in Arial; train split only, none in our documents).

### Scoring

- `score.py` scores a `predictions.jsonl` (the harness's own file works: it parses `raw_text`) with TAT's metric:
  exact match (headline) and numeracy-aware F1 with scale, per type, per TAT answer type and source, and the
  paired factual -> counterfactual table.
- The metric is vendored in `tatqa_metric.py` (Apache-2.0, attributed). Reasons: TAT's `tatqa_eval.py` does not
  run as shipped (it calls `TaTQAEmAndF1` without the required `pred_type` argument and unpacks four values from
  a three-value return), and scipy and pandas are not installed here. Copied functions are AST-identical to the
  originals; scipy's assignment solver is replaced by a pure-Python Hungarian algorithm; validation checks both
  against TAT's original class on 3,332 predictions (all agree).
- **Deviation: `eval_answer_type`.** The raw file types every hypothetical question `counterfactual`, and the
  metric then stringifies the gold, so the 26 dev counterfactuals with list answers could never be matched (not
  even by their own gold). TAT-HQA's evaluation files (`dataset_extra_field/counter`, which its official
  `evaluate.py` is run on) give each hypothetical question its answer format (arithmetic, span, multi-span,
  count). Gold keeps `answer_type: counterfactual` and adds that format as `eval_answer_type`, which the metric
  uses. With it every one of the 2,465 usable dev questions self-scores 100%.
- **Deviation: the answer contract allows a list.** The spec's `{"answer": "<number or short text>", "scale": ...}`
  is extended with a JSON list for questions asking for several items (32 of 300 gold answers are lists, 9 with
  more than one item); otherwise multi-span gold cannot be matched. Known metric quirks (2-decimal rounding,
  order-sensitive EM on multi-item answers unless items are copied as printed) are documented in
  ANSWER_CONTRACT.md and kept, so numbers stay comparable with published TAT-HQA results.

### Checks (VALIDATION.md)

PASS on all runs: gold fidelity to the released records, pairing, scope titles in every question and prompt,
self-score 100%, outline and page counts, every paragraph in the text layer, every table found by pdfplumber as a
grid with released shape and identical cell text (11,331 cells), and an exact character round-trip. In that
check, every page is read with pdfplumber `extract_text` and `extract_words`, pypdfium2 and PyPDF2, and:
- no page holds U+FFFD, U+FFFE, a control character or `(cid:N)`;
- per scope and for the front matter, the characters read back equal the printed source exactly (304/304
  scopes, 464,023 characters, 966 of them non-ASCII, in every extractor).

Baseline "copy the factual twin's answer" gets
EM 0.01 on the counterfactuals. 20 seeded questions are written out with their excerpt for hand-checking.

### Reviewer pushback to expect (beyond the risks above)

- **Contamination.** TAT-QA/TAT-HQA dev has been public since 2021/2022; models may have seen the contexts and
  answers. It affects all systems equally (same model underneath), but say so; the hidden-answer test split
  cannot be used because we need gold.
- **Scale annotations.** 2 of the 153 questions with a thousand/million/billion gold scale have no scale cue in
  their excerpt (the annotators saw the full report page). Reported, not corrected.
- **Metric quirks** are the official ones (see Scoring); report EM and F1 both.
- **Prefix.** The only edit to questions is the scope prefix; a reviewer may ask whether it helps retrieval
  systems unevenly. It is applied identically to every system and is needed once contexts are bundled.
