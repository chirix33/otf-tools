"""Select paired questions (counterfactual + its factual twin) and bind them to their scope.

The only change to a TAT question is the scope prefix: "In Report R-031: <question>" (TAT questions say
"the company", which is ambiguous once contexts are bundled). Leading/trailing whitespace of the released
question is dropped; inner spacing is kept. Type mapping: span, multi-span, count, arithmetic -> descriptive;
counterfactual -> counterfactual. All questions are open-ended.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass

from .data import Context, pairs
from .score import normalize_answer_value, score_one

TYPE_OF = {"span": "descriptive", "multi-span": "descriptive", "count": "descriptive",
           "arithmetic": "descriptive", "counterfactual": "counterfactual"}


@dataclass
class Question:
    scope: str
    question_id: int            # 1 = factual twin, 2 = counterfactual
    tat: dict                   # the released question record (answer, scale, derivation, ...)
    tat_context_uid: str
    twin_tat_uid: str

    @property
    def qtype(self) -> str:
        return TYPE_OF[self.tat["answer_type"]]

    @property
    def question(self) -> str:
        return f"In {self.scope}: {self.tat['question'].strip()}"


def scoped_question(scope: str, tat_question: str) -> str:
    return f"In {scope}: {tat_question.strip()}"


def gold_answer_str(answer) -> str:
    """A flat string of the gold answer for the QAItem `gold_answer` field (informational; scoring uses
    gold.jsonl through domains.finance.score)."""
    return json.dumps(answer) if isinstance(answer, list) else str(answer)


def self_scores(q: dict) -> bool:
    """The gold answer, given as the prediction, gets full marks from TAT's metric (excludes malformed gold,
    e.g. one train multi-span answer with an empty span)."""
    s = score_one(q, normalize_answer_value(q["answer"]), q["scale"])
    return s["em"] == 1 and s["f1"] == 1


def usable_pairs(ctx: Context) -> list[tuple[dict, dict]]:
    return [(cf, t) for cf, t in pairs(ctx) if self_scores(cf) and self_scores(t)]


def select(scoped: list[tuple[str, Context]], n_pairs: int, rng: random.Random) -> list[Question]:
    """n_pairs contexts of the document, chosen at random, one (counterfactual, twin) pair each."""
    eligible = [(t, c) for t, c in scoped if usable_pairs(c)]
    if len(eligible) < n_pairs:
        raise RuntimeError(f"only {len(eligible)} contexts with a pair, {n_pairs} needed")
    out: list[Question] = []
    for title, ctx in rng.sample(eligible, n_pairs):
        cf, twin = rng.choice(usable_pairs(ctx))
        out.append(Question(title, 1, twin, ctx.uid, cf["uid"]))
        out.append(Question(title, 2, cf, ctx.uid, twin["uid"]))
    return out
