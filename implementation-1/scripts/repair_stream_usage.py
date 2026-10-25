"""Correct GraphRAG answer usage recorded through LiteLLM's streaming path (Tier B, before commit "stream as one
request"). LiteLLM rebuilt streamed usage from the visible text, so reasoning tokens were missing from output_tokens
(e.g. output 6, reasoning 1,332). The repository convention is reasoning as a subset of output, so output_tokens
becomes output + reasoning for those rows. Rows are marked and the script is idempotent.

    python scripts/repair_stream_usage.py            (standard library only)
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
MARK = "usage_corrected"
NOTE = "stream_reasoning_added"


def fix_usage(u: dict) -> bool:
    if not u or not u.get("reasoning_tokens"):
        return False
    u["output_tokens"] += u["reasoning_tokens"]
    u["total_tokens"] = u["input_tokens"] + u["output_tokens"]
    return True


def rewrite(path: Path, fix) -> int:
    lines, n = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            lines.append(line)
            continue
        if r.get(MARK) is None and fix(r):
            r[MARK] = NOTE
            n += 1
        lines.append(json.dumps(r, default=str))
    if n:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("".join(l + "\n" for l in lines), encoding="utf-8")
        tmp.replace(path)
    return n


total = 0
for d in sorted(RUNS.glob("*/systems/graphrag*")):
    if (d / "calls.jsonl").exists():
        n = rewrite(d / "calls.jsonl", lambda r: r.get("source") == "litellm_stream" and r.get("status") == "ok"
                    and fix_usage(r.get("usage")))
        total += n
        print(f"{d.relative_to(RUNS)}/calls.jsonl: {n} rows corrected")
    if (d / "predictions.jsonl").exists():
        n = rewrite(d / "predictions.jsonl", lambda r: "error" not in r and fix_usage(r.get("usage")))
        total += n
        print(f"{d.relative_to(RUNS)}/predictions.jsonl: {n} rows corrected")

# freeze records: recompute candidate token totals from the corrected predictions (selection was by accuracy)
for fz_path in sorted((RUNS / "tier_b" / "freeze").glob("graphrag__*.json")):
    fz = json.loads(fz_path.read_text(encoding="utf-8"))
    changed = False
    for c in fz["candidates"]:
        pred = RUNS / c["out_dir"].replace("\\", "/") / "predictions.jsonl"   # recorded on Windows or Linux
        if not pred.exists():
            continue
        rows = {}
        for line in pred.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if "error" not in r:
                rows[r["uid"]] = r
        ans = sum(r["usage"]["total_tokens"] for r in rows.values())
        if ans != c["answer_tokens"]:
            c["answer_tokens"], c["total_tokens"], changed = ans, ans + c["setup_tokens"], True
    if changed:
        fz[MARK] = NOTE
        fz_path.write_text(json.dumps(fz, indent=2, default=str), encoding="utf-8")
        print(f"{fz_path.relative_to(RUNS)}: candidate token totals updated")
print(f"done: {total} rows corrected")
