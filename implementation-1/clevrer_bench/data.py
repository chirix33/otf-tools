"""Load CLEVRER validation questions + annotations and sample a benchmark subset."""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

MC_TYPES = ("explanatory", "predictive", "counterfactual")
QUESTION_TYPES = ("descriptive",) + MC_TYPES
HIDDEN_OPEN, HIDDEN_MC = "open_ended", "multiple_choice"  # what systems see instead of the type


@dataclass
class QAItem:
    """One benchmark question, already bound to its video."""
    uid: str                      # "<scene_index>-<question_id>", globally unique
    scene_index: int
    question_id: int
    question_type: str            # descriptive | explanatory | predictive | counterfactual
    question_subtype: Optional[str]
    question: str                 # original CLEVRER question text
    choices: list[dict] = field(default_factory=list)  # [{"choice_id", "choice"}] (no labels)
    gold_answer: Optional[str] = None                   # descriptive only
    gold_choices: dict[int, bool] = field(default_factory=dict)  # MC only: choice_id -> correct?

    @property
    def is_mc(self) -> bool:
        return self.question_type in MC_TYPES or self.question_type == HIDDEN_MC

    def stripped(self) -> "QAItem":
        """The copy a system receives: no gold labels, and the question type reduced to
        open-ended vs. multiple-choice (the answer format, which the prompt states anyway)."""
        return QAItem(uid=self.uid, scene_index=self.scene_index, question_id=self.question_id,
                      question_type=HIDDEN_MC if self.is_mc else HIDDEN_OPEN, question_subtype=None,
                      question=self.question, choices=[dict(c) for c in self.choices])

    def public(self) -> dict:
        """What a system is allowed to see (no gold labels)."""
        return {"uid": self.uid, "video": self.scene_index, "question_type": self.question_type,
                "question": self.question,
                "choices": [{"choice_id": c["choice_id"], "choice": c["choice"]} for c in self.choices]}


def annotation_path(raw_dir: Path, scene_index: int) -> Path:
    lo = scene_index // 1000 * 1000
    return raw_dir / "annotations" / f"annotation_{lo}-{lo + 1000}" / f"annotation_{scene_index}.json"


def load_annotation(raw_dir: Path, scene_index: int) -> dict:
    return json.loads(annotation_path(raw_dir, scene_index).read_text())


def sample_videos(raw_dir: Path, n_videos: int, seed: int) -> list[dict]:
    """Deterministically sample `n_videos` entries from validation.json."""
    entries = json.loads((raw_dir / "validation.json").read_text())
    rng = random.Random(seed)
    picked = rng.sample(entries, n_videos)
    return sorted(picked, key=lambda e: e["scene_index"])


def to_items(entries: list[dict]) -> list[QAItem]:
    items = []
    for e in entries:
        for q in e["questions"]:
            item = QAItem(
                uid=f"{e['scene_index']}-{q['question_id']}",
                scene_index=e["scene_index"],
                question_id=q["question_id"],
                question_type=q["question_type"],
                question_subtype=q.get("question_subtype"),
                question=q["question"],
            )
            if item.is_mc:
                item.choices = [{"choice_id": c["choice_id"], "choice": c["choice"]} for c in q["choices"]]
                item.gold_choices = {c["choice_id"]: c["answer"] == "correct" for c in q["choices"]}
            else:
                item.gold_answer = str(q["answer"]).lower()
            items.append(item)
    return items


def save_items(items: list[QAItem], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for it in items:
            d = it.__dict__.copy()
            d["gold_choices"] = {str(k): v for k, v in it.gold_choices.items()}
            f.write(json.dumps(d) + "\n")


def load_items(path: Path) -> list[QAItem]:
    items = []
    for line in path.read_text().splitlines():
        d = json.loads(line)
        d["gold_choices"] = {int(k): v for k, v in d["gold_choices"].items()}
        items.append(QAItem(**d))
    return items
