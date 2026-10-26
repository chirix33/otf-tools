"""Collect the Tier B results for colleagues into one folder (and a zip) with a results analysis.

    python scripts/tier_b_handoff.py            (standard library only; also run automatically after delivery)

Writes implementation-1/tier_b_results/:
  TIER_B_RESULTS.md     analysis: what ran, accuracy (overall, by type, by document), paired significance tests,
                        dev selection, cost and efficiency, failure modes, caveats
  reports/              e1_report.md/.json, per-document reports, DELIVERY.md, delivery_manifest.json
  e1/<doc>/<system>__<model>/   predictions.jsonl, setup.json, calls.jsonl (call ledger), attempts.jsonl if any
  dev/pilot20/<candidate>/      the same for every pilot20 candidate run
  freeze/               frozen selections, GraphRAG index decision, auto-tuned GraphRAG prompts
  provenance.json, timing.json, SHA256SUMS.txt
and tier_b_results.zip next to it. GraphRAG index folders (~300 MB) are not copied; they are rebuildable and stay
in runs/tier_b/graphrag_index.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
E1_CORE = ["e1_d03", "e1_d06", "e1_d09", "e1_d12", "e1_d15"]
TYPES = ["descriptive", "explanatory", "predictive", "counterfactual"]
SYSTEM_NAMES = {"react_r": "ReAct-R (retrieval tools)", "react_c": "ReAct-C (retrieval + Python tools)",
                "graphrag": "GraphRAG (local search)", "recode": "ReCode (recursive code agent)"}
# OpenRouter list prices, USD per million tokens (input, output), checked 2026-10-26. Local runs cost no API money.
PRICES = {"or-qwen3.6-27b": (0.45, 2.70), "or-gpt-oss-20b": (0.03, 0.13), "or-gemma-4-31b-think": (0.14, 0.40)}
FILES = ("predictions.jsonl", "setup.json", "calls.jsonl", "attempts.jsonl")


def jload(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def jlines(p: Path) -> list[dict]:
    out = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def family(model: str) -> str:
    return model.removeprefix("or-")


def pct(x) -> str:
    return "-" if x is None else f"{x:.1f}"


def num(x) -> str:
    return "-" if x is None else f"{x:,.0f}"


def mcnemar_p(b: int, c: int) -> float:
    """Exact two-sided McNemar test on the discordant pairs (b: only A correct, c: only B correct)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def table(head: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + \
           ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]


def served_label(model: str, served_by: dict) -> str:
    s = served_by.get(model) or ""                 # e.g. "hosted: https://openrouter.ai/api/v1 qwen/..., provider X"
    if s.startswith("hosted:"):
        return "OpenRouter" + (f", provider {s.rsplit('provider ', 1)[1]}" if "provider " in s else "")
    return s.replace("local vLLM: ", "local GPU, vLLM: ") or "local GPU"


def collect(runs: Path, out: Path) -> dict:
    """Copy the deliverable files. Returns what was found."""
    if out.exists():
        shutil.rmtree(out)
    (out / "reports").mkdir(parents=True)
    tb = runs / "tier_b"
    manifest = jload(tb / "delivery_manifest.json", {})
    plan = [(p["model"], p["systems"]) for p in manifest.get("plan", [])]
    answered = {(j["model"], j["system"]) for j in manifest.get("jobs", []) if j.get("answered")}
    not_run = [m for m, ss in plan if not any((m, s) in answered for s in ss)]
    plan = [(m, ss) for m, ss in plan if m not in not_run]       # a model with no answers at all is listed apart
    for f in ("e1_report.md", "e1_report.json"):
        if (runs / f).exists():
            shutil.copy2(runs / f, out / "reports" / f)
    for f in ("DELIVERY.md", "delivery_manifest.json"):
        if (tb / f).exists():
            shutil.copy2(tb / f, out / "reports" / f)
    for doc in E1_CORE:
        for f in ("report.md", "report.json"):
            if (runs / doc / f).exists():
                shutil.copy2(runs / doc / f, out / "reports" / f"{doc}_{f}")
        for model, systems in plan:
            for s in systems:
                src = runs / doc / "systems" / f"{s}__{model}"
                for f in FILES:
                    if (src / f).exists():
                        (out / "e1" / doc / src.name).mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src / f, out / "e1" / doc / src.name / f)
    models = {m for m, _ in plan}
    for src in sorted((runs / "pilot20" / "systems").glob("*__*")):
        if src.name.rsplit("__", 1)[1] in models:
            for f in FILES:
                if (src / f).exists():
                    (out / "dev" / "pilot20" / src.name).mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src / f, out / "dev" / "pilot20" / src.name / f)
    (out / "freeze").mkdir()
    for p in sorted((tb / "freeze").glob("*.json")) + sorted(tb.glob("graphrag_decision__*.json")):
        shutil.copy2(p, out / "freeze" / p.name)
    if (tb / "graphrag_tuned").exists():
        shutil.copytree(tb / "graphrag_tuned", out / "freeze" / "graphrag_tuned_prompts",
                        ignore=shutil.ignore_patterns("*.jsonl"))
    for f in ("provenance.json", "timing.json"):
        if (tb / f).exists():
            shutil.copy2(tb / f, out / f)
    spec = ROOT / "SPEC.md"
    if spec.exists():
        m = re.search(r"<!-- TIER-B-FREEZE:BEGIN.*?<!-- TIER-B-FREEZE:END -->", spec.read_text(encoding="utf-8"), re.S)
        if m:
            (out / "freeze" / "SPEC_tier_b_block.md").write_text(m.group(0) + "\n", encoding="utf-8")
    return {"manifest": manifest, "plan": plan, "not_run": not_run}


