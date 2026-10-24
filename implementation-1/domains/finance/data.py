"""Load TAT-HQA hybrid contexts (one table + its paragraphs + questions) exactly as released.

Raw data: data/domains/raw/tat-hqa/dataset_raw/ (Apache-2.0; Li et al., ACL 2022, built on TAT-QA, Zhu et al.,
ACL 2021). The dev split gives the test documents; the train split is used only for the dev document. The test
split (dataset_test_hqa/) has no answers and is never read.

Nothing is changed on load: table cells, paragraph texts, questions and answers are kept verbatim.

Answer type for scoring: the raw file labels every hypothetical question `answer_type = "counterfactual"`, and
TAT's metric treats an unknown type by stringifying the answer (so a list answer such as ["2019", "2018"] can
never be matched). TAT-HQA's own evaluation files (dataset_extra_field/counter/, which the official
`evaluate.py` is run on) give each hypothetical question its answer format instead (arithmetic, span,
multi-span, count). We keep `answer_type = "counterfactual"` and add that format as `eval_answer_type`, read
by uid. Hypothetical questions whose answer or scale differs between the two files (3 in dev, 19 in train) are
not used, since their gold is ambiguous.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "domains" / "raw" / "tat-hqa" / "dataset_raw"
SPLIT_FILE = {"dev": "tatqa_and_hqa_dataset_dev.json", "train": "tatqa_and_hqa_dataset_train.json"}
EXTRA = ROOT / "data" / "domains" / "raw" / "tat-hqa" / "dataset_extra_field" / "counter"
EXTRA_FILE = {"dev": "tatqa_and_hqa_field_dev.json", "train": "tatqa_and_hqa_field_train.json"}
FACTUAL_TYPES = ("span", "multi-span", "count", "arithmetic")


@dataclass
class Context:
    uid: str                    # TAT table uid (identifies the context)
    split: str                  # dev | train
    index: int                  # position in the released file
    table: list[list[str]]      # rows of cells, as released
    paragraphs: list[dict]      # {"uid", "order", "text"}, sorted by order
    questions: list[dict]       # as released

    def question_by_order(self, order) -> dict | None:
        for q in self.questions:
            if str(q["order"]) == str(order):
                return q
        return None


def load(split: str) -> list[Context]:
    """Contexts as released; every hypothetical question gets `eval_answer_type` and `extra_agrees` (whether
    dataset_extra_field has the same answer and scale); factual questions get eval_answer_type = answer_type."""
    raw = json.loads((RAW / SPLIT_FILE[split]).read_text(encoding="utf-8"))
    extra = {q["uid"]: q for c in json.loads((EXTRA / EXTRA_FILE[split]).read_text(encoding="utf-8"))
             for q in c["questions"]}
    for c in raw:
        for q in c["questions"]:
            if q["answer_type"] == "counterfactual":
                x = extra[q["uid"]]
                q["eval_answer_type"] = x["answer_type"]
                q["extra_agrees"] = x["answer"] == q["answer"] and x["scale"] == q["scale"]
            else:
                q["eval_answer_type"] = q["answer_type"]
    return [Context(uid=c["table"]["uid"], split=split, index=i, table=c["table"]["table"],
                    paragraphs=sorted(c["paragraphs"], key=lambda p: int(p["order"])),
                    questions=c["questions"]) for i, c in enumerate(raw)]


def pairs(ctx: Context) -> list[tuple[dict, dict]]:
    """(counterfactual, factual twin) pairs of a context. A counterfactual is kept only if its gold agrees with
    dataset_extra_field, and its twin exists, is factual, and is the twin of no other counterfactual in the
    context (so every twin is used once)."""
    cfs = [q for q in ctx.questions if q["answer_type"] == "counterfactual"]
    twin_use: dict[str, int] = {}
    for q in cfs:
        twin_use[str(q["rel_question"])] = twin_use.get(str(q["rel_question"]), 0) + 1
    out = []
    for q in cfs:
        t = ctx.question_by_order(q["rel_question"])
        if (q["extra_agrees"] and t is not None and t["answer_type"] in FACTUAL_TYPES
                and twin_use[str(q["rel_question"])] == 1):
            out.append((q, t))
    return out
