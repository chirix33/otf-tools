"""Guard: the method package `otf` must stay document-agnostic. No benchmark-specific vocabulary may
appear in its source. The same applies to the newly authored instructions of the Tier B baselines
(clevrer_bench/systems/baseline_prompts.py); the shared answer contract, document content and question text are
inserted at run time and are not scanned. Run: python -m pytest tests  (or python tests/test_no_benchmark_words.py)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "otf"
BASELINE_PROMPTS = ROOT / "clevrer_bench" / "systems" / "baseline_prompts.py"
BANNED = ["clevrer", "video", "frame", "collision", "collide", "sphere", "cube", "cylinder", "rubber", "metal",
          "physics", "velocity", "friction", "gray", "red", "blue", "green", "brown", "purple", "cyan", "yellow"]


def _hits(files):
    hits = []
    for f in files:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for w in BANNED:
                if re.search(rf"\b{w}(s|es|d|ed|ing|ion|ions|er|ers)?\b", line, flags=re.I):
                    hits.append(f"{f.name}:{i}: '{w}' in: {line.strip()[:100]}")
    return hits


def test_no_benchmark_words():
    hits = _hits(PKG.rglob("*.py"))
    assert not hits, "benchmark words in otf/:\n" + "\n".join(hits)


def test_no_benchmark_words_in_baseline_prompts():
    hits = _hits([BASELINE_PROMPTS])
    assert not hits, "benchmark words in baseline prompts:\n" + "\n".join(hits)


if __name__ == "__main__":
    test_no_benchmark_words()
    test_no_benchmark_words_in_baseline_prompts()
    print("ok: no benchmark words in otf/ or the baseline prompts")
