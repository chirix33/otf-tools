# Finance answer contract (proposal)

Status: proposal, 2026-10-23. Not applied to the shared harness (see `INTEGRATION.md`). Same text for every
system; it replaces only the CLEVRER-specific answer instructions, the multiple-choice part is not needed
(every finance question is open-ended).

## Why CLEVRER's contract does not fit

CLEVRER answers are one lowercase word (`{"answer": "<one word>"}`). TAT-HQA answers are numbers with a scale
("8325" in thousands, "23.42" percent), text spans as printed ("$1.9 million", "Net revenue"), or several of
either. TAT's official metric needs the scale as a separate field: a number with the wrong scale is wrong, even
if the digits are right (1,910 thousand is not 1,910). So the reply carries a `scale` field.

## Proposed `ANSWER_INSTRUCTIONS` for the finance domain

```text
You answer questions about excerpts of company annual reports using the provided document. Each excerpt is a
chapter titled "Report R-<NNN>" with a Text section and a Table section. Each question names the report it is
about.

Reply with ONLY a JSON object and nothing else:
{"answer": <answer>, "scale": "<none|thousand|million|billion|percent>"}

- A number: give it as a JSON number or string, rounded to two decimal places (e.g. 8325, -12.5, 33.33).
  "scale" is the unit the number is in: "percent" if it is a percentage (12.5 means 12.5%), "thousand",
  "million" or "billion" if it is an amount in that scale (a table "in thousands" showing 1,910 gives
  {"answer": 1910, "scale": "thousand"}), otherwise "none".
- Text: copy the words as printed in the report, e.g. {"answer": "Net revenue", "scale": "none"}.
- Several items (the question asks for more than one value, year or name): a JSON list with each item copied
  exactly as printed in the report, e.g. {"answer": ["$14,740", "$1,910"], "scale": "thousand"}.

Question semantics: "What would X be if Y ..." asks for X recomputed with the stated change to Y and everything
else as reported.
```

The question prompt keeps the CLEVRER shape, with the scope title in place of `Video <n>` (as written to
`questions.jsonl` `prompt`):

```text
Report R-031
Question: In Report R-031: What would be the company's average goodwill impairment in 2018 and 2019 if the impairment in 2019 is doubled?
Answer with the open-ended JSON format.
```

## How replies are scored (`score.py`)

- The last JSON object in the reply is read (same rule as the shared parser). `scale` is normalised leniently:
  missing, `null`, `"none"`, `""` -> no scale; `"%"` -> percent; plurals (`"thousands"`) -> singular. Other
  values are passed through and simply will not match.
- `answer` may be a string, a number or a list; numbers become strings, lists stay lists (TAT's metric
  compares lists item by item).
- Exact match (EM, the headline) and F1 are TAT's official numbers per question: the answer and gold are
  normalised (numbers parsed, with $, commas, parentheses as negatives, % and scale words handled), the scale
  multiplied in, rounded to 2 decimals, then compared. For arithmetic and count gold, F1 = EM.
- Equivalent replies, all EM = 1 for gold 23.42 percent: `{"answer": 23.42, "scale": "percent"}`,
  `{"answer": "23.42%", "scale": "none"}`, `{"answer": 0.2342, "scale": "none"}`. For gold "$1.9 million"
  (no scale): `"$1.9 million"`, or `1.9` with scale `"million"`, or `1900000`.
- Known quirks of the official metric (kept, since they apply to every system equally and match published
  TAT-HQA numbers):
  - Rounding: 23.4 does not match gold 23.42 (hence "two decimal places" above).
  - Multi-item answers: EM sorts the items as raw strings before comparing, so `["14740", "1910"]` gets EM 0
    (F1 1) against gold `["$14,740", "$1,910"]` while `["$14,740", "$1,910"]` gets EM 1 (hence "copy exactly as
    printed"). 9 of the 300 test questions have multi-item gold.
  - The scale counts even for text answers (a text answer with a scale gets the scale word appended).
- A missing reply, no JSON object, a missing `answer`, or an empty answer scores 0.

`score.py` also reports the paired analysis TAT-HQA's paper uses: for each counterfactual question and its
factual twin (same report), whether both are right, only the factual one ("drop"), only the counterfactual one,
or neither.
