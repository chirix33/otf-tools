"""Shared prompt + answer contract, identical for every system so scores are comparable."""
from __future__ import annotations

import json
import re
from typing import Optional

from .data import QAItem

ANSWER_INSTRUCTIONS = """You answer questions about CLEVRER physics videos using the provided document, which \
describes each video (objects, events, and a motion log). Each question names the video it is about.

Reply with ONLY a JSON object and nothing else.
- Open-ended question: {"answer": "<one word>"}. Use lowercase; give counts as digits (e.g. "2"), \
existence questions as "yes" or "no", and colors/materials/shapes as a single word \
(e.g. "red", "metal", "cylinder").
- Multiple-choice question: {"choices": {"<choice_id>": true|false, ...}} with one entry per choice. \
Mark a choice true if the statement is a correct answer to the question. Zero, one, or several choices \
may be true.

Question semantics: "responsible for" an event means the event would not have happened without it (causal). \
"What will happen next" asks about events after the video ends. "If X is removed" / "Without X" asks what \
would happen in the same video with that object absent from the start."""


def build_question_prompt(item: QAItem) -> str:
    lines = [f"Video {item.scene_index}", f"Question: {item.question}"]
    if item.is_mc:
        lines.append("Choices:")
        lines += [f"  {c['choice_id']}: {c['choice']}" for c in item.choices]
        lines.append("Answer with the multiple-choice JSON format.")
    else:
        lines.append("Answer with the open-ended JSON format.")
    return "\n".join(lines)


_NUM = {"zero": "0", "none": "0", "one": "1", "two": "2", "three": "3", "four": "4",
        "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"}


def _last_json_object(text: str) -> Optional[dict]:
    """The last top-level JSON object in `text` (nested objects are not considered on their own)."""
    text = re.sub(r"```(?:json)?", "", text)
    decoder = json.JSONDecoder()
    found, i = None, 0
    while (i := text.find("{", i)) != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(obj, dict):
            found = obj
        i = end
    return found


def normalize_word(s: str) -> str:
    s = str(s).strip().lower().strip(".!,;:'\" ")
    return _NUM.get(s, s)


def parse_prediction(item: QAItem, raw: str) -> dict:
    """Returns {"answer": str} or {"choices": {int: bool}}; missing/invalid -> {"parse_error": ...}."""
    obj = _last_json_object(raw or "")
    if obj is None:
        return {"parse_error": "no JSON object"}
    if item.is_mc:
        ch = obj.get("choices")
        if not isinstance(ch, dict):
            return {"parse_error": "missing 'choices'"}
        out = {}
        for k, v in ch.items():
            try:
                cid = int(k)
            except ValueError:
                continue
            if isinstance(v, str):
                v = v.strip().lower() in ("true", "yes", "correct")
            out[cid] = bool(v)
        return {"choices": out}
    if "answer" not in obj:
        return {"parse_error": "missing 'answer'"}
    return {"answer": normalize_word(obj["answer"])}
