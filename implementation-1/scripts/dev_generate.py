"""Dev helper: generate + check the OTF process model for one run's document and print the log.
    python scripts/dev_generate.py pilot20 gpt-oss-20b
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clevrer_bench.systems import Document, load_system  # noqa: E402

run, model = sys.argv[1], sys.argv[2]
work = Path("runs") / run / "systems" / f"otf_dev__{model}" / "work"
work.mkdir(parents=True, exist_ok=True)
for f in ("otf_model.json", "otf_log.txt"):
    (work / f).unlink(missing_ok=True)
s = load_system("otf", model)
t = time.time()
r = s.setup(Document(Path("runs") / run / "document.pdf", {}, work))
print("setup", r.info, r.usage.to_dict(), round(time.time() - t), "s")
print((work / "otf_log.txt").read_text(encoding="utf-8")[-4000:])
