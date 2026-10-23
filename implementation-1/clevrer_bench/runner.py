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
from .prompts import ANSWER_INSTRUCTIONS, build_question_prompt, parse_prediction
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


class CorruptPredictions(RuntimeError):
    pass


def load_predictions(pred_path: Path) -> list[dict]:
    """Rows of predictions.jsonl. A torn *final* line (a crash mid-write) is moved to torn_lines.jsonl and cut
    from the file; an unparseable line anywhere else is corruption and stops the run instead of being dropped."""
    if not pred_path.exists():
        return []
    raw = pred_path.read_bytes()
    lines = raw.split(b"\n")
    rows, good_end = [], 0
    for i, line in enumerate(lines):
        if not line.strip():
            good_end += len(line) + 1
            continue
        try:
            rows.append(json.loads(line))
            good_end += len(line) + 1
        except ValueError:
            if any(l.strip() for l in lines[i + 1:]):
                raise CorruptPredictions(f"{pred_path}: unparseable line {i + 1} is not the last line; "
                                         "inspect the file (nothing was discarded)")
            with (pred_path.parent / "torn_lines.jsonl").open("ab") as f:
                f.write(json.dumps({"t": time.time(), "line": line.decode("utf-8", "replace")}).encode() + b"\n")
            with pred_path.open("r+b") as f:
                f.truncate(min(good_end, len(raw)))
            break
    return rows


def run_system(system: QASystem, run_dir: Path, workers: int, limit: int | None = None,
               types: list[str] | None = None, per_type: int | None = None, max_attempts: int | None = None,
               should_stop=None, max_consecutive_errors: int | None = None) -> Path:
    """Answer every question of `run_dir` with `system`, resuming by uid.
    max_attempts: give up (leave unanswered, listed by the caller) on a question after this many errored
    attempts; errored attempts are kept in attempts.jsonl. should_stop(): checked before each question starts
    (deadline / interrupt). max_consecutive_errors: end the pass early when the server looks down."""
    items = load_items(run_dir / "items.jsonl")
    if types:
        items = [it for it in items if it.question_type in types]
    if per_type:   # smoke tests: the first N questions of each type
        items = [it for t in sorted({it.question_type for it in items})
                 for it in [x for x in items if x.question_type == t][:per_type]]
    if limit:
        items = items[:limit]
    # one directory per (system, model); pilot runs used the bare system name for gpt-5.5
    out_dir = run_dir / "systems" / (system.name if system.model == "gpt-5.5" else f"{system.name}__{system.model}")
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)

    doc = Document(run_dir / "document.pdf", json.loads((run_dir / "manifest.json").read_text()), work)
    pred_path = out_dir / "predictions.jsonl"
    rows = load_predictions(pred_path)          # before setup: corruption stops the run before any cost
    setup = system.setup(doc)
    setup_rec = {"system": system.name, "model": system.model, "reasoning_effort": system.reasoning_effort,
                 "model_spec": system.spec.to_dict(),
                 "usage": setup.usage.to_dict(), "latency_s": setup.latency_s, "info": setup.info}
    if hasattr(system, "provenance"):
        setup_rec["provenance"] = system.provenance()
    (out_dir / "setup.json").write_text(json.dumps(setup_rec, indent=2, default=str))
    print(f"[{system.name}] setup: {setup.usage.total_tokens} tokens, {setup.latency_s:.1f}s {setup.info}")

    done, kept, moved = set(), [], []
    for r in rows:
        if "error" in r or r["uid"] in done:   # errored attempts (and any duplicate) go to the attempt history
            moved.append(r)
        else:
            done.add(r["uid"])
            kept.append(r)
    attempts_path = out_dir / "attempts.jsonl"
    if moved:   # history first, then the rewrite: a crash in between can only duplicate history, never lose it
        with attempts_path.open("a") as f:
            f.write("".join(json.dumps(r, default=str) + "\n" for r in moved))
        tmp = pred_path.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(json.dumps(r, default=str) + "\n" for r in kept))
        tmp.replace(pred_path)
    tries: dict[str, int] = {}
    if max_attempts and attempts_path.exists():
        for line in attempts_path.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if "error" in r:
                tries[r["uid"]] = tries.get(r["uid"], 0) + 1
    todo = [it for it in items if it.uid not in done and (not max_attempts or tries.get(it.uid, 0) < max_attempts)]
    print(f"[{system.name}] {len(done)} already answered, {len(todo)} to go")

    lock = threading.Lock()
    stop = threading.Event()

    def one(item):
        if stop.is_set() or (should_stop and should_stop()):
            stop.set()
            return {"uid": item.uid, "skipped": True}
        prompt = build_question_prompt(item)
        rec = {"uid": item.uid, "question_type": item.question_type, "question_subtype": item.question_subtype}
        try:
            pred = system.answer(item.stripped(), ANSWER_INSTRUCTIONS, prompt)
            parsed = parse_prediction(item, pred.raw_text)
            rec.update(raw_text=pred.raw_text, parsed={**parsed, **({"choices": {str(k): v for k, v in
                       parsed["choices"].items()}} if "choices" in parsed else {})},
                       score=score(item, parsed), usage=pred.usage.to_dict(),
                       latency_s=round(pred.latency_s, 2), trace=pred.trace)
        except Exception as e:  # recorded and retried on the next invocation
            rec["error"] = f"{type(e).__name__}: {e}"
            rec["traceback"] = traceback.format_exc()
        with lock, pred_path.open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        return rec

    t0, n_ok, n_err, streak = time.time(), 0, 0, 0
    ex = ThreadPoolExecutor(max_workers=workers)
    try:
        futs = [ex.submit(one, it) for it in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            if r.get("skipped"):
                continue
            n_err += "error" in r
            streak = streak + 1 if "error" in r else 0
            n_ok += bool(r.get("score", {}).get("question_correct"))
            if i % 10 == 0 or i == len(todo):
                print(f"[{system.name}] {i}/{len(todo)}  correct={n_ok}  errors={n_err}  {time.time()-t0:.0f}s",
                      flush=True)
            if "error" in r and n_err <= 3:
                print(f"[{system.name}] error on {r['uid']}: {r['error']}", flush=True)
            if max_consecutive_errors and streak >= max_consecutive_errors and not stop.is_set():
                print(f"[{system.name}] {streak} errors in a row: ending this pass", flush=True)
                stop.set()
    except BaseException:          # Ctrl+C: stop admitting work; in-flight answers still land in the file
        stop.set()
        ex.shutdown(wait=False, cancel_futures=True)
        raise
    ex.shutdown(wait=True)
    answered = {r["uid"] for r in load_predictions(pred_path) if "error" not in r}
    setup_rec["completion"] = {"expected": len(items), "answered": len(answered & {it.uid for it in items}),
                               "complete": {it.uid for it in items} <= answered}
    (out_dir / "setup.json").write_text(json.dumps(setup_rec, indent=2, default=str))
    return out_dir
