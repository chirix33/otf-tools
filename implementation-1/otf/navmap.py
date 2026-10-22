"""Navigation Map: a deterministic, LLM-free coordinate system over a PDF.

Every leaf of the PDF outline becomes a node with its title, parent, page range, and content in one of
three kinds:
  table: a header line of short alphabetic words followed by rows; each row's words are assigned to the
         header column whose left edge they fall under (left-aligned text tables, also across pages
         when the header repeats);
  list:  one entry per line (enumerations, logs, item lists);
  text:  free prose.
Front matter before the first outline entry is kept as `intro_text` (documents usually explain their own
data there). Without an outline the whole document is a single text node.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

LINE_TOL = 2.0          # points: words whose tops differ by less than this are on the same line
NUMERIC = re.compile(r"^[-+]?\d+(\.\d+)?$")


def _lines(pdf_path: Path) -> list[dict]:
    """All text lines in reading order: {page, top, text, words: [{x0, text}]}."""
    import pdfplumber
    out = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            words = sorted(page.extract_words(keep_blank_chars=False, use_text_flow=False),
                           key=lambda w: (round(w["top"]), w["x0"]))
            cur: list[dict] = []
            for w in words:
                if cur and abs(w["top"] - cur[0]["top"]) > LINE_TOL:
                    out.append(_mk_line(pno, cur))
                    cur = []
                cur.append(w)
            if cur:
                out.append(_mk_line(pno, cur))
    return out


def _mk_line(pno: int, words: list[dict]) -> dict:
    words = sorted(words, key=lambda w: w["x0"])
    return {"page": pno, "top": words[0]["top"], "text": " ".join(w["text"] for w in words),
            "words": [{"x0": w["x0"], "text": w["text"]} for w in words]}


def _outline(pdf_path: Path) -> list[dict]:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(pdf_path))
    out = []
    for b in pdf.get_toc():
        d = b.get_dest()
        out.append({"title": b.get_title(), "level": b.level, "page": (d.get_index() + 1) if d else None})
    return out


def _is_header(line: dict) -> bool:
    toks = [w["text"] for w in line["words"]]
    return len(toks) >= 3 and all(t.isalpha() and len(t) <= 16 for t in toks)


def _row_cells(line: dict, cols: list[dict]) -> list[str] | None:
    """Assign a line's words to header columns by left edge; None if it does not look like a row."""
    edges = [c["x0"] for c in cols]
    cells = [[] for _ in cols]
    for w in line["words"]:
        k = max((i for i, e in enumerate(edges) if w["x0"] >= e - 3.0), default=None)
        if k is None:
            return None
        cells[k].append(w["text"])
    filled = sum(bool(c) for c in cells)
    if filled < max(2, len(cols) - 1):
        return None
    return [" ".join(c) for c in cells]


def _parse_block(lines: list[dict]) -> dict:
    """Decide the kind of a node's content lines and parse it."""
    i = next((k for k, l in enumerate(lines) if _is_header(l)), None)
    if i is not None:
        header = lines[i]
        cols = [{"name": w["text"], "x0": w["x0"]} for w in header["words"]]
        names = [c["name"] for c in cols]
        rows, other = [], lines[:i]
        for l in lines[i + 1:]:
            if [w["text"] for w in l["words"]] == names:          # header repeated on a new page
                cols = [{"name": w["text"], "x0": w["x0"]} for w in l["words"]]
                continue
            cells = _row_cells(l, cols)
            if cells is None:
                other.append(l)
            else:
                rows.append(cells)
        if len(rows) >= 2:
            return {"kind": "table", "table": {"columns": names, "rows": rows},
                    "text": "\n".join(l["text"] for l in other)}
    texts = [l["text"] for l in lines]
    short = sum(len(t) < 160 for t in texts)
    kind = "list" if len(texts) >= 2 and short / len(texts) > 0.8 and \
        len({t.split(" ")[0] for t in texts}) < len(texts) else "text"
    if kind == "text" and len(texts) >= 3 and all(len(t) < 160 for t in texts):
        kind = "list"
    return {"kind": kind, "lines": texts} if kind == "list" else {"kind": "text", "text": "\n".join(texts)}


def build_map(pdf_path: Path) -> dict:
    lines = _lines(pdf_path)
    outline = _outline(pdf_path)
    doc_id = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]
    # locate each outline title as a line, in order, starting at its destination page
    marks, cursor = [], 0
    for o in outline:
        for k in range(cursor, len(lines)):
            if lines[k]["text"].strip() == o["title"].strip() and (o["page"] is None or lines[k]["page"] >= o["page"]):
                marks.append((k, o))
                cursor = k + 1
                break
    nodes, stack = [], []
    intro_end = marks[0][0] if marks else len(lines)
    intro = "\n".join(l["text"] for l in lines[:intro_end])
    for idx, (k, o) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(lines)
        stack = stack[:o["level"]]
        parent = stack[-1] if stack else None
        node_id = f"n{idx:04d}"
        body = lines[k + 1:end]
        node = {"node_id": node_id, "title": o["title"], "level": o["level"], "parent_id": parent,
                "file": pdf_path.name, "pages": [lines[k]["page"], (body[-1]["page"] if body else lines[k]["page"])]}
        node.update(_parse_block(body) if body else {"kind": "text", "text": ""})
        nodes.append(node)
        stack.append(node_id)
    if not marks:
        nodes = [{"node_id": "n0000", "title": pdf_path.stem, "level": 0, "parent_id": None,
                  "file": pdf_path.name, "pages": [1, lines[-1]["page"] if lines else 1], "kind": "text",
                  "text": intro}]
        intro = ""
    for n in nodes:
        n["children"] = [m["node_id"] for m in nodes if m["parent_id"] == n["node_id"]]
    return {"document_id": doc_id, "source_files": [pdf_path.name], "intro_text": intro, "nodes": nodes}


def schema_summary(nav: dict, max_examples: int = 2) -> str:
    """What the tool generator sees: structure, node kinds, column names and a few example rows/lines,
    for distinct node 'shapes' (title patterns with digits normalised), never the full content."""
    def pattern(title: str) -> str:
        return re.sub(r"\d+", "#", title)

    titles = {n["node_id"]: n["title"] for n in nav["nodes"]}
    seen, out = set(), []
    for n in nav["nodes"]:
        shape = (pattern(n["title"]), n["kind"], tuple(n.get("table", {}).get("columns", [])))
        if shape in seen:
            continue
        seen.add(shape)
        parent = pattern(titles[n["parent_id"]]) if n["parent_id"] else "-"
        desc = f"- node kind={n['kind']} title pattern '{shape[0]}' (e.g. '{n['title']}'), parent pattern '{parent}'"
        if n["kind"] == "table":
            desc += f"\n    columns: {n['table']['columns']}\n    example rows: {n['table']['rows'][:max_examples + 1]}"
        elif n["kind"] == "list":
            desc += f"\n    example lines: {n['lines'][:max_examples + 2]}"
        else:
            desc += f"\n    text starts: {n['text'][:200]!r}"
        out.append(desc)
    count = len(nav["nodes"])
    return f"{count} nodes. Distinct node shapes:\n" + "\n".join(out)


def save_map(nav: dict, path: Path) -> None:
    path.write_text(json.dumps(nav))
