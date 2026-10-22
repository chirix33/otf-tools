"""Summarize smoke-test predictions: accuracy per type, tokens, latency, truncation, parse errors.
    python scripts/smoke_summary.py runs/pilot20 full_context_text__gpt-oss-20b pageindex__gpt-oss-20b
"""
import collections
import json
import statistics as st
import sys
from pathlib import Path

run = Path(sys.argv[1])
for name in sys.argv[2:]:
    rows = {}
    for line in (run / "systems" / name / "predictions.jsonl").read_text().splitlines():
        r = json.loads(line)
        rows[r["uid"]] = r
    ok = [r for r in rows.values() if "error" not in r]
    by = collections.defaultdict(list)
    for r in ok:
        by[r["question_type"]].append(r["score"]["question_correct"])
    u = [r["usage"] for r in ok]
    acc = "  ".join(f"{t[:4]} {sum(v)}/{len(v)}" for t, v in sorted(by.items()))
    print(f"{name}: n={len(ok)} errors={len(rows) - len(ok)}  {acc}")
    print(f"   tokens/q: in {st.mean(x['input_tokens'] for x in u):,.0f} (cached {st.mean(x['cached_input_tokens'] for x in u):,.0f})"
          f"  out {st.mean(x['output_tokens'] for x in u):,.0f} (reasoning {st.mean(x['reasoning_tokens'] for x in u):,.0f}, max {max(x['output_tokens'] for x in u):,})"
          f"  latency/q {st.mean(r['latency_s'] for r in ok):.1f}s"
          f"  truncated {sum((r.get('trace') or {}).get('finish_reason') == 'length' for r in ok)}"
          f"  parse_err {sum('parse_error' in r['parsed'] for r in ok)}")