def analysis(runs: Path, found: dict) -> str:
    manifest, plan = found["manifest"], found["plan"]
    rep = jload(runs / "e1_report.json", {})
    sysrep = {(r["system"], r["model"]): r for r in rep.get("systems", [])}
    served_by = {p["model"]: p.get("served_by") or "" for p in manifest.get("plan", [])}
    doc_uids = {d: [json.loads(l)["uid"] for l in (runs / d / "items.jsonl").read_text(encoding="utf-8").splitlines()]
                for d in E1_CORE if (runs / d / "items.jsonl").exists()}
    jobs = [(m, s) for m, ss in plan for s in ss]
    complete = {}
    for j in manifest.get("jobs", []):                 # a run is complete when all its E1 documents validate
        k = (j["model"], j["system"])
        complete[k] = complete.get(k, True) and bool(j.get("complete"))
    done = [(m, s) for m, s in jobs if (s, m) in sysrep and complete.get((m, s))]
    missing = [(m, s) for m, s in jobs if (m, s) not in done]
    fams = list(dict.fromkeys(family(m) for m, _ in plan))
    n_q = rep.get("build_config", {}).get("n_questions") or sum(len(v) for v in doc_uids.values())
    L: list[str] = []
    gen = datetime.now().isoformat(timespec="minutes")
    L += ["# Tier B baselines: results and analysis", "",
          f"Generated {gen} from `runs/` by `scripts/tier_b_handoff.py` (re-run it to refresh). "
          f"**{len(done)}/{len(jobs)} system-model runs complete** on E1-core.", ""]

    # ------------------------------------------------------------------ 1. setup
    L += ["## 1. What was run", "",
          f"- **Benchmark:** CLEVRER document QA, E1-core = {', '.join(E1_CORE)} ({n_q} questions, "
          f"{rep.get('build_config', {}).get('n_videos', '?')} videos, {rep.get('pages', '?')} pages). Development and "
          "selection used pilot20 only (308 questions); E1 questions were answered once, after the freeze.",
          "- **Systems:** " + "; ".join(f"`{s}` = {SYSTEM_NAMES.get(s, s)}" for s in dict.fromkeys(s for _, s in jobs)) + ".",
          "- **Shared caps:** at most 12 model calls per question and 16,384 output tokens per call; frozen sampling "
          "settings from `configs/models.json`; the same answer contract and scorer as Tier A.",
          "- **Selection:** each system had up to 3 predefined candidate slots, run on all of pilot20 and chosen by "
          "accuracy, then fewer total tokens, then the earlier slot. The choice was frozen (config hash) before any "
          "E1 question.", "", "Where each run was served:", ""]
    L += table(["Model alias", "Served by", "Systems"],
               [[f"`{m}`", served_label(m, served_by), ", ".join(ss)] for m, ss in plan])
    if found["not_run"]:
        L += ["", "**Planned but not run:** " + ", ".join(f"`{m}`" for m in found["not_run"]) + "."]
    if missing:
        L += ["", "**Not complete:** " + ", ".join(f"{s} on `{m}`" for m, s in missing) +
              f" ({manifest.get('partial_reason') or 'still running or not started'}). Those rows are missing below."]

    # ------------------------------------------------------------------ 2. headline
    L += ["", "## 2. Headline results (E1-core)", "",
          "Question accuracy counts each question once (a multiple-choice question is correct only when every option "
          "is). 95% CIs are bootstrap intervals from the report. Tokens are per question; GraphRAG's one-time "
          "indexing cost is in *setup* and in the amortized column. Cost is at OpenRouter list prices (local runs: $0 "
          "API cost, GPU time instead).", ""]
    rows, costs = [], {}
    for m, s in done:
        r = sysrep[(s, m)]
        o = r["overall"]
        su = (r.get("setup") or {}).get("usage") or {}
        tin = o["tokens_sum"]["input_tokens"] + su.get("input_tokens", 0)
        tout = o["tokens_sum"]["output_tokens"] + su.get("output_tokens", 0)
        pin, pout = PRICES.get(m, (0.0, 0.0))
        costs[(m, s)] = (tin * pin + tout * pout) / 1e6
        ci = o.get("question_accuracy_ci95") or [None, None]
        rows.append([SYSTEM_NAMES.get(s, s), f"`{m}`", f"**{pct(o['question_accuracy'])}** [{pct(ci[0])}, {pct(ci[1])}]",
                     pct(o["option_accuracy"]), o["parse_errors"], num(o["tokens_mean"]["total_tokens"]),
                     num(r["amortized_tokens_per_question"]["total_tokens"]), f"{o['llm_calls_mean']:.1f}",
                     f"${costs[(m, s)]:.2f}" if m in PRICES else "local", f"{o['latency_mean_s']:.0f}"])
    L += table(["System", "Model", "Question acc. % [95% CI]", "Option acc. %", "Parse errors", "Tokens / q",
                "Amortized tokens / q", "Calls / q", "API cost (E1)", "Latency / q (s)"], rows)

    # ------------------------------------------------------------------ 3. by type
    L += ["", "## 3. Accuracy by question type", "",
          "Question accuracy %, with n per type. Descriptive questions are exact match; the other three are "
          "multiple choice (all options must be right).", ""]
    rows = []
    for m, s in done:
        bt = sysrep[(s, m)]["by_type"]
        rows.append([SYSTEM_NAMES.get(s, s), f"`{m}`"] +
                    [f"{pct(bt[t]['question_accuracy'])} (n={bt[t]['n']})" if t in bt else "-" for t in TYPES])
    L += table(["System", "Model"] + TYPES, rows)
    sub = [(m, s) for m, s in done if sysrep[(s, m)].get("descriptive_subtypes")]
    if sub:
        names = list(sysrep[(sub[0][1], sub[0][0])]["descriptive_subtypes"])
        L += ["", "Descriptive subtypes (accuracy %):", ""]
        L += table(["System", "Model"] + names,
                   [[SYSTEM_NAMES.get(s, s), f"`{m}`"] + [pct(sysrep[(s, m)]["descriptive_subtypes"].get(n, {})
                                                            .get("question_accuracy")) for n in names] for m, s in sub])

    # ------------------------------------------------------------------ 4. by document
    L += ["", "## 4. Accuracy by document", "",
          "Question accuracy % per E1-core document; the spread shows how stable each system is across documents.", ""]
    rows = []
    for m, s in done:
        cor = sysrep[(s, m)]["correct"]
        accs = [100 * sum(cor.get(u, False) for u in doc_uids[d]) / len(doc_uids[d]) for d in E1_CORE if d in doc_uids]
        rows.append([SYSTEM_NAMES.get(s, s), f"`{m}`"] + [pct(a) for a in accs] +
                    [f"{min(accs):.1f}-{max(accs):.1f}" if accs else "-"])
    L += table(["System", "Model"] + [d for d in E1_CORE if d in doc_uids] + ["Range"], rows)

    # ------------------------------------------------------------------ 5. paired tests
    L += ["", "## 5. Paired comparisons", "",
          "Every system answered the same questions, so differences are tested pairwise with an exact McNemar test "
          "on the questions where exactly one of the two is right. *A only / B only* = questions only that system "
          "got right.", ""]
    rows = []
    pairs = []
    for f in fams:
        ms = [(m, s) for m, s in done if family(m) == f]
        pairs += [(a, b) for i, a in enumerate(ms) for b in ms[i + 1:]]
    for s in dict.fromkeys(s for _, s in done):
        ms = [(m, ss) for m, ss in done if ss == s]
        pairs += [(a, b) for i, a in enumerate(ms) for b in ms[i + 1:] if family(a[0]) != family(b[0])]
    for a, b in pairs:
        ca, cb = sysrep[(a[1], a[0])]["correct"], sysrep[(b[1], b[0])]["correct"]
        uids = set(ca) & set(cb)
        only_a = sum(ca[u] and not cb[u] for u in uids)
        only_b = sum(cb[u] and not ca[u] for u in uids)
        p = mcnemar_p(only_a, only_b)
        acc_a, acc_b = (100 * sum(c[u] for u in uids) / len(uids) for c in (ca, cb))
        rows.append([f"{a[1]} `{a[0]}`", f"{b[1]} `{b[0]}`", f"{acc_a - acc_b:+.1f}", only_a, only_b,
                     "<0.001" if p < 0.001 else f"{p:.3f}", "yes" if p < 0.05 else "no"])
    L += table(["A", "B", "A - B (pts)", "A only", "B only", "p (exact McNemar)", "Significant at 0.05"], rows) \
        if rows else ["(needs at least two complete runs)"]

    # ------------------------------------------------------------------ 6. dev selection
    L += ["", "## 6. Development selection on pilot20", "",
          "All candidates of each system on pilot20 (308 questions) and the frozen choice. *Dev to E1* compares the "
          "frozen slot's pilot20 accuracy with its E1-core accuracy.", ""]
    rows = []
    for m, s in jobs:
        fz = jload(runs / "tier_b" / "freeze" / f"{s}__{m}.json")
        if not fz:
            continue
        e1 = sysrep.get((s, m), {}).get("overall", {}).get("question_accuracy") if (m, s) in done else None
        for c in fz["candidates"]:
            sel = c["slot"] == fz["selected_slot"]
            extra = c["kwargs"].get("index_method")
            rows.append([SYSTEM_NAMES.get(s, s), f"`{m}`", f"{c['slot']}{' (selected)' if sel else ''}",
                         pct(c["accuracy"]), num(c["total_tokens"]), c.get("parse_errors", "-"),
                         extra or "-", f"{pct(c['accuracy'])} -> {pct(e1)}" if sel and e1 is not None else ""])
    L += table(["System", "Model", "Slot", "pilot20 acc. %", "Total tokens", "Parse errors", "Index", "Dev to E1"],
               rows) if rows else ["(no frozen selections yet)"]
    for m, _ in plan:
        dec = jload(runs / "tier_b" / f"graphrag_decision__{m}.json")
        if dec:
            ex = dec.get("standard_extraction") or {}
            L += ["", f"GraphRAG indexing for `{m}`: **{dec.get('index_method')}** (rule: {dec.get('rule')}; standard "
                      f"extraction failed on {ex.get('failed_chunks')}/{ex.get('chunks')} pilot20 chunks)."]

    # ------------------------------------------------------------------ 7. cost
    L += ["", "## 7. Cost and efficiency", "",
          "Tokens per correct answer = all E1 tokens (including setup) / correctly answered questions. Lower is "
          "better.", ""]
    rows = []
    for m, s in done:
        r = sysrep[(s, m)]
        o = r["overall"]
        su = (r.get("setup") or {}).get("usage") or {}
        tot = o["tokens_sum"]["total_tokens"] + su.get("total_tokens", 0)
        ncor = sum(r["correct"].values())
        reas = o["tokens_mean"].get("reasoning_tokens") or 0
        rows.append([SYSTEM_NAMES.get(s, s), f"`{m}`", num(tot), num(su.get("total_tokens", 0)),
                     f"{100 * reas / max(o['tokens_mean']['output_tokens'], 1):.0f}%", num(tot / max(ncor, 1)),
                     f"${costs[(m, s)]:.2f}" if m in PRICES else "local",
                     f"${1000 * costs[(m, s)] / max(ncor, 1):.2f}" if m in PRICES else "-"])
    L += table(["System", "Model", "E1 tokens (all)", "of which setup", "Reasoning share of output",
                "Tokens / correct answer", "API cost", "Cost / 1,000 correct"], rows)
    spend = ledger_spend(runs, [m for m, _ in plan])
    if spend:
        L += ["", "Whole Tier B budget from the call ledgers (every successful call: pilot20 development, GraphRAG "
                  "indexing and prompt tuning, E1), at list prices:", ""]
        L += table(["Model", "Input tokens", "Output tokens", "API cost"],
                   [[f"`{m}`", num(v[0]), num(v[1]), f"${v[2]:.2f}" if m in PRICES else "local"]
                    for m, v in spend.items()])

    # ------------------------------------------------------------------ 8. failure modes
    L += ["", "## 8. Failure modes", "",
          "From each prediction's trace. A parse error is a reply without a valid answer object (scored wrong). "
          "*Truncated* = the 16,384-token output cap was hit. *Call cap* = the 12-call budget ran out. *No answer* = "
          "the agent stopped without submitting one.", ""]
    rows = []
    fails = manifest.get("failures", {})
    for m, s in done:
        outcomes, pe = {}, {}
        for d in E1_CORE:
            for r in jlines(runs / d / "systems" / f"{s}__{m}" / "predictions.jsonl"):
                if "error" in r:
                    continue
                o = (r.get("trace") or {}).get("outcome") or "answered"
                outcomes[o] = outcomes.get(o, 0) + 1
                if "parse_error" in r.get("parsed", {}):
                    k = str(r["parsed"]["parse_error"])[:40]
                    pe[k] = pe.get(k, 0) + 1
        f = fails.get(f"{s}__{m}", {})
        rows.append([SYSTEM_NAMES.get(s, s), f"`{m}`", f.get("parse_errors", sum(pe.values())), f.get("truncated", "-"),
                     f.get("call_cap_exhausted", "-"), f.get("errored_attempts", "-"),
                     ", ".join(f"{k}: {v}" for k, v in sorted(outcomes.items(), key=lambda kv: -kv[1])),
                     ", ".join(f"{k}: {v}" for k, v in sorted(pe.items(), key=lambda kv: -kv[1])) or "-"])
    L += table(["System", "Model", "Parse errors", "Truncated", "Call cap", "Retried infra errors", "Outcomes",
                "Parse error kinds"], rows)

    # ------------------------------------------------------------------ 9. findings
    L += ["", "## 9. Key findings", ""]
    L += findings(done, sysrep, costs, pairs, runs)

    # ------------------------------------------------------------------ 10. caveats
    L += ["", "## 10. Caveats and deviations from the plan", ""]
    cav = []
    if any(not m.startswith("or-") for m, _ in plan) and any(m.startswith("or-") for m, _ in plan):
        loc = [f"{s} on `{m}`" for m, ss in plan if not m.startswith("or-") for s in ss]
        cav.append(f"Mixed serving: {', '.join(loc)} ran on the local GPU (NVFP4 checkpoint, vLLM); the other runs used "
                   "OpenRouter with one pinned provider per model. Same model weights family and sampling settings, "
                   "but different quantisation and serving stack, so compare systems within one serving where "
                   "possible. Latency is not comparable across servings.")
    if not any("gemma" in m for m, _ in plan) or any("gemma" in m for m in found["not_run"]):
        cav.append("Gemma 4 31B was dropped from Tier B on 2026-10-26: its bf16 OpenRouter providers were "
                   "rate-limited and the remaining time did not fit a full run. gpt-oss-20b (the Tier A model) is the "
                   "second model instead.")
    if any("gpt-oss" in m for m, _ in plan):
        cav.append("Two robustness fixes were added on 2026-10-26, before gpt-oss-20b's development stage (its first "
                   "attempt was discarded after a few minutes; kept in `_discarded_runs/`): (1) a reply that OpenRouter "
                   "ends with finish_reason \"error\" (a provider failure mid-generation) is retried as an "
                   "infrastructure error instead of being scored; Qwen's runs had no such replies. (2) In ReAct, calling "
                   "`finish` without its `answer_json` argument returns an error to the model, which can call again "
                   "within the 12-call cap; before, it ended the question with an empty answer. Qwen did this once "
                   "(ReAct-C, e1_d03, question 13778-6, scored wrong), so Qwen's ReAct-C score could be at most one "
                   "question (0.14 points) higher under the new rule. Empty replies (no text, no tool call) remain a "
                   "model outcome for both models, as in the Tier A baselines.")
    n_fix = sum(1 for p in runs.glob("*/systems/graphrag*/*.jsonl") for r in jlines(p) if r.get("usage_corrected"))
    if n_fix:
        cav.append(f"GraphRAG token accounting: {n_fix} rows (answers and ledger entries, mostly pilot20) recorded "
                   "through LiteLLM's streaming path missed reasoning tokens; they were corrected from the reasoning "
                   "counts the provider returned "
                   "(`scripts/repair_stream_usage.py`, rows marked `usage_corrected`). Later calls are sent "
                   "non-streamed, so their counts are exact. Answers were unaffected.")
    nocache = sorted({m for m, s in done if m.startswith("or-") and
                      not sysrep[(s, m)]["overall"]["tokens_sum"].get("cached_input_tokens")})
    if nocache:
        cav.append("Cached input tokens: " + ", ".join(f"`{m}`" for m in nocache) + " reported none (the provider does "
                   "not return them), so those rows show 0 cached tokens; it does not mean no prompt reuse happened.")
    over = [f"{s} `{m}`" for m, s in done if (sysrep[(s, m)]["overall"]["tokens_mean"].get("reasoning_tokens") or 0)
            > sysrep[(s, m)]["overall"]["tokens_mean"]["output_tokens"]]
    if over:
        cav.append("Reasoning tokens above output tokens (" + ", ".join(over) + "): on GraphRAG's LiteLLM path the "
                   "reasoning count is LiteLLM's own estimate, while output tokens (which include reasoning) are the "
                   "provider's billed count. Totals and costs use the output count, so they are unaffected.")
    cav.append("Errored attempts (network/provider errors) were retried and are excluded from scoring; every question "
               "has exactly one scored answer (see `reports/delivery_manifest.json`).")
    cav.append("API costs are estimates at list prices from the token ledgers; the OpenRouter invoice is the "
               "authoritative number.")
    L += [f"- {c}" for c in cav]

    # ------------------------------------------------------------------ 11. files
    L += ["", "## 11. Files in this folder", "",
          "- `reports/e1_report.md` / `.json`: the benchmark's own aggregate report (per-question correctness in the "
          "JSON); `reports/e1_dXX_report.*`: per document.",
          "- `reports/DELIVERY.md`, `reports/delivery_manifest.json`: completeness check, SHA-256 of every "
          "prediction file, where each run was served, failure counts.",
          "- `e1/<document>/<system>__<model>/predictions.jsonl`: one line per question: raw output, parsed answer, "
          "score, token usage, latency and the full agent trace. `calls.jsonl`: every model call (including failed "
          "attempts) with its usage. `setup.json`: one-time setup cost and provenance.",
          "- `dev/pilot20/<system>_c<slot>__<model>/`: every development candidate, same format.",
          "- `freeze/`: frozen selections (`<system>__<model>.json`, with config hashes), the GraphRAG indexing "
          "decision, the auto-tuned GraphRAG prompts and the SPEC sec. 11 block.",
          "- `provenance.json`: repository commit, dependency versions, checkpoints/providers, package checksums. "
          "`timing.json`: wall-clock time per stage.",
          "- `SHA256SUMS.txt`: checksums of every file here.", ""]
    return "\n".join(L)


