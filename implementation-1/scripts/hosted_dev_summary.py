"""Dev-check summary for the hosted models (SPEC sec. 5, "Move to OpenRouter"): per model, whether OTF generation
passed, its forecast F1 and setup tokens, and pilot20 accuracy by type next to the hand-written oracle; plus the
dev documents and token metering (input / cached / output / reasoning).

    python scripts/hosted_dev_summary.py
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ("or-gpt-oss-20b", "or-qwen3.6-27b", "or-gemma-4-31b-think")
TYPES = ("counterfactual", "descriptive", "explanatory", "predictive")


def rows(p: Path) -> list[dict]:
    if not p.exists():
        return []
    last = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        last[r["uid"]] = r
    return [r for r in last.values() if "error" not in r]


def acc(rs: list[dict]) -> str:
    by = defaultdict(lambda: [0, 0])
    for r in rs:
        by[r["question_type"]][0] += bool(r["score"].get("question_correct"))
        by[r["question_type"]][1] += 1
    cells = [f"{by[t][0]}/{by[t][1]}" for t in TYPES]
    n_ok, n = sum(v[0] for v in by.values()), sum(v[1] for v in by.values())
    return " | ".join(cells) + f" | **{n_ok}/{n} ({100 * n_ok / max(n, 1):.1f}%)**"


def meter(rs: list[dict]) -> str:
    t = defaultdict(int)
    for r in rs:
        for k in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "llm_calls"):
            t[k] += r.get("usage", {}).get(k, 0)
    n = max(len(rs), 1)
    return (f"in {t['input_tokens'] / n / 1e3:.1f}k, cached {t['cached_input_tokens'] / n / 1e3:.1f}k, "
            f"out {t['output_tokens'] / n / 1e3:.2f}k, reasoning {t['reasoning_tokens'] / n / 1e3:.2f}k, "
            f"calls {t['llm_calls'] / n:.1f} per question")


def setup_info(sys_dir: Path) -> str:
    p = sys_dir / "setup.json"
    if not p.exists():
        return "no setup.json"
    s = json.loads(p.read_text())
    i, u = s["info"], s["usage"]
    tot = u["input_tokens"] + u["output_tokens"]
    if i.get("model_code"):
        return "hand-written"
    m = json.loads((sys_dir / "work" / "otf_model.json").read_text())["model"] if \
        (sys_dir / "work" / "otf_model.json").exists() else {}
    return (f"passed={i.get('model_passed')} F1={i.get('model_f1')} failed_step={m.get('failed_step')} "
            f"tries={i.get('model_tries')} setup={tot / 1e3:.0f}k tokens (reasoning {u['reasoning_tokens'] / 1e3:.0f}k, "
            f"{u['llm_calls']} calls, {s['latency_s'] / 60:.0f} min)")


print("## pilot20 (all 308 questions): cf | desc | expl | pred | total\n")
for m in MODELS:
    for sysname in ("otf_oracle", "otf"):
        d = ROOT / "runs" / "pilot20" / "systems" / f"{sysname}__{m}"
        rs = rows(d / "predictions.jsonl")
        tr = [r.get("trace") or {} for r in rs]
        routed = sum(t.get("routed_type") == r["question_type"] for t, r in zip(tr, rs))
        tools = sum(bool(t.get("used_tool")) for t in tr)
        fb = sum(bool(t.get("fallback")) for t in tr)
        terr = sum(bool(t.get("tool_error")) for t in tr)
        print(f"- {m} {sysname}: {acc(rs)}")
        print(f"  setup: {setup_info(d)}")
        print(f"  router {routed}/{len(rs)}, tools used {tools}, fallback {fb}, tool errors {terr}; {meter(rs)}")
print("\n## dev documents (use_library=false, first 4 questions)\n")
for dev in ("mfg_dev", "itops_dev", "fin_dev"):
    for m in MODELS:
        d = ROOT / "runs" / dev / "systems" / f"otf_no_library__{m}"
        rs = rows(d / "predictions.jsonl")
        tr = [r.get("trace") or {} for r in rs]
        print(f"- {dev} {m}: {setup_info(d)}; answered {len(rs)}/4, tools used "
              f"{sum(bool(t.get('used_tool')) for t in tr)}, tool errors {sum(bool(t.get('tool_error')) for t in tr)}")
