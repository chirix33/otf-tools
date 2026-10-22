"""Deterministic scoring against CLEVRER gold labels."""
from __future__ import annotations

from .data import QAItem


def score(item: QAItem, parsed: dict) -> dict:
    """Returns {"question_correct": bool, "options_correct": int, "options_total": int}.
    Descriptive questions count as a single option. Parse errors score zero."""
    if not item.is_mc:
        ok = parsed.get("answer") == item.gold_answer
        return {"question_correct": ok, "options_correct": int(ok), "options_total": 1}
    pred = parsed.get("choices") or {}
    n_ok = sum(pred.get(cid) == gold for cid, gold in item.gold_choices.items())
    total = len(item.gold_choices)
    return {"question_correct": n_ok == total and "parse_error" not in parsed,
            "options_correct": n_ok, "options_total": total}