def ledger_spend(runs: Path, models: list[str]) -> dict:
    """Input/output tokens and list-price cost per model over every call ledger."""
    out = {}
    for m in models:
        paths = list(runs.glob(f"*/systems/*__{m}/calls.jsonl")) + \
            list((runs / "tier_b" / "graphrag_index").glob(f"*__{m}__*/index_calls.jsonl")) + \
            list((runs / "tier_b" / "graphrag_tuned" / m).glob("*.jsonl"))
        tin = tout = 0
        for p in paths:
            for r in jlines(p):
                u = r.get("usage")
                if r.get("status") == "ok" and u:
                    tin += u.get("input_tokens", 0)
                    tout += u.get("output_tokens", 0)
        if tin or tout:
            pin, pout = PRICES.get(m, (0.0, 0.0))
            out[m] = (tin, tout, (tin * pin + tout * pout) / 1e6)
    return out


def findings(done, sysrep, costs, pairs, runs: Path = None) -> list[str]:
    out = []
    if not done:
        return ["- No complete runs yet."]
    acc = {k: sysrep[(k[1], k[0])]["overall"]["question_accuracy"] for k in done}
    for f in dict.fromkeys(family(m) for m, _ in done):
        ks = sorted([k for k in done if family(k[0]) == f], key=lambda k: -acc[k])
        out.append(f"- **{f}:** " + " > ".join(f"{k[1]} {acc[k]:.1f}%" for k in ks) +
                   f" (spread {acc[ks[0]] - acc[ks[-1]]:.1f} points).")
    best = max(done, key=lambda k: acc[k])
    out.append(f"- Best overall: **{best[1]} on `{best[0]}`** at {acc[best]:.1f}% question accuracy.")
    for t in TYPES:
        vals = {k: sysrep[(k[1], k[0])]["by_type"].get(t, {}).get("question_accuracy") for k in done}
        vals = {k: v for k, v in vals.items() if v is not None}
        if vals:
            b, w = max(vals, key=vals.get), min(vals, key=vals.get)
            out.append(f"- {t.capitalize()}: best {b[1]} `{b[0]}` {vals[b]:.1f}%, worst {w[1]} `{w[0]}` {vals[w]:.1f}%.")
    hardest = {}
    for k in done:
        bt = sysrep[(k[1], k[0])]["by_type"]
        t = min((t for t in TYPES if t in bt), key=lambda t: bt[t]["question_accuracy"])
        hardest[t] = hardest.get(t, 0) + 1
    t, n = max(hardest.items(), key=lambda kv: kv[1])
    out.append(f"- The hardest question type is **{t}** for {n} of {len(done)} runs (all options of a multiple-choice "
               "question must be right; option-level accuracy in the report is much higher).")
    tpc = {k: (sysrep[(k[1], k[0])]["overall"]["tokens_sum"]["total_tokens"] +
               ((sysrep[(k[1], k[0])].get("setup") or {}).get("usage") or {}).get("total_tokens", 0)) /
           max(sum(sysrep[(k[1], k[0])]["correct"].values()), 1) for k in done}
    e = min(tpc, key=tpc.get)
    out.append(f"- Most token-efficient: {e[1]} `{e[0]}` at {tpc[e]:,.0f} tokens per correct answer; least: "
               f"{max(tpc, key=tpc.get)[1]} `{max(tpc, key=tpc.get)[0]}` at {max(tpc.values()):,.0f}.")
    sig = []
    for a, b in pairs:
        ca, cb = sysrep[(a[1], a[0])]["correct"], sysrep[(b[1], b[0])]["correct"]
        u = set(ca) & set(cb)
        p = mcnemar_p(sum(ca[x] and not cb[x] for x in u), sum(cb[x] and not ca[x] for x in u))
        if p >= 0.05:
            sig.append(f"{a[1]} `{a[0]}` vs {b[1]} `{b[0]}` (p={p:.2f})")
    if sig:
        out.append("- Not significantly different (paired test, p >= 0.05): " + "; ".join(sig) + ".")
    gaps = []
    for m, s in done:
        fz = jload(runs / "tier_b" / "freeze" / f"{s}__{m}.json") if runs else None
        if fz:
            dev = next(c["accuracy"] for c in fz["candidates"] if c["slot"] == fz["selected_slot"])
            gaps.append((dev - acc[(m, s)], s, m))
    if gaps:
        lo, hi = min(gaps), max(gaps)
        out.append(f"- Dev-to-E1 gap: the frozen configurations scored {lo[0]:+.1f} ({lo[1]} `{lo[2]}`) to "
                   f"{hi[0]:+.1f} ({hi[1]} `{hi[2]}`) points higher on pilot20 than on E1-core. Some of this is "
                   "selection on the dev set (the best of up to 3 slots), the rest is a difference in difficulty "
                   "between pilot20 and the E1-core documents; E1 numbers are the ones to report.")
    return out


def sha_all(out: Path) -> None:
    lines = []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS.txt":
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out).as_posix()}")
    (out / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    runs = Path(argv[0]) if argv else ROOT / "runs"
    out = Path(argv[1]) if argv and len(argv) > 1 else ROOT / "tier_b_results"
    if not (runs / "tier_b" / "delivery_manifest.json").exists():
        print(f"no delivery manifest in {runs / 'tier_b'}; run run_tier_b.py first")
        return 1
    found = collect(runs, out)
    (out / "TIER_B_RESULTS.md").write_text(analysis(runs, found), encoding="utf-8")
    sha_all(out)
    z = out.with_suffix(".zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(out.rglob("*")):
            if p.is_file():
                zf.write(p, Path(out.name) / p.relative_to(out))
    print(f"results folder: {out}\nzip: {z} ({z.stat().st_size / 2 ** 20:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
