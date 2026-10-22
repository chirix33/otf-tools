"""Guard: the method package `otf` must stay document-agnostic. No benchmark-specific vocabulary may
appear in its source. Run: python -m pytest tests  (or python tests/test_no_benchmark_words.py)."""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "otf"
BANNED = ["clevrer", "video", "frame", "collision", "collide", "sphere", "cube", "cylinder", "rubber", "metal",
          "physics", "velocity", "friction", "gray", "red", "blue", "green", "brown", "purple", "cyan", "yellow"]


def test_no_benchmark_words():
    hits = []
    for f in PKG.rglob("*.py"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for w in BANNED:
                if re.search(rf"\b{w}(s|es|d|ed|ing|ion|ions|er|ers)?\b", line, flags=re.I):
                    hits.append(f"{f.name}:{i}: '{w}' in: {line.strip()[:100]}")
    assert not hits, "benchmark words in otf/:\n" + "\n".join(hits)


if __name__ == "__main__":
    test_no_benchmark_words()
    print("ok: no benchmark words in otf/")
