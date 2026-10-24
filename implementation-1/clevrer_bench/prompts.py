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


# Other domains (run manifests with a "domain" field). Same JSON contract as above, without the CLEVRER wording.
GENERIC_ANSWER_INSTRUCTIONS = """You answer questions about a document using the provided document. The document \
is divided into chapters, and the first line of each question names the chapter it is about.

Reply with ONLY a JSON object and nothing else.
- Open-ended question: {"answer": "<one word>"}. Use lowercase; give numbers and counts as digits (e.g. "2"), \
yes/no questions as "yes" or "no", and names or identifiers as a single word as printed.
- Multiple-choice question: {"choices": {"<choice_id>": true|false, ...}} with one entry per choice. \
Mark a choice true if the statement is a correct answer to the question. Zero, one, or several choices \
may be true.

Question semantics: "why" or "responsible for" asks what an outcome depended on: it would not have happened \
without it (causal). Questions about times after the chapter's records end ask what will happen next. \
"Suppose ... had ..., with everything else as recorded" asks what would have happened in the same chapter with \
only that change."""

# Finance (TAT-HQA): answers are numbers with a scale, text spans or lists (domains/finance/ANSWER_CONTRACT.md).
FINANCE_ANSWER_INSTRUCTIONS = """You answer questions about excerpts of company annual reports using the provided \
document. Each excerpt is a chapter titled "Report R-<NNN>" with a Text section and a Table section. Each question \
names the report it is about.

Reply with ONLY a JSON object and nothing else:
{"answer": <answer>, "scale": "<none|thousand|million|billion|percent>"}

- A number: give it as a JSON number or string, rounded to two decimal places (e.g. 8325, -12.5, 33.33). \
"scale" is the unit the number is in: "percent" if it is a percentage (12.5 means 12.5%), "thousand", \
"million" or "billion" if it is an amount in that scale (a table "in thousands" showing 1,910 gives \
{"answer": 1910, "scale": "thousand"}), otherwise "none".
- Text: copy the words as printed in the report, e.g. {"answer": "Net revenue", "scale": "none"}.
- Several items (the question asks for more than one value, year or name): a JSON list with each item copied \
exactly as printed in the report, e.g. {"answer": ["$14,740", "$1,910"], "scale": "thousand"}.

Question semantics: "What would X be if Y ..." asks for X recomputed with the stated change to Y and everything \
else as reported."""


def answer_instructions(domain: str | None = None) -> str:
    """The answer contract for a run's domain (manifest.json "domain"; None = CLEVRER)."""
    if domain is None:
        return ANSWER_INSTRUCTIONS
    return FINANCE_ANSWER_INSTRUCTIONS if domain == "finance" else GENERIC_ANSWER_INSTRUCTIONS


def build_question_prompt(item: QAItem, domain: str | None = None) -> str:
    """First line: the question's chapter ("Video <n>" for CLEVRER, the scope title otherwise)."""
    head = f"Video {item.scene_index}" if domain is None else str(item.scene_index)
    lines = [head, f"Question: {item.question}"]
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


def parse_prediction(item: QAItem, raw: str, domain: str | None = None) -> dict:
    """Returns {"answer": str} or {"choices": {int: bool}}; missing/invalid -> {"parse_error": ...}.
    Finance keeps the answer as given (number, text or list) and its "scale"; scoring normalises them."""
    obj = _last_json_object(raw or "")
    if obj is None:
        return {"parse_error": "no JSON object"}
    if domain == "finance":
        if "answer" not in obj:
            return {"parse_error": "missing 'answer'"}
        return {"answer": obj["answer"], "scale": obj.get("scale")}
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
