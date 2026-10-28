"""Package the benchmark inputs for a collaborator: documents, questions (no gold, no question type), gold answers
(scoring only), Navigation Maps, and the shared answer contracts + scorer, for physics (CLEVRER), manufacturing, IT
operations and finance.

    python scripts/make_handoff_package.py            -> handoff/docqa_package/ and handoff/docqa_package.zip

Navigation Maps are rebuilt from the PDFs with the current otf/navmap.py (post-freeze fix 10 changes the manufacturing
and IT-operations maps). The package records the git commit it was built from (CODE_VERSION.txt) and checks that the
question rows of the three new domains equal the ones the harness already uses (runs/<run>/questions.jsonl).
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clevrer_bench.data import load_items  # noqa: E402
from clevrer_bench.prompts import (ANSWER_INSTRUCTIONS, FINANCE_ANSWER_INSTRUCTIONS,  # noqa: E402
                                   GENERIC_ANSWER_INSTRUCTIONS, answer_instructions, build_question_prompt)
from otf.navmap import build_map  # noqa: E402


def _runs(pattern):
    return sorted(p.name for p in (ROOT / "runs").glob(pattern))


OUT = ROOT / "handoff" / "docqa_package"
# (group folder, runs). Dev documents are for smoke tests and prompt checks only; the rest are test documents.
SETS = [("dev", ["pilot20", "mfg_dev", "itops_dev", "fin_dev"]),
        ("e1", _runs("e1_d[0-9]*")),
        ("e2", ["e2_d01"]),
        ("mfg", _runs("mfg_d[0-9]*")),
        ("itops", _runs("itops_d[0-9]*")),
        ("fin", _runs("fin_d[0-9]*"))]

DESIGN_NOTE = """> **Status note (2026-10-26).** This design was written on 2026-10-22 for local GPUs. Since then: all remaining runs
> use the hosted `or-*` models (OpenRouter), so the GPU-hour estimates, the Tier A/Tier B split and the vLLM remarks
> below no longer apply; three more domains (manufacturing, IT operations, finance) were added; the settings in
> `configs/models.json` (including the `or-*` aliases) are the ones to use. Everything about what each baseline is,
> the caps, the tuning budget and the no-domain-hints rule still holds.

"""


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def read_jsonl(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True).stdout.strip()


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
        domain = manifest.get("domain")                            # None = physics (CLEVRER)
        manifest.pop("pdf", None)                                  # local absolute path, not useful elsewhere
        (dst / "manifest.json").write_text(json.dumps(manifest, indent=2))
        (dst / "navmap.json").write_text(json.dumps(build_map(src / "document.pdf")))
        items = load_items(src / "items.jsonl")
        key = "video" if domain is None else "scope"
        q = [{"uid": it.uid, "document": run, key: it.scene_index, "question": it.question,
              "choices": it.choices, "format": "multiple_choice" if it.is_mc else "open_ended",
              "prompt": build_question_prompt(it.stripped(), domain)} for it in items]
        if domain is None:
            g = [{"uid": it.uid, "question_type": it.question_type, "question_subtype": it.question_subtype,
                  "gold_answer": it.gold_answer, "gold_choices": {str(k): v for k, v in it.gold_choices.items()}}
                 for it in items]
        else:                                                      # the harness's own gold rows (finance has more fields)
            g = read_jsonl(src / "gold.jsonl")
            assert [r["uid"] for r in g] == [r["uid"] for r in q], run
            assert q == read_jsonl(src / "questions.jsonl"), f"{run}: questions differ from the harness's"
        write_jsonl(dst / "questions.jsonl", q)
        write_jsonl(dst / "gold.jsonl", g)
        all_q += q
        all_g += g
    write_jsonl(OUT / group / "all_questions.jsonl", all_q)
    write_jsonl(OUT / group / "all_gold.jsonl", all_g)
    counts[group] = {"documents": len(runs), "questions": len(all_q)}

# answer contracts, one per domain (the harness picks them from the manifest's "domain": none = physics)
shared = OUT / "shared"
shared.mkdir()
assert answer_instructions(None) == ANSWER_INSTRUCTIONS and answer_instructions("manufacturing") == GENERIC_ANSWER_INSTRUCTIONS
assert answer_instructions("it_ops") == GENERIC_ANSWER_INSTRUCTIONS and answer_instructions("finance") == FINANCE_ANSWER_INSTRUCTIONS
(shared / "answer_instructions_physics.txt").write_text(ANSWER_INSTRUCTIONS, encoding="utf-8")
(shared / "answer_instructions_generic.txt").write_text(GENERIC_ANSWER_INSTRUCTIONS, encoding="utf-8")
(shared / "answer_instructions_finance.txt").write_text(FINANCE_ANSWER_INSTRUCTIONS, encoding="utf-8")

# the scorer and parser with the repository's own layout, so `sys.path.insert(0, "shared")` makes
# `from clevrer_bench.scoring import score` and `from otf.navmap import build_map` work
CODE = ("clevrer_bench/__init__.py", "clevrer_bench/data.py", "clevrer_bench/prompts.py", "clevrer_bench/scoring.py",
        "otf/navmap.py", "domains/finance/__init__.py", "domains/finance/score.py", "domains/finance/tatqa_metric.py")
for f in CODE:
    (shared / "code" / f).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / f, shared / "code" / f)
(shared / "new_baselines_design.md").write_text(
    DESIGN_NOTE + (ROOT / "docs" / "new_baselines_design.md").read_text(encoding="utf-8"), encoding="utf-8")
shutil.copy2(ROOT / "configs" / "models.json", shared / "models.json")
shutil.copy2(ROOT / "docs" / "handoff_README.md", OUT / "README.md")

# the version collaborators pull is origin/main; the packaged code files must be exactly its versions
head = git("rev-parse", "origin/main")
same = subprocess.run(["git", "-C", str(ROOT), "diff", "--quiet", "origin/main", "--", *CODE]).returncode == 0
(OUT / "CODE_VERSION.txt").write_text(
    f"repository: https://github.com/chirix33/otf-tools (branch main)\ncommit (origin/main when built): {head}\n"
    f"latest tag at that commit: {git('describe', '--tags', '--abbrev=0', 'origin/main')}\n"
    f"otf/navmap.py last changed in: {git('log', '-1', '--format=%h %s', 'origin/main', '--', 'otf/navmap.py')}\n"
    f"shared/code files identical to origin/main: {'yes' if same else 'NO - push before sharing'}\n")

sums = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(OUT).as_posix()}"
        for p in sorted(OUT.rglob("*")) if p.is_file() and p.name != "SHA256SUMS.txt"]
(OUT / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
zip_path = OUT.parent / "docqa_package.zip"
zip_path.unlink(missing_ok=True)
shutil.make_archive(str(OUT), "zip", OUT.parent, OUT.name)
print(json.dumps(counts))
print((OUT / "CODE_VERSION.txt").read_text())
