"""Gate G1 (SPEC sec. 5, OTF v3): the Navigation Map built by the current `otf/navmap.py` must be byte-identical
to the map each existing CLEVRER run used, so baselines that share the map (ReAct-C, ReCode) and the v2 results
stay comparable.

    python scripts/check_navmap_identity.py            # pilot20, e1_d01-d15, e2_d01
Prints one line per document and exits non-zero if any map differs.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from otf.navmap import build_map  # noqa: E402

runs = ["pilot20"] + [f"e1_d{i:02d}" for i in range(1, 16)] + ["e2_d01"]
bad = 0
for name in sys.argv[1:] or runs:
    d = ROOT / "runs" / name
    ref = next(iter(sorted(d.glob("systems/otf*__*/work/navmap.json"))), None)
    if ref is None:
        print(f"{name}: no reference map, skipped")
        continue
    new = json.dumps(build_map(d / "document.pdf"))
    same = new == ref.read_text()
    bad += not same
    print(f"{name}: {'identical' if same else 'DIFFERENT'} (reference {ref.relative_to(ROOT)})")
print("G1 passed" if not bad else f"G1 FAILED: {bad} maps differ")
sys.exit(1 if bad else 0)
