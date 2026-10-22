"""Package the benchmark inputs for a collaborator: documents, questions (no gold, no question type), gold answers
(scoring only), Navigation Maps, and the shared answer contract + scorer.

    python scripts/make_handoff_package.py            -> handoff/clevrer_docqa_package/ and handoff/clevrer_docqa_package.zip
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clevrer_bench.data import load_items  # noqa: E402
from clevrer_bench.prompts import ANSWER_INSTRUCTIONS, build_question_prompt  # noqa: E402
from otf.navmap import build_map  # noqa: E402

OUT = ROOT / "handoff" / "clevrer_docqa_package"
SETS = [("dev", ["pilot20"]),
        ("e1", sorted(p.name for p in (ROOT / "runs").glob("e1_d[0-9]*"))),
        ("e2", ["e2_d01"])]


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


if OUT.exists():
    shutil.rmtree(OUT)
counts = {}
for group, runs in SETS:
    all_q, all_g = [], []
    for run in runs:
        src, dst = ROOT / "runs" / run, OUT / group / run
        dst.mkdir(parents=True)
        shutil.copy2(src / "document.pdf", dst / "document.pdf")
        manifest = json.loads((src / "manifest.json").read_text())
        manifest.pop("pdf", None)                                  # local absolute path, not useful elsewhere
        (dst / "manifest.json").write_text(json.dumps(manifest, indent=2))
        (dst / "navmap.json").write_text(json.dumps(build_map(src / "document.pdf")))
        items = load_items(src / "items.jsonl")
        q = [{"uid": it.uid, "document": run, "video": it.scene_index, "question": it.question,
              "choices": it.choices, "format": "multiple_choice" if it.is_mc else "open_ended",
              "prompt": build_question_prompt(it.stripped())} for it in items]
        g = [{"uid": it.uid, "question_type": it.question_type, "question_subtype": it.question_subtype,
              "gold_answer": it.gold_answer, "gold_choices": {str(k): v for k, v in it.gold_choices.items()}}
             for it in items]
        write_jsonl(dst / "questions.jsonl", q)
        write_jsonl(dst / "gold.jsonl", g)
        all_q += q
        all_g += g
    write_jsonl(OUT / group / "all_questions.jsonl", all_q)
    write_jsonl(OUT / group / "all_gold.jsonl", all_g)
    counts[group] = {"documents": len(runs), "questions": len(all_q)}

shared = OUT / "shared"
shared.mkdir()
(shared / "answer_instructions.txt").write_text(ANSWER_INSTRUCTIONS, encoding="utf-8")
for f in ("clevrer_bench/prompts.py", "clevrer_bench/scoring.py", "clevrer_bench/data.py", "otf/navmap.py"):
    shutil.copy2(ROOT / f, shared / Path(f).name)
shutil.copy2(ROOT / "docs" / "new_baselines_design.md", shared / "new_baselines_design.md")
shutil.copy2(ROOT / "docs" / "handoff_README.md", OUT / "README.md")

sums = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(OUT).as_posix()}"
        for p in sorted(OUT.rglob("*")) if p.is_file() and p.name != "SHA256SUMS.txt"]
(OUT / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
print(json.dumps(counts))
