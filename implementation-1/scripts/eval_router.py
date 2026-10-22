"""Router accuracy on the pilot20 DEV set only (router tuning must never look at E1/E2).

    python scripts/eval_router.py gemma-4-31b-think            # current prompt
    python scripts/eval_router.py gemma-4-31b-think candidate  # prompt from otf/prompts.py ROUTER_CANDIDATE
"""
import collections
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clevrer_bench.data import load_items  # noqa: E402
from clevrer_bench.prompts import build_question_prompt  # noqa: E402
from clevrer_bench.systems import load_system  # noqa: E402
from otf import prompts  # noqa: E402
from otf.engine import _json  # noqa: E402

model = sys.argv[1]
variant = sys.argv[2] if len(sys.argv) > 2 else "current"
router = prompts.ROUTER if variant == "current" else getattr(prompts, "ROUTER_" + variant.upper())
system = load_system("otf", model)
items = load_items(ROOT / "runs" / "pilot20" / "items.jsonl")


def route(it):
    t = _json(system._llm([{"role": "system", "content": router},
                           {"role": "user", "content": build_question_prompt(it.stripped())}]))
    qt = str(t.get("type", "")).strip().lower()
    return it.question_type, (qt if qt in prompts.QUESTION_TYPES else "descriptive")


with ThreadPoolExecutor(8) as ex:
    res = list(ex.map(route, items))
by = collections.defaultdict(lambda: [0, 0])
for gold, got in res:
    by[gold][0] += gold == got
    by[gold][1] += 1
conf = collections.Counter((g, p) for g, p in res if g != p)
acc = sum(g == p for g, p in res)
print(json.dumps({"model": model, "variant": variant, "accuracy": f"{acc}/{len(res)}",
                  "by_type": {k: f"{v[0]}/{v[1]}" for k, v in by.items()},
                  "confusions": {f"{g}->{p}": n for (g, p), n in conf.most_common()}}))
