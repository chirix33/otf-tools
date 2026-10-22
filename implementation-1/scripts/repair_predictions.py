"""After a crash: drop torn (unparseable) lines from every runs/**/predictions.jsonl. The questions they held
are simply answered again on the next run (the runner resumes by question id). Prints what it changed.

    python scripts/repair_predictions.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fixed = 0
for f in (ROOT / "runs").rglob("predictions.jsonl"):
    lines = f.read_bytes().split(b"\n")
    good, torn = [], 0
    for line in lines:
        if not line.strip():
            continue
        try:
            json.loads(line)
            good.append(line)
        except ValueError:
            torn += 1
    if torn:
        f.write_bytes(b"\n".join(good) + b"\n")
        fixed += torn
        print(f"dropped {torn} torn line(s) from {f.relative_to(ROOT)}")
print(f"repair done: {fixed} torn line(s) dropped")
