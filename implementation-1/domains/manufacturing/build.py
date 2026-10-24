"""Build the manufacturing benchmark: runs/mfg_dev and runs/mfg_d01..mfg_d05.

    python -m domains.manufacturing.build            (from implementation-1/)

Split: period 01 (4 scopes) is the dev document; periods 02-15 (56 scopes) are shuffled with a fixed seed and
dealt into 5 test documents (12, 11, 11, 11, 11 scopes). Questions per document: 15 per type (dev: 10).
Each run folder gets the harness layout (document.pdf, items.jsonl, items_all.jsonl, manifest.json,
build_config.json) plus the hand-off split (questions.jsonl without type/gold, gold.jsonl).
"""
from __future__ import annotations

import itertools
import json
import random
from pathlib import Path

from .data import ROOT, load
from .questions import (CF_KINDS, DESC_TEMPLATES, PRED_TEMPLATES, Question, counterfactual, descriptive,
                        explanatory, predictive, reset_balance)
from .render import build_pdf, save_manifest
from .scopes import PERIOD_DAYS, all_scopes, capacity, opening_stock
from .sim import simulate

SEED = 2027
N_TEST_DOCS = 5
PER_TYPE_TEST = 15
PER_TYPE_DEV = 10
TYPES = ("descriptive", "explanatory", "predictive", "counterfactual")
RUNS = ROOT / "runs"


def split(scopes):
    dev = [s for s in scopes if s.period == 1]
    test = [s for s in scopes if s.period > 1]
    random.Random(SEED).shuffle(test)
    docs = [sorted(test[i::N_TEST_DOCS], key=lambda s: (s.period, s.plant)) for i in range(N_TEST_DOCS)]
    return dev, docs


def generate(runs, per_type: int, cycles: dict, rng: random.Random) -> list[Question]:
    """per_type questions of each type, spread round-robin over the document's scopes."""
    out: list[Question] = []
    seen = set()
    for qtype in TYPES:
        order = list(range(len(runs)))
        rng.shuffle(order)
        pos = 0
        for _ in range(per_type):
            template = next(cycles[qtype]) if qtype in cycles else None
            q = None
            for attempt in range(len(runs) * 2):
                s, f = runs[order[(pos + attempt) % len(runs)]]
                if qtype == "descriptive":
                    q = descriptive(s, f, template, rng)
                elif qtype == "explanatory":
                    q = explanatory(s, f, rng)
                elif qtype == "predictive":
                    q = predictive(s, f, template, rng)
                else:
                    q = counterfactual(s, f, template, rng)
                if q is not None and q.question + "|".join(q.choices) not in seen:
                    pos += attempt + 1
                    break
                q = None
            if q is None:
                raise RuntimeError(f"could not generate {qtype}/{template}")
            seen.add(q.question + "|".join(q.choices))
            out.append(q)
    return out


def prompt_of(q: Question) -> str:
    """Same shape as the CLEVRER prompt, with the scope title in place of 'Video <n>'."""
    lines = [q.scope, f"Question: {q.question}"]
    if q.qtype != "descriptive":
        lines.append("Choices:")
        lines += [f"  {i}: {c}" for i, c in enumerate(q.choices)]
        lines.append("Answer with the multiple-choice JSON format.")
    else:
        lines.append("Answer with the open-ended JSON format.")
    return "\n".join(lines)


def write_run(name: str, rec, caps, runs, qs: list[Question], extra: dict) -> None:
    run_dir = RUNS / name
    run_dir.mkdir(parents=True, exist_ok=True)
    doc = build_pdf(rec, caps, runs, run_dir / "document.pdf", name)
    save_manifest(doc, run_dir / "manifest.json")
    titles = [s.title for s, _ in runs]
    qs = sorted(qs, key=lambda q: (titles.index(q.scope), TYPES.index(q.qtype)))
    counters: dict[str, int] = {}
    items, questions, gold, meta = [], [], [], []
    for q in qs:
        s = runs[titles.index(q.scope)][0]
        counters[q.scope] = counters.get(q.scope, 0) + 1
        qid = counters[q.scope]
        uid = f"mfg-{s.plant}-{s.period:02d}-{qid:02d}"
        choices = [{"choice_id": i, "choice": c} for i, c in enumerate(q.choices)]
        gc = {str(i): g for i, g in enumerate(q.gold_choices)}
        # QAItem fields (clevrer_bench.data.load_items can read this file); scene_index holds the scope title
        items.append({"uid": uid, "scene_index": q.scope, "question_id": qid, "question_type": q.qtype,
                      "question_subtype": q.subtype, "question": q.question, "choices": choices,
                      "gold_answer": q.gold_answer, "gold_choices": gc})
        questions.append({"uid": uid, "document": name, "scope": q.scope, "question": q.question,
                          "choices": choices, "format": "open_ended" if q.qtype == "descriptive"
                          else "multiple_choice", "prompt": prompt_of(q)})
        gold.append({"uid": uid, "question_type": q.qtype, "question_subtype": q.subtype,
                     "gold_answer": q.gold_answer, "gold_choices": gc})
        meta.append({"uid": uid, **q.meta})
    for fname, rows in (("items.jsonl", items), ("items_all.jsonl", items), ("questions.jsonl", questions),
                        ("gold.jsonl", gold), ("gold_meta.jsonl", meta)):
        (run_dir / fname).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    per_type = {t: sum(q.qtype == t for q in qs) for t in TYPES}
    (run_dir / "build_config.json").write_text(json.dumps(
        {"domain": "manufacturing", "n_scopes": len(runs), "seed": SEED, "period_days": PERIOD_DAYS,
         "n_questions": len(qs), "n_questions_all": len(qs), "per_type": per_type, **extra,
         "capacity_kg": caps, "scopes": titles}, indent=2))
    print(f"built {run_dir / 'document.pdf'}: {len(runs)} scopes, {doc.sections[-1].end_page} pages, "
          f"{len(qs)} questions {per_type}")


def main() -> None:
    reset_balance()
    rec = load()
    caps = capacity(rec)
    scopes = all_scopes(rec)
    dev, docs = split(scopes)
    rng = random.Random(SEED)
    # template / intervention-kind cycles run across the test documents, so totals stay balanced
    cycles = {"descriptive": itertools.cycle(DESC_TEMPLATES), "predictive": itertools.cycle(PRED_TEMPLATES),
              "counterfactual": itertools.cycle(CF_KINDS)}
    for i, doc_scopes in enumerate(docs, 1):
        runs = [(s, simulate(s)) for s in doc_scopes]
        qs = generate(runs, PER_TYPE_TEST, cycles, rng)
        write_run(f"mfg_d{i:02d}", rec, caps, runs, qs, {"split": "mfg", "doc": i, "role": "test"})
    dev_cycles = {"descriptive": itertools.cycle(DESC_TEMPLATES), "predictive": itertools.cycle(PRED_TEMPLATES),
                  "counterfactual": itertools.cycle(CF_KINDS)}
    runs = [(s, simulate(s)) for s in dev]
    qs = generate(runs, PER_TYPE_DEV, dev_cycles, random.Random(SEED + 1))
    write_run("mfg_dev", rec, caps, runs, qs, {"split": "mfg", "doc": 0, "role": "dev (pipeline smoke tests only)"})
    (RUNS / "mfg_dev" / "opening_stock.json").write_text(json.dumps(opening_stock(rec), indent=2))


if __name__ == "__main__":
    main()
