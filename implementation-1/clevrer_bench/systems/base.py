"""The interface every QA system implements. Plug your own system in by subclassing
`QASystem` and passing `--system your_module:YourClass` to run.py."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..data import QAItem


@dataclass
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0   # subset of input_tokens served from the provider cache
    output_tokens: int = 0
    reasoning_tokens: int = 0      # subset of output_tokens
    llm_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, o: "Usage") -> "Usage":
        return Usage(*(getattr(self, f) + getattr(o, f) for f in
                       ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "llm_calls")))

    def to_dict(self) -> dict:
        return {**asdict(self), "total_tokens": self.total_tokens}


@dataclass
class Document:
    """Everything a system may use to prepare. Systems choose which parts to consume."""
    pdf_path: Path
    manifest: dict          # video -> page ranges (see render.RenderedDoc.manifest)
    work_dir: Path          # scratch/cache dir owned by the system


@dataclass
class Prediction:
    raw_text: str                                   # the system's raw final output
    usage: Usage
    latency_s: float = 0.0
    trace: Optional[Any] = None                     # optional: retrieved pages, tool calls, ...


@dataclass
class SetupResult:
    usage: Usage = field(default_factory=Usage)     # one-time cost (e.g. building an index)
    latency_s: float = 0.0
    info: dict = field(default_factory=dict)


class QASystem(ABC):
    name: str = "system"

    def __init__(self, model: str, reasoning_effort: Optional[str] = None, **kwargs):
        from ..llm import get_model
        self.model = model                  # registry alias (configs/models.json)
        self.spec = get_model(model)        # where it is served + frozen sampling settings
        self.reasoning_effort = reasoning_effort or self.spec.reasoning_effort

    @abstractmethod
    def setup(self, doc: Document) -> SetupResult:
        """One-time preparation over the document (index build, upload, ...)."""

    @abstractmethod
    def answer(self, item: QAItem, instructions: str, prompt: str) -> Prediction:
        """Answer one question. `instructions` is the shared answer contract (system prompt,
        prompts.ANSWER_INSTRUCTIONS) and `prompt` the shared question prompt
        (prompts.build_question_prompt). The harness passes a stripped item (data.QAItem.stripped):
        no gold labels and no question type, so a system must infer the type itself.
        Must be thread-safe if run with --workers > 1."""
