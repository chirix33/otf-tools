"""Import pilot20 and the E1-core documents from the collaborator package into runs/<doc>/.

Each document gets document.pdf, manifest.json, navmap.json (copied byte for byte after checksum verification) and
items.jsonl (questions.jsonl + gold.jsonl merged into the harness's QAItem rows). Existing run inputs are never
overwritten: an identical file is accepted, a different one stops the import.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from clevrer_bench.data import QAItem
from clevrer_bench.prompts import build_question_prompt

DEV_DOCS = {"pilot20": "dev/pilot20"}
E1_CORE = ["e1_d03", "e1_d06", "e1_d09", "e1_d12", "e1_d15"]
EXPECTED = {"pilot20": 308, "e1_core": 694}
COPIED = ("document.pdf", "manifest.json", "navmap.json")


class ImportErrorTierB(RuntimeError):
    pass


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def package_sums(pkg: Path) -> dict[str, str]:
    sums = {}
    for line in (pkg / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, rel = line.split(maxsplit=1)
            sums[rel.strip()] = digest
    return sums


def doc_sources(pkg: Path) -> dict[str, Path]:
    return {**{k: pkg / v for k, v in DEV_DOCS.items()}, **{d: pkg / "e1" / d for d in E1_CORE}}


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def to_items(questions: list[dict], gold: list[dict]) -> list[QAItem]:
    """Merge questions and gold by uid. The prompt each system receives must be byte-identical to the package's."""
    g = {r["uid"]: r for r in gold}
    if len(g) != len(gold) or set(g) != {q["uid"] for q in questions} or len(questions) != len(g):
        raise ImportErrorTierB("questions.jsonl and gold.jsonl do not hold the same unique uids")
    items = []
    for q in questions:
        r = g[q["uid"]]
        it = QAItem(uid=q["uid"], scene_index=int(q["video"]), question_id=int(q["uid"].rsplit("-", 1)[1]),
                    question_type=r["question_type"], question_subtype=r.get("question_subtype"),
                    question=q["question"], choices=[{"choice_id": c["choice_id"], "choice": c["choice"]}
                                                     for c in q["choices"]],
                    gold_answer=r.get("gold_answer"),
                    gold_choices={int(k): bool(v) for k, v in (r.get("gold_choices") or {}).items()})
        if it.is_mc != (q["format"] == "multiple_choice"):
            raise ImportErrorTierB(f"{it.uid}: format {q['format']} disagrees with type {it.question_type}")
        if build_question_prompt(it.stripped()) != q["prompt"]:
            raise ImportErrorTierB(f"{it.uid}: rebuilt prompt differs from the package prompt")
        items.append(it)
    return items


def _item_line(it: QAItem) -> str:
    d = dict(it.__dict__)
    d["gold_choices"] = {str(k): v for k, v in it.gold_choices.items()}
    return json.dumps(d) + "\n"


def _place(dst: Path, data: bytes) -> None:
    """Write `data` to `dst` unless an identical file is there; refuse to overwrite a different one."""
    if dst.exists():
        if dst.read_bytes() != data:
            raise ImportErrorTierB(f"refusing to overwrite {dst}: it differs from the package version")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(dst)


def import_all(pkg: Path, runs: Path) -> dict:
    """Verify, copy and convert every Tier B document. Returns per-document counts and checksums."""
    if not (pkg / "SHA256SUMS.txt").exists():
        raise ImportErrorTierB(f"no SHA256SUMS.txt in {pkg}; pass --package <clevrer_docqa_package folder>")
    sums = package_sums(pkg)
    out = {}
    for doc, src in doc_sources(pkg).items():
        rel_dir = src.relative_to(pkg).as_posix()
        for name in COPIED + ("questions.jsonl", "gold.jsonl"):
            rel = f"{rel_dir}/{name}"
            if rel not in sums:
                raise ImportErrorTierB(f"{rel} has no checksum in SHA256SUMS.txt")
            if not (src / name).exists():
                raise ImportErrorTierB(f"missing package file {src / name}")
            if sha256(src / name) != sums[rel]:
                raise ImportErrorTierB(f"checksum mismatch for {rel}")
        items = to_items(_jsonl(src / "questions.jsonl"), _jsonl(src / "gold.jsonl"))
        dst = runs / doc
        for name in COPIED:
            _place(dst / name, (src / name).read_bytes())
        _place(dst / "items.jsonl", "".join(_item_line(it) for it in items).encode("utf-8"))
        manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
        build = {"n_videos": len(manifest["videos"]), "seed": None, "motion_stride": 8, "n_questions": len(items),
                 "source": f"clevrer_docqa_package/{rel_dir}", "videos": [v["scene_index"] for v in manifest["videos"]]}
        _place(dst / "build_config.json", (json.dumps(build, indent=2) + "\n").encode("utf-8"))
        out[doc] = {"questions": len(items), "pdf_sha256": sums[f"{rel_dir}/document.pdf"]}
    n_e1 = sum(out[d]["questions"] for d in E1_CORE)
    if out["pilot20"]["questions"] != EXPECTED["pilot20"] or n_e1 != EXPECTED["e1_core"]:
        raise ImportErrorTierB(f"unexpected counts: pilot20={out['pilot20']['questions']}, E1-core={n_e1}")
    return out
