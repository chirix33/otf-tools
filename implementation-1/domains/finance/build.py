"""Build the finance benchmark: runs/fin_d01..fin_d03 (test) and runs/fin_dev.

    python -m domains.finance.build            (from implementation-1/)

Split: the 274 TAT-HQA dev contexts are shuffled with a fixed seed and dealt into 3 test documents (92, 91, 91
contexts), each kept in released-file order and numbered Report R-001 ... R-274 across the three documents.
Per test document, 50 contexts are drawn at random and one (counterfactual, factual twin) pair is taken from
each: 100 questions per document, 300 in all (150 descriptive, 150 counterfactual), at most one pair per context.
The dev document (smoke tests only) is 30 TAT-HQA train contexts (Report R-901 ... R-930) with 20 pairs.
Each run folder gets the harness layout (document.pdf, items.jsonl, items_all.jsonl, manifest.json,
build_config.json) plus the hand-off split (questions.jsonl without type/gold, gold.jsonl).
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from .data import ROOT, Context, load
from .questions import Question, gold_answer_str, select
from .render import build_pdf, save_manifest

SEED = 2027
N_TEST_DOCS = 3
PAIRS_PER_TEST_DOC = 50
DEV_CONTEXTS, DEV_PAIRS, DEV_FIRST_REPORT = 30, 20, 901
TYPES = ("descriptive", "counterfactual")
RUNS = ROOT / "runs"


def title_of(n: int) -> str:
    return f"Report R-{n:03d}"


def split(contexts: list[Context]) -> list[list[tuple[str, Context]]]:
    order = list(contexts)
    random.Random(SEED).shuffle(order)
    docs = [sorted(order[i::N_TEST_DOCS], key=lambda c: c.index) for i in range(N_TEST_DOCS)]
    out, n = [], 0
    for doc in docs:
        scoped = []
        for c in doc:
            n += 1
            scoped.append((title_of(n), c))
        out.append(scoped)
    return out


def prompt_of(q: Question) -> str:
    """Same shape as the CLEVRER open-ended prompt, with the scope title in place of 'Video <n>'."""
    return "\n".join([q.scope, f"Question: {q.question}", "Answer with the open-ended JSON format."])


def write_run(name: str, scoped: list[tuple[str, Context]], qs: list[Question], extra: dict) -> None:
    run_dir = RUNS / name
    run_dir.mkdir(parents=True, exist_ok=True)
    doc = build_pdf(scoped, run_dir / "document.pdf", name)
    save_manifest(doc, run_dir / "manifest.json")
    titles = [t for t, _ in scoped]
    qs = sorted(qs, key=lambda q: (titles.index(q.scope), q.question_id))
    items, questions, gold = [], [], []
    for q in qs:
        uid = f"fin-{q.scope.split('-')[-1]}-{q.question_id:02d}"
        twin_uid = f"fin-{q.scope.split('-')[-1]}-{3 - q.question_id:02d}"
        t = q.tat
        # QAItem fields (clevrer_bench.data.load_items can read this file); scene_index holds the scope title
        items.append({"uid": uid, "scene_index": q.scope, "question_id": q.question_id, "question_type": q.qtype,
                      "question_subtype": t["answer_type"], "question": q.question, "choices": [],
                      "gold_answer": gold_answer_str(t["answer"]), "gold_choices": {}})
        questions.append({"uid": uid, "document": name, "scope": q.scope, "question": q.question,
                          "choices": [], "format": "open_ended", "prompt": prompt_of(q)})
        gold.append({"uid": uid, "question_type": q.qtype, "question_subtype": t["answer_type"],
                     "answer": t["answer"], "scale": t["scale"], "derivation": t["derivation"],
                     "answer_type": t["answer_type"], "eval_answer_type": t["eval_answer_type"],
                     "answer_from": t["answer_from"],
                     "rel_paragraphs": t["rel_paragraphs"], "req_comparison": t["req_comparison"],
                     "pair_uid": twin_uid, "tat_uid": t["uid"], "tat_pair_uid": q.twin_tat_uid,
                     "tat_context_uid": q.tat_context_uid, "tat_question": t["question"],
                     "gold_answer": gold_answer_str(t["answer"]), "gold_choices": {}})
    for fname, rows in (("items.jsonl", items), ("items_all.jsonl", items), ("questions.jsonl", questions),
                        ("gold.jsonl", gold)):
        (run_dir / fname).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    per_type = {t: sum(q.qtype == t for q in qs) for t in TYPES}
    (run_dir / "build_config.json").write_text(json.dumps(
        {"domain": "finance", "source": "TAT-HQA", "n_scopes": len(scoped), "seed": SEED,
         "n_questions": len(qs), "n_questions_all": len(qs), "per_type": per_type, **extra,
         "scopes": titles}, indent=2))
    print(f"built {run_dir / 'document.pdf'}: {len(scoped)} scopes, {doc.sections[-1].end_page} pages, "
          f"{len(qs)} questions {per_type}")


def main() -> None:
    rng = random.Random(SEED)
    for i, scoped in enumerate(split(load("dev")), 1):
        qs = select(scoped, PAIRS_PER_TEST_DOC, rng)
        write_run(f"fin_d{i:02d}", scoped, qs, {"split": "fin", "doc": i, "role": "test", "tat_split": "dev"})
    train = load("train")
    dev_rng = random.Random(SEED + 1)
    picked = sorted(dev_rng.sample(train, DEV_CONTEXTS), key=lambda c: c.index)
    scoped = [(title_of(DEV_FIRST_REPORT + k), c) for k, c in enumerate(picked)]
    qs = select(scoped, DEV_PAIRS, dev_rng)
    write_run("fin_dev", scoped, qs, {"split": "fin", "doc": 0, "role": "dev (pipeline smoke tests only)",
                                      "tat_split": "train"})


if __name__ == "__main__":
    main()
