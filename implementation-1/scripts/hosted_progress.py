"""Answered questions per hosted model and system folder, appended as one snapshot line to
runs/logs/hosted__progress.jsonl; with two or more snapshots, prints the rate since the previous one."""
import json
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
counts = defaultdict(int)
for p in (ROOT / "runs").glob("*/systems/*__or-*/predictions.jsonl"):
    folder, model = p.parent.name.split("__")
    n = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            n += "error" not in json.loads(line)
        except ValueError:
            pass
    counts[f"{model}|{folder}"] += n
snap = {"t": time.time(), "counts": dict(counts)}
log = ROOT / "runs" / "logs" / "hosted__progress.jsonl"
prev = json.loads(log.read_text().splitlines()[-1]) if log.exists() and log.read_text().strip() else None
with log.open("a") as f:
    f.write(json.dumps(snap) + "\n")
by_model = defaultdict(int)
for k, v in counts.items():
    by_model[k.split("|")[0]] += v
for k in sorted(counts):
    rate = ""
    if prev:
        rate = f"  {(v := counts[k] - prev['counts'].get(k, 0)) / ((snap['t'] - prev['t']) / 60):6.1f}/min"
    print(f"{k:45s} {counts[k]:6d}{rate}")
if prev:
    mins = (snap["t"] - prev["t"]) / 60
    for m, v in sorted(by_model.items()):
        pv = sum(c for k, c in prev["counts"].items() if k.startswith(m + "|"))
        print(f"TOTAL {m:30s} {v:6d}  {(v - pv) / mins:6.1f}/min over {mins:.0f} min")
