"""Build the benchmark document and run a system over all questions (resumable)."""
from __future__ import annotations

import json
import random
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .data import load_annotation, load_items, sample_videos, save_items, to_items
from .prompts import answer_instructions, build_question_prompt, parse_prediction
from .render import build_pdf, build_section, save_manifest
from .scoring import score
from .systems import Document, QASystem


def build(raw_dir: Path, run_dir: Path, n_videos: int, seed: int, stride: int,
          entries: list[dict] | None = None, desc_frac: float = 1.0, extra: dict | None = None) -> None:
    """One document + its questions. `entries` overrides sampling (split builds pass their own videos).
    desc_frac < 1 keeps a seeded random fraction of descriptive questions in items.jsonl (all questions
    stay in items_all.jsonl); the other types are always kept in full."""
    run_dir.mkdir(parents=True, exist_ok=True)
    entries = entries if entries is not None else sample_videos(raw_dir, n_videos, seed)
    sections = [build_section(load_annotation(raw_dir, e["scene_index"]), stride) for e in entries]
    doc = build_pdf(sections, run_dir / "document.pdf")
    save_manifest(doc, run_dir / "manifest.json")
    all_items = to_items(entries)
    items = all_items
    if desc_frac < 1.0:
        rng = random.Random(seed)
        items = [it for it in all_items if it.question_type != "descriptive" or rng.random() < desc_frac]
        save_items(all_items, run_dir / "items_all.jsonl")
    save_items(items, run_dir / "items.jsonl")
    (run_dir / "build_config.json").write_text(json.dumps(
        {"n_videos": len(entries), "seed": seed, "motion_stride": stride, "desc_frac": desc_frac,
         "n_questions": len(items), "n_questions_all": len(all_items), **(extra or {}),
         "videos": [e["scene_index"] for e in entries]}, indent=2))
    print(f"built {run_dir/'document.pdf'}: {len(sections)} videos, "
          f"{doc.sections[-1].end_page} pages, {len(items)} questions")


def build_split(raw_dir: Path, runs_root: Path, name: str, n_videos: int, per_doc: int, seed: int,
                stride: int, exclude_runs: list[str], desc_frac: float) -> None:
    """Sample `n_videos` test videos (excluding every video of `exclude_runs`, e.g. the dev set) and
    split them, in sampled order, into documents of `per_doc` videos: runs/<name>_d01, _d02, ..."""
    excluded = set()
    for r in exclude_runs:
        excluded |= set(json.loads((runs_root / r / "build_config.json").read_text())["videos"])
    pool = [e for e in json.loads((raw_dir / "validation.json").read_text()) if e["scene_index"] not in excluded]
    picked = random.Random(seed).sample(pool, n_videos)
    for k in range(0, n_videos, per_doc):
        chunk = sorted(picked[k:k + per_doc], key=lambda e: e["scene_index"])
        doc_no = k // per_doc + 1
        build(raw_dir, runs_root / f"{name}_d{doc_no:02d}", len(chunk), seed * 1000 + doc_no, stride,
              entries=chunk, desc_frac=desc_frac,
              extra={"split": name, "doc": doc_no, "split_seed": seed, "excluded_runs": exclude_runs})


def run_system(system: QASystem, run_dir: Path, workers: int, limit: int | None = None,
               types: list[str] | None = None, per_type: int | None = None, shard: str | None = None) -> Path:
    items = load_items(run_dir / "items.jsonl")
    if types:
        items = [it for it in items if it.question_type in types]
    if per_type:   # smoke tests: the first N questions of each type
        items = [it for t in sorted({it.question_type for it in items})
                 for it in [x for x in items if x.question_type == t][:per_type]]
    if limit:
        items = items[:limit]
    if shard:      # "k/n": every n-th question from the k-th, so n processes can share one document
        k, n = (int(x) for x in shard.split("/"))
        items = [it for i, it in enumerate(items) if i % n == k]
    # one directory per (system, model); pilot runs used the bare system name for gpt-5.5
    out_dir = run_dir / "systems" / (system.name if system.model == "gpt-5.5" else f"{system.name}__{system.model}")
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((run_dir / "manifest.json").read_text())
    # the run's domain picks the answer contract, the prompt's first line and the scorer (None = CLEVRER)
    domain = manifest.get("domain")
    instructions = answer_instructions(domain)
    gold = ({(g := json.loads(l))["uid"]: g for l in (run_dir / "gold.jsonl").read_text().splitlines()}
            if domain == "finance" else {})
    doc = Document(run_dir / "document.pdf", manifest, work)
    setup = system.setup(doc)
    (out_dir / "setup.json").write_text(json.dumps(
        {"system": system.name, "model": system.model, "reasoning_effort": system.reasoning_effort,
         "model_spec": system.spec.to_dict(),
         "usage": setup.usage.to_dict(), "latency_s": setup.latency_s, "info": setup.info}, indent=2))
    print(f"[{system.name}] setup: {setup.usage.total_tokens} tokens, {setup.latency_s:.1f}s {setup.info}")

    pred_path = out_dir / "predictions.jsonl"
    done = set()
    if pred_path.exists():
        for line in pred_path.read_text().splitlines():
            r = json.loads(line)
            if "error" not in r:
                done.add(r["uid"])
        # drop stale error rows; they will be retried
        kept = [l for l in pred_path.read_text().splitlines() if "error" not in json.loads(l)]
        pred_path.write_text("".join(l + "\n" for l in kept))
    todo = [it for it in items if it.uid not in done]
    print(f"[{system.name}] {len(done)} already answered, {len(todo)} to go")

    lock = threading.Lock()

    def one(item):
        prompt = build_question_prompt(item, domain)
        rec = {"uid": item.uid, "question_type": item.question_type, "question_subtype": item.question_subtype}
        try:
            pred = system.answer(item.stripped(), instructions, prompt)
            parsed = parse_prediction(item, pred.raw_text, domain)
            rec.update(raw_text=pred.raw_text, parsed={**parsed, **({"choices": {str(k): v for k, v in
                       parsed["choices"].items()}} if "choices" in parsed else {})},
                       score=score(item, parsed, domain, gold.get(item.uid)), usage=pred.usage.to_dict(),
                       latency_s=round(pred.latency_s, 2), trace=pred.trace)
        except Exception as e:  # recorded and retried on the next invocation
            rec["error"] = f"{type(e).__name__}: {e}"
            rec["traceback"] = traceback.format_exc()
        with lock, pred_path.open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        return rec

    t0, n_ok, n_err = time.time(), 0, 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, it) for it in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            n_err += "error" in r
            n_ok += bool(r.get("score", {}).get("question_correct"))
            if i % 10 == 0 or i == len(todo):
                print(f"[{system.name}] {i}/{len(todo)}  correct={n_ok}  errors={n_err}  {time.time()-t0:.0f}s",
                      flush=True)
            if "error" in r and n_err <= 3:
                print(f"[{system.name}] error on {r['uid']}: {r['error']}", flush=True)
    return out_dir
