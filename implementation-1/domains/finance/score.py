"""Score finance predictions with TAT-QA's official metric (exact match and numeracy-aware F1, with scale).

    python -m domains.finance.score --gold runs/fin_d01/gold.jsonl [more gold.jsonl ...] \
        --pred <predictions.jsonl> [more ...] [--out score.json]

Gold: rows of runs/fin_*/gold.jsonl (answer, scale, answer_type as released by TAT-HQA; the metric uses
`eval_answer_type`, the answer format TAT-HQA's own evaluation files give hypothetical questions, see data.py).
Predictions: one JSON object per line with "uid" and one of
  - "raw_text": the system's reply; the last JSON object in it is read as {"answer": ..., "scale": ...}
    (this is what the shared harness writes to systems/<name>/predictions.jsonl);
  - "parsed": {"answer": ..., "scale": ...};
  - top-level "answer" and "scale".
If several are present, "raw_text" wins (the harness's `parsed` field holds the CLEVRER one-word normalisation,
which drops the scale). Missing, unparsable or empty answers score 0. The answer contract is in
ANSWER_CONTRACT.md.

Per question: em and f1 exactly as tag_op/tatqa_metric.py TaTQAEmAndF1 computes them (see tatqa_metric.py; for
arithmetic and count gold, f1 = em). Reported: exact match (headline) and F1, overall, per question type
(descriptive / counterfactual), per TAT answer type and answer source, and the paired factual -> counterfactual
analysis (pairs share a context; "drop" = factual twin right, counterfactual wrong).
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from .tatqa_metric import em_f1

SCALES = ("", "thousand", "million", "billion", "percent")
_SCALE_ALIASES = {"none": "", "null": "", "no": "", "n/a": "", "na": "", "-": "", "units": "", "unit": "",
                  "one": "", "ones": "", "%": "percent", "percentage": "percent", "pct": "percent",
                  "thousands": "thousand", "millions": "million", "billions": "billion", "percents": "percent"}


def normalize_scale(scale) -> tuple[str, bool]:
    """(TAT scale string, valid?). None / "none" / "" -> "" (no scale). Unknown values are kept lowercased
    (TAT's metric then treats them as it would: a mismatch for numbers unless they contain a scale word)."""
    if scale is None:
        return "", True
    s = str(scale).strip().lower()
    s = _SCALE_ALIASES.get(s, s)
    return s, s in SCALES


def normalize_answer_value(answer):
    """JSON answer -> what TAT's metric expects: a string, or a list of strings for several items."""
    if answer is None or isinstance(answer, bool):
        return None if answer is None else str(answer).lower()
    if isinstance(answer, (int, float)):
        return str(answer)
    if isinstance(answer, list):
        vals = [normalize_answer_value(a) for a in answer]
        vals = [v for v in vals if v not in (None, "")]
        return vals or None
    s = str(answer).strip()
    return s or None


def _last_json_object(text: str):
    """The last top-level JSON object in `text` (same rule as the shared harness's parser)."""
    text = re.sub(r"```(?:json)?", "", text)
    decoder = json.JSONDecoder()
    found, i = None, 0
    while (i := text.find("{", i)) != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(obj, dict):
            found = obj
        i = end
    return found


def parse_prediction(row: dict) -> dict:
    """{"answer", "scale", "scale_valid"} or {"parse_error": ...}."""
    if row.get("raw_text") is not None:
        obj = _last_json_object(row["raw_text"] or "")
        if obj is None:
            return {"parse_error": "no JSON object"}
    elif isinstance(row.get("parsed"), dict) and "answer" in row["parsed"]:
        obj = row["parsed"]
    elif "answer" in row:
        obj = row
    else:
        return {"parse_error": "no answer field"}
    if "answer" not in obj:
        return {"parse_error": "missing 'answer'"}
    scale, valid = normalize_scale(obj.get("scale"))
    return {"answer": normalize_answer_value(obj["answer"]), "scale": scale, "scale_valid": valid}


def score_one(gold: dict, answer, scale: str = "") -> dict:
    """em, f1 (TAT metric) and whether the scale matches, for one gold row and one answer."""
    gt = {"answer": gold["answer"], "answer_type": gold.get("eval_answer_type", gold["answer_type"]),
          "scale": gold["scale"]}
    em, f1 = em_f1(gt, answer, scale)
    return {"em": float(em), "f1": float(f1), "scale_correct": scale == gold["scale"]}


def load_jsonl(paths) -> list[dict]:
    rows = []
    for p in paths:
        rows += [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
    return rows


def _mean(xs):
    return round(sum(xs) / len(xs), 4) if xs else None


def score_predictions(gold_rows: list[dict], pred_rows: list[dict]) -> dict:
    preds = {r["uid"]: r for r in pred_rows if "error" not in r}
    per = []
    for g in gold_rows:
        p = parse_prediction(preds[g["uid"]]) if g["uid"] in preds else {"parse_error": "no prediction"}
        if "parse_error" in p:
            s = {"em": 0.0, "f1": 0.0, "scale_correct": False}
        else:
            s = score_one(g, p["answer"], p["scale"])
        per.append({"uid": g["uid"], "question_type": g["question_type"], "answer_type": g["answer_type"],
                    "answer_from": g["answer_from"], "pair_uid": g.get("pair_uid"), **s,
                    "pred_answer": p.get("answer"), "pred_scale": p.get("scale"),
                    "parse_error": p.get("parse_error"), "scale_valid": p.get("scale_valid")})

    def summary(rows):
        return {"n": len(rows), "em": _mean([r["em"] for r in rows]), "f1": _mean([r["f1"] for r in rows]),
                "scale_acc": _mean([float(r["scale_correct"]) for r in rows]),
                "missing": sum(r["parse_error"] == "no prediction" for r in rows),
                "parse_errors": sum(r["parse_error"] not in (None, "no prediction") for r in rows)}

    groups = defaultdict(lambda: defaultdict(list))
    for r in per:
        for key in ("question_type", "answer_type", "answer_from"):
            groups[key][r[key]].append(r)
    by_uid = {r["uid"]: r for r in per}
    pairs = [(by_uid[r["pair_uid"]], r) for r in per
             if r["question_type"] == "counterfactual" and r.get("pair_uid") in by_uid]
    pair = {"n_pairs": len(pairs),
            "factual_em": _mean([f["em"] for f, _ in pairs]), "counterfactual_em": _mean([c["em"] for _, c in pairs]),
            "both_right": sum(f["em"] == 1 and c["em"] == 1 for f, c in pairs),
            "factual_right_cf_wrong": sum(f["em"] == 1 and c["em"] < 1 for f, c in pairs),
            "factual_wrong_cf_right": sum(f["em"] < 1 and c["em"] == 1 for f, c in pairs),
            "both_wrong": sum(f["em"] < 1 and c["em"] < 1 for f, c in pairs)}
    return {"overall": summary(per),
            **{f"by_{k}": {g: summary(v) for g, v in sorted(groups[k].items())} for k in groups},
            "pairs": pair, "per_question": per}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gold", nargs="+", required=True, help="gold.jsonl file(s)")
    ap.add_argument("--pred", nargs="+", required=True, help="predictions.jsonl file(s)")
    ap.add_argument("--out", help="write the full report (with per-question rows) as JSON here")
    a = ap.parse_args()
    rep = score_predictions(load_jsonl(a.gold), load_jsonl(a.pred))
    if a.out:
        Path(a.out).write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "per_question"}, indent=2))


if __name__ == "__main__":
    main()
