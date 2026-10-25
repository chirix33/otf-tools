"""Re-check stored OTF process models with the current forecast check (used to validate checker bug fixes).

    python scripts/recheck_models.py [glob over runs/, default */systems/otf*/work/otf_model.json]
Prints the stored verdict next to the new one; the hand-written oracle is checked on pilot20 too.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from otf.toolgen import check_model  # noqa: E402

pattern = sys.argv[1] if len(sys.argv) > 1 else "*/systems/otf*/work/otf_model.json"
oracle = (ROOT / "oracle" / "oracle_model.py").read_text(encoding="utf-8")
nav_p = ROOT / "runs" / "pilot20" / "systems" / "otf_oracle__or-gpt-oss-20b" / "work" / "navmap.json"
rep = check_model(oracle, json.loads(nav_p.read_text(encoding="utf-8")), nav_p)
print(f"oracle pilot20: passed={rep['passed']} F1={rep['mean_f1']}", flush=True)
for p in sorted((ROOT / "runs").glob(pattern)):
    m = json.loads(p.read_text(encoding="utf-8"))["model"]
    if not m.get("passed") or m.get("hand_written"):
        continue
    nav_p = p.with_name("navmap.json")
    rep = check_model(m["code"], json.loads(nav_p.read_text(encoding="utf-8")), nav_p)
    print(f"{p.relative_to(ROOT / 'runs').parent.parent}: stored F1={m.get('mean_f1')} -> now passed={rep['passed']} "
          f"F1={rep['mean_f1']}" + (f" error={rep['error'][:150]}" if rep.get("error") else ""), flush=True)
