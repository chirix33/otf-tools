"""Aggregate predictions of every system in a run into report.json + report.md."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .data import QUESTION_TYPES, load_items

TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens")


BOOT_SAMPLES, BOOT_SEED = 2000, 0


def _pct(a, b):
    return round(100 * a / b, 2) if b else None


def _boot_ci(correct: list[bool]) -> list[float] | None:
    """95% percentile-bootstrap CI (percent) of the mean of 0/1 outcomes."""
    import numpy as np
    if not correct:
        return None
    x = np.asarray(correct, dtype=float)
    idx = np.random.default_rng(BOOT_SEED).integers(0, len(x), size=(BOOT_SAMPLES, len(x)))
    m = x[idx].mean(axis=1)
    return [round(100 * float(np.percentile(m, 2.5)), 2), round(100 * float(np.percentile(m, 97.5)), 2)]


def paired_diff(a: dict, b: dict, uids: list[str]) -> dict | None:
    """Accuracy of A minus B on the questions both answered, with a 95% paired-bootstrap CI (points) and the
    share of resamples in which the difference is <= 0 (one-sided bootstrap p for 'A better than B')."""
    import numpy as np
    common = [u for u in uids if u in a and u in b]
    if not common:
        return None
    d = np.asarray([float(a[u]) - float(b[u]) for u in common])
    idx = np.random.default_rng(BOOT_SEED).integers(0, len(d), size=(BOOT_SAMPLES, len(d)))
    m = d[idx].mean(axis=1)
    return {"n": len(common), "diff": round(100 * float(d.mean()), 2),
            "ci95": [round(100 * float(np.percentile(m, 2.5)), 2), round(100 * float(np.percentile(m, 97.5)), 2)],
            "p_le_0": round(float((m <= 0).mean()), 4)}


def _agg(rows: list[dict]) -> dict:
    n = len(rows)
    ok = sum(r["score"]["question_correct"] for r in rows)
    oc = sum(r["score"]["options_correct"] for r in rows)
    ot = sum(r["score"]["options_total"] for r in rows)
    tok = {f: sum(r["usage"][f] for r in rows) for f in TOKEN_FIELDS}
    calls = sum(r["usage"]["llm_calls"] for r in rows)
    tool_calls = [len((r.get("trace") or {}).get("tool_calls", [])) for r in rows if r.get("trace")]
    return {
        "n": n,
        "question_accuracy": _pct(ok, n),
        "question_accuracy_ci95": _boot_ci([bool(r["score"]["question_correct"]) for r in rows]),
        "option_accuracy": _pct(oc, ot),
        "parse_errors": sum("parse_error" in r["parsed"] for r in rows),
        "truncated": sum((r.get("trace") or {}).get("finish_reason") == "length" for r in rows),
        "tokens_sum": tok,
        "tokens_mean": {f: round(v / n, 1) if n else None for f, v in tok.items()},
        "llm_calls_mean": round(calls / n, 2) if n else None,
        "tool_calls_mean": round(sum(tool_calls) / len(tool_calls), 2) if tool_calls else None,
        "latency_mean_s": round(sum(r["latency_s"] for r in rows) / n, 2) if n else None,
    }


def system_report(sys_dir: Path | list[Path], uids: set[str]) -> dict:
    """One system over one document, or over several (a split): predictions are pooled and the
    one-time setup cost is summed over the documents."""
    sys_dirs = sys_dir if isinstance(sys_dir, list) else [sys_dir]
    setups = [json.loads((d / "setup.json").read_text()) for d in sys_dirs]
    setup = dict(setups[0])
    if len(setups) > 1:
        setup["usage"] = {f: sum(s["usage"][f] for s in setups) for f in setups[0]["usage"]}
        setup["latency_s"] = sum(s["latency_s"] for s in setups)
        setup["info"] = {"documents": len(setups)}
    rows = {}
    for d in sys_dirs:
        for line in (d / "predictions.jsonl").read_text().splitlines():
            r = json.loads(line)
            if r["uid"] in uids:
                rows[r["uid"]] = r          # last write wins
    ok_rows = [r for r in rows.values() if "error" not in r]
    errors = [r for r in rows.values() if "error" in r]
    by_type = defaultdict(list)
    by_sub = defaultdict(list)
    for r in ok_rows:
        by_type[r["question_type"]].append(r)
        if r["question_type"] == "descriptive":
            by_sub[r["question_subtype"]].append(r)
    overall = _agg(ok_rows)
    su = setup["usage"]
    n = overall["n"]
    amort = {f: round((su[f] + overall["tokens_sum"][f]) / n, 1) if n else None for f in TOKEN_FIELDS}
    return {
        "system": setup["system"], "model": setup["model"], "reasoning_effort": setup["reasoning_effort"],
        "coverage": {"answered": n, "errors": len(errors), "expected": len(uids)},
        "overall": overall,
        "by_type": {t: _agg(by_type[t]) for t in QUESTION_TYPES if by_type[t]},
        "descriptive_subtypes": {s: _agg(v) for s, v in sorted(by_sub.items())},
        "setup": {"usage": su, "latency_s": setup["latency_s"], "info": setup["info"]},
        "amortized_tokens_per_question": amort,
        # per-question outcomes, for paired comparisons between systems
        "correct": {r["uid"]: bool(r["score"]["question_correct"]) for r in ok_rows},
        "qtype": {r["uid"]: r["question_type"] for r in ok_rows},
    }


def add_paired(rep: dict, reference: str = "otf") -> None:
    """For every model with a `reference` system: its accuracy minus each other system's (same model),
    overall and per question type."""
    out = []
    for ref in [s for s in rep["systems"] if s["system"] == reference]:
        for other in rep["systems"]:
            if other is ref or other["model"] != ref["model"]:
                continue
            row = {"model": ref["model"], "reference": reference, "other": other["system"],
                   "overall": paired_diff(ref["correct"], other["correct"], sorted(ref["correct"]))}
            for t in QUESTION_TYPES:
                uids = sorted(u for u, q in ref["qtype"].items() if q == t)
                row[t] = paired_diff(ref["correct"], other["correct"], uids)
            out.append(row)
    rep["paired"] = out


def _fmt(x, nd=1):
    if x is None:
        return "-"
    return f"{x:,.{nd}f}" if isinstance(x, float) else f"{x:,}"


def to_markdown(rep: dict) -> str:
    systems = rep["systems"]
    cfg = rep["build_config"]
    L = [f"# CLEVRER document-QA benchmark: {rep['run']}", "",
         f"- Videos: {cfg.get('n_videos', cfg.get('n_scopes'))} (validation split, seed {cfg.get('seed')}), "
         f"questions: {cfg['n_questions']}",
         f"- Document: `{rep['pdf']}` ({rep['pages']} pages), rendered from ground-truth annotations "
         f"(observed 128 frames only; motion log every {cfg.get('motion_stride')} frames + event frames)",
         "- Descriptive: exact match. Multiple-choice: per-option accuracy, and per-question accuracy "
         "(all options of the question correct). Overall question accuracy counts each question once.",
         ""]
    L += ["## Overall", "",
          "| System | Model | Answered | Errors | Question acc. (%) | Option acc. (%) | Parse err. |",
          "|---|---|---|---|---|---|---|"]
    for s in systems:
        o = s["overall"]
        L.append(f"| {s['system']} | {s['model']} | {s['coverage']['answered']}/{s['coverage']['expected']} | "
                 f"{s['coverage']['errors']} | {_fmt(o['question_accuracy'], 2)} | {_fmt(o['option_accuracy'], 2)} | "
                 f"{o['parse_errors']} |")
    L += ["", "## Accuracy by question type", "",
          "Descriptive: accuracy. Others: per-option / per-question.", "",
          "| System | " + " | ".join(QUESTION_TYPES) + " |", "|---|" + "---|" * len(QUESTION_TYPES)]
    for s in systems:
        cells = []
        for t in QUESTION_TYPES:
            a = s["by_type"].get(t)
            if not a:
                cells.append("-")
            elif t == "descriptive":
                cells.append(f"{_fmt(a['question_accuracy'], 2)} (n={a['n']})")
            else:
                cells.append(f"{_fmt(a['option_accuracy'], 2)} / {_fmt(a['question_accuracy'], 2)} (n={a['n']})")
        L.append(f"| {s['system']} | " + " | ".join(cells) + " |")
    L += ["", "### Question accuracy (%) with 95% bootstrap CI", "",
          "| System | Model | overall | " + " | ".join(QUESTION_TYPES) + " |",
          "|---|---|---|" + "---|" * len(QUESTION_TYPES)]
    for s in systems:
        def ci(a):
            if not a or a.get("question_accuracy_ci95") is None:
                return "-"
            lo, hi = a["question_accuracy_ci95"]
            return f"{_fmt(a['question_accuracy'], 1)} [{lo:.1f}, {hi:.1f}]"
        L.append(f"| {s['system']} | {s['model']} | {ci(s['overall'])} | "
                 + " | ".join(ci(s["by_type"].get(t)) for t in QUESTION_TYPES) + " |")
    if rep.get("paired"):
        L += ["", "### Paired differences: reference minus other (accuracy points, 95% paired-bootstrap CI, "
              "p = share of resamples <= 0)", "",
              "| Model | Reference vs other | overall | " + " | ".join(QUESTION_TYPES) + " |",
              "|---|---|---|" + "---|" * len(QUESTION_TYPES)]
        for row in rep["paired"]:
            def pd(x):
                return "-" if not x else f"{x['diff']:+.1f} [{x['ci95'][0]:+.1f}, {x['ci95'][1]:+.1f}] p={x['p_le_0']:.3f}"
            L.append(f"| {row['model']} | {row['reference']} vs {row['other']} | {pd(row['overall'])} | "
                     + " | ".join(pd(row.get(t)) for t in QUESTION_TYPES) + " |")
    subs = sorted({k for s in systems for k in s["descriptive_subtypes"]})
    if subs:
        L += ["", "### Descriptive subtypes (accuracy %)", "", "| System | " + " | ".join(subs) + " |",
              "|---|" + "---|" * len(subs)]
        for s in systems:
            L.append(f"| {s['system']} | " + " | ".join(
                _fmt(s["descriptive_subtypes"].get(k, {}).get("question_accuracy"), 2) for k in subs) + " |")
    L += ["", "## Token consumption", "",
          "Query tokens are per question (mean). Cached input is a subset of input; reasoning is a subset "
          "of output. Setup = one-time cost (e.g. PageIndex tree build). Amortized = (setup + all query "
          "tokens) / questions answered.", "",
          "| System | Input | Cached input | Output | Reasoning | Total / q | Setup total | Amortized total / q | "
          "Sum (all q) | LLM calls / q | Tool calls / q | Latency / q (s) |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in systems:
        m, o = s["overall"]["tokens_mean"], s["overall"]
        L.append(f"| {s['system']} | {_fmt(m['input_tokens'])} | {_fmt(m['cached_input_tokens'])} | "
                 f"{_fmt(m['output_tokens'])} | {_fmt(m['reasoning_tokens'])} | {_fmt(m['total_tokens'])} | "
                 f"{_fmt(s['setup']['usage']['total_tokens'])} | {_fmt(s['amortized_tokens_per_question']['total_tokens'])} | "
                 f"{_fmt(o['tokens_sum']['total_tokens'])} | {_fmt(o['llm_calls_mean'], 2)} | "
                 f"{_fmt(o['tool_calls_mean'], 2)} | {_fmt(o['latency_mean_s'], 2)} |")
    L += ["", "### Mean total tokens per question, by type", "",
          "| System | " + " | ".join(QUESTION_TYPES) + " |", "|---|" + "---|" * len(QUESTION_TYPES)]
    for s in systems:
        L.append(f"| {s['system']} | " + " | ".join(
            _fmt(s["by_type"].get(t, {}).get("tokens_mean", {}).get("total_tokens")) for t in QUESTION_TYPES) + " |")
    L += ["", "### Setup details", ""]
    for s in systems:
        su = s["setup"]
        L.append(f"- **{s['system']}**: {_fmt(su['usage']['total_tokens'])} tokens "
                 f"({_fmt(su['usage']['input_tokens'])} in / {_fmt(su['usage']['output_tokens'])} out, "
                 f"{su['usage']['llm_calls']} calls), {su['latency_s']:.1f}s, info: `{json.dumps(su['info'])}`")
    return "\n".join(L) + "\n"


def make_report(run_dir: Path, systems: list[str] | None = None) -> dict:
    items = load_items(run_dir / "items.jsonl")
    uids = {it.uid for it in items}
    sys_root = run_dir / "systems"
    names = systems or sorted(p.name for p in sys_root.iterdir() if (p / "predictions.jsonl").exists())
    manifest = json.loads((run_dir / "manifest.json").read_text())
    rep = {"run": run_dir.name, "pdf": str(run_dir / "document.pdf"),
           "pages": manifest["videos"][-1]["end_page"],
           "build_config": json.loads((run_dir / "build_config.json").read_text()),
           "systems": [system_report(sys_root / n, uids) for n in names]}
    add_paired(rep)
    (run_dir / "report.json").write_text(json.dumps(rep, indent=2))
    (run_dir / "report.md").write_text(to_markdown(rep), encoding="utf-8")
    return rep


def make_split_report(runs_root: Path, name: str, systems: list[str] | None = None, out: str | None = None) -> dict:
    """Pool every document of a split (runs/<name>_dNN) into runs/<out or name>_report.{json,md}.
    A system is reported only once it has a setup.json in every document."""
    docs = sorted(p for p in runs_root.glob(f"{name}_d[0-9]*") if p.is_dir())
    items = [it for d in docs for it in load_items(d / "items.jsonl")]
    uids = {it.uid for it in items}
    names = systems or sorted({p.name for d in docs if (d / "systems").exists() for p in (d / "systems").iterdir()
                               if (p / "predictions.jsonl").exists()})
    names = [n for n in names if all((d / "systems" / n / "setup.json").exists() for d in docs)]
    cfgs = [json.loads((d / "build_config.json").read_text()) for d in docs]
    pages = sum(json.loads((d / "manifest.json").read_text())["videos"][-1]["end_page"] for d in docs)
    rep = {"run": f"{name} ({len(docs)} documents)", "pdf": f"{docs[0].name} .. {docs[-1].name}", "pages": pages,
           # other domains' build configs count scopes ("n_scopes") and have no motion log
           "build_config": {"n_videos": sum(c.get("n_videos", c.get("n_scopes", 0)) for c in cfgs),
                            "seed": cfgs[0].get("split_seed"), "n_questions": len(items),
                            "motion_stride": cfgs[0].get("motion_stride")},
           "systems": [system_report([d / "systems" / n for d in docs], uids) for n in names]}
    add_paired(rep)
    (runs_root / f"{out or name}_report.json").write_text(json.dumps(rep, indent=2))
    (runs_root / f"{out or name}_report.md").write_text(to_markdown(rep), encoding="utf-8")
    return rep
