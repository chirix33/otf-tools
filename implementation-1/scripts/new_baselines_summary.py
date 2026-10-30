"""Final table for the new baselines: accuracy per domain and question type, tokens and cost per model and system.
usage: python3 scripts/new_baselines_summary.py [--types]
Cost uses the locked providers' OpenRouter list prices (all input at the full price). GraphRAG's streamed answers
report output tokens without reasoning tokens (SPEC sec. 11), so billed output there = output + reasoning."""
import collections
import glob
import json
import sys
from pathlib import Path

RUNS = str(Path(__file__).resolve().parents[1] / "runs")
MODELS = {"or-gpt-oss-20b": (0.03, 0.13), "or-qwen3.6-27b": (0.45, 2.70), "or-gemma-4-31b-think": (0.14, 0.40)}
SYSTEMS = ["react_r", "react_c", "recode", "graphrag"]
DOMAINS = ["mfg", "itops", "fin"]


def billed_out(u, system):
    return u.get("output_tokens", 0) + (u.get("reasoning_tokens", 0) if system == "graphrag" else 0)


def main(types: bool):
    print(f"{'model':22} {'system':9} " + " ".join(f"{d:>13}" for d in DOMAINS)
          + f" {'err':>4} {'q in M':>7} {'q out M':>7} {'setup in M':>10} {'setup out M':>11} {'cost $':>7}")
    for m, (pi, po) in MODELS.items():
        for s in SYSTEMS:
            cells, err, q, su = [], 0, collections.Counter(), collections.Counter()
            by_type = collections.defaultdict(lambda: [0, 0])
            for d in DOMAINS:
                n = c = 0
                for out in sorted(glob.glob(f"{RUNS}/{d}_d0*/systems/{s}__{m}")):
                    if not glob.glob(f"{out}/predictions.jsonl"):   # not started yet
                        continue
                    for line in open(f"{out}/predictions.jsonl"):
                        r = json.loads(line)
                        if "error" in r:
                            err += 1
                            continue
                        ok = bool(r["score"].get("question_correct"))
                        n, c = n + 1, c + ok
                        t = by_type[(d, r["question_type"])]
                        t[0], t[1] = t[0] + 1, t[1] + ok
                        q["in"] += r["usage"].get("input_tokens", 0)
                        q["out"] += billed_out(r["usage"], s)
                    u = json.load(open(f"{out}/setup.json"))["usage"]
                    su["in"] += u.get("input_tokens", 0)
                    su["out"] += u.get("output_tokens", 0)
                cells.append(f"{100 * c / n:5.1f}% ({n:3d})" if n else f"{'-':>13}")
            cost = ((q["in"] + su["in"]) * pi + (q["out"] + su["out"]) * po) / 1e6
            print(f"{m:22} {s:9} " + " ".join(f"{x:>13}" for x in cells)
                  + f" {err:4d} {q['in'] / 1e6:7.1f} {q['out'] / 1e6:7.2f} {su['in'] / 1e6:10.1f}"
                  f" {su['out'] / 1e6:11.2f} {cost:7.2f}")
            if types:
                for (d, t), (n, c) in sorted(by_type.items()):
                    print(f"{'':32} {d:6} {t:28} {100 * c / n:5.1f}% ({n})")


if __name__ == "__main__":
    main("--types" in sys.argv)
