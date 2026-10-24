"""Deterministic scoring against CLEVRER gold labels."""
from __future__ import annotations

from .data import QAItem


def score(item: QAItem, parsed: dict, domain: str | None = None, gold: dict | None = None) -> dict:
    """Returns {"question_correct": bool, "options_correct": int, "options_total": int}.
    Descriptive questions count as a single option. Parse errors score zero.
    Finance (`gold` = the question's row of gold.jsonl) uses TAT-QA's metric: question_correct = exact match
    with the right scale; em, f1 and scale_correct are added."""
    if domain == "finance":
        from domains.finance.score import normalize_answer_value, normalize_scale, score_one
        if "parse_error" in parsed or gold is None:
            return {"question_correct": False, "options_correct": 0, "options_total": 1,
                    "em": 0.0, "f1": 0.0, "scale_correct": False}
        s = score_one(gold, normalize_answer_value(parsed.get("answer")), normalize_scale(parsed.get("scale"))[0])
        ok = s["em"] == 1
        return {"question_correct": ok, "options_correct": int(ok), "options_total": 1, **s}
    if not item.is_mc:
        ok = parsed.get("answer") == item.gold_answer
        return {"question_correct": ok, "options_correct": int(ok), "options_total": 1}
    pred = parsed.get("choices") or {}
    n_ok = sum(pred.get(cid) == gold for cid, gold in item.gold_choices.items())
    total = len(item.gold_choices)
    return {"question_correct": n_ok == total and "parse_error" not in parsed,
            "options_correct": n_ok, "options_total": total}
