"""Navigation Map: a deterministic, LLM-free coordinate system over a PDF.

Every leaf of the PDF outline becomes a node with its title, parent, page range, and content in one of
three kinds:
  table: a ruled table (drawn grid lines; cells as the grid gives them, the first row as column names,
         continued across pages), or else a header line of short alphabetic words followed by rows, at
         least half of them with a number; each row's words are assigned to the header column whose left
         edge they fall under (left-aligned text tables, also across pages when the header repeats);
  list:  one entry per line (enumerations, logs, item lists);
  text:  free prose.
A leaf holding ruled tables and its own text lines (captions) is split: each ruled table, with its
continuations, becomes a sibling node titled "<leaf title>: <the line just before it>", and the leaf keeps the
other lines (post-freeze bug fix 10: before, only the first table was kept and later ones fell into unread text).
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


def _ruled_tables(page) -> list[dict]:
    """Tables drawn with grid lines on a page: [{bbox, rows}]. Pages without vertical rules have none."""
    if sum(e["orientation"] == "v" for e in page.edges) < 2:
        return []
    out = []
    for t in page.find_tables():
        rows = [[re.sub(r"\s+", " ", c or "").strip() for c in r] for r in t.extract()]
        rows = [r for r in rows if any(r)]
        if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
            out.append({"bbox": t.bbox, "rows": rows})
    return out


def _lines(pdf_path: Path) -> list[dict]:
    """All text lines in reading order: {page, top, text, words: [{x0, text}]}; a line inside a ruled
    table also carries `tbl` (that table's cell rows, shared by all its lines)."""
    import pdfplumber
    out = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            tables = _ruled_tables(page)
            words = sorted(page.extract_words(keep_blank_chars=False, use_text_flow=False),
                           key=lambda w: (round(w["top"]), w["x0"]))
            cur: list[dict] = []
            first = len(out)
            for w in words:
                if cur and abs(w["top"] - cur[0]["top"]) > LINE_TOL:
                    out.append(_mk_line(pno, cur))
                    cur = []
                cur.append(w)
            if cur:
                out.append(_mk_line(pno, cur))
            for line in out[first:]:
                for t in tables:
                    x0, top, x1, bottom = t["bbox"]
                    if top - 1 <= line["top"] <= bottom + 1 and line["words"][0]["x0"] >= x0 - 1:
                        line["tbl"] = t
                        break
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


def _ruled_block(lines: list[dict]) -> dict | None:
    """A node whose lines lie in ruled tables: the first table's first row names the columns; later tables
    with as many columns continue it (a header row repeated on a new page is dropped). Other lines are text."""
    tables, other = [], []
    for l in lines:
        t = l.get("tbl")
        if t is None:
            other.append(l)
        elif not tables or tables[-1] is not t:
            tables.append(t)
    if not tables:
        return None
    first = tables[0]["rows"]
    header, n_head = list(first[0]), 1
    width = len(header)
    # a header spread over several rows ("2019 | 2019" over "Capital | Depreciation"): while the names so far
    # repeat or have gaps and the next row holds only words or years, merge it into the column names
    while n_head < min(3, len(first) - 1) and len(first[n_head]) == width and _header_ambiguous(header) \
            and all(_header_like(c) for c in first[n_head]):
        header = [" ".join(p for p in (a, b) if p) for a, b in zip(header, first[n_head])]
        n_head += 1
    cols, seen = [], {}
    for i, c in enumerate(header):
        name = c or f"col{i}"
        seen[name] = seen.get(name, 0) + 1
        cols.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    rows = []
    for k, t in enumerate(tables):
        if len(t["rows"][0]) != width:
            other += [l for l in lines if l.get("tbl") is t]
            continue
        rows += [r for j, r in enumerate(t["rows"])
                 if not ((k == 0 and j < n_head) or (k > 0 and j == 0 and r == first[0]))]
    return {"kind": "table", "table": {"columns": cols, "rows": rows}, "text": "\n".join(l["text"] for l in other)}


def _header_ambiguous(names: list[str]) -> bool:
    """Repeated names, or gaps after the first column (which is often an unlabelled row-label column)."""
    named = [n for n in names if n]
    return len(set(named)) < len(named) or any(not n for n in names[1:])


def _header_like(cell: str) -> bool:
    """Empty, words, or a year: no amounts."""
    return not re.search(r"\d", re.sub(r"\b(19|20)\d\d\b", "", cell or ""))


def _parse_block(lines: list[dict]) -> dict:
    """Decide the kind of a node's content lines and parse it."""
    ruled = _ruled_block(lines)
    if ruled is not None:
        return ruled
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
        numeric = sum(any(NUMERIC.match(c) for c in r) for r in rows)
        if len(rows) >= 2 and 2 * numeric >= len(rows):          # prose split at word gaps is not a table
            return {"kind": "table", "table": {"columns": names, "rows": rows},
                    "text": "\n".join(l["text"] for l in other)}
    texts = [l["text"] for l in lines]
    short = sum(len(t) < 160 for t in texts)
    kind = "list" if len(texts) >= 2 and short / len(texts) > 0.8 and \
        len({t.split(" ")[0] for t in texts}) < len(texts) else "text"
    if kind == "text" and len(texts) >= 3 and all(len(t) < 160 for t in texts):
        kind = "list"
    return {"kind": kind, "lines": texts} if kind == "list" else {"kind": "text", "text": "\n".join(texts)}


def _captioned_tables(body: list[dict]) -> list[tuple[str, list[dict]]] | None:
    """For a leaf with ruled tables and text lines of its own: [(caption, table lines)] per table (a table
    continues while no text line intervenes and the width stays the same), else None."""
    if not any(l.get("tbl") for l in body) or all(l.get("tbl") for l in body):
        return None
    groups, last_text, prev = [], None, None
    for l in body:
        t = l.get("tbl")
        if t is None:
            last_text, prev = l["text"], None
            continue
        width = len(t["rows"][0])
        if prev is not None and (prev is t or len(prev["rows"][0]) == width):
            groups[-1][1].append(l)
        else:
            groups.append((last_text, [l]))
        prev = t
    return groups


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
        node_id = f"n{len(nodes):04d}"
        body = lines[k + 1:end]
        node = {"node_id": node_id, "title": o["title"], "level": o["level"], "parent_id": parent,
                "file": pdf_path.name, "pages": [lines[k]["page"], (body[-1]["page"] if body else lines[k]["page"])]}
        split = _captioned_tables(body) if idx + 1 < len(marks) and marks[idx + 1][1]["level"] <= o["level"] or             idx + 1 == len(marks) else None                        # leaves only
        if split:
            node.update(_parse_block([l for l in body if not l.get("tbl")]))
        else:
            node.update(_parse_block(body) if body else {"kind": "text", "text": ""})
        nodes.append(node)
        stack.append(node_id)
        for j, (caption, tlines) in enumerate(split or [], start=1):
            name = (caption or "").strip().rstrip(":").strip() or f"table {j}"
            tnode = {"node_id": f"n{len(nodes):04d}", "title": f"{o['title']}: {name}", "level": o["level"],
                     "parent_id": parent, "file": pdf_path.name, "pages": [tlines[0]["page"], tlines[-1]["page"]]}
            tnode.update(_ruled_block(tlines))
            nodes.append(tnode)
    if not marks:
        nodes = [{"node_id": "n0000", "title": pdf_path.stem, "level": 0, "parent_id": None,
                  "file": pdf_path.name, "pages": [1, lines[-1]["page"] if lines else 1], "kind": "text",
                  "text": intro}]
        intro = ""
    for n in nodes:
        n["children"] = [m["node_id"] for m in nodes if m["parent_id"] == n["node_id"]]
    return {"document_id": doc_id, "source_files": [pdf_path.name], "intro_text": intro, "nodes": nodes}


def schema_summary(nav: dict, max_examples: int = 2, max_shapes: int = 25) -> str:
    """What the tool generator sees: structure, node kinds, column names and a few example rows/lines,
    for distinct node 'shapes' (title patterns with digits normalised), never the full content. At most
    `max_shapes` shapes are listed."""
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
    more = f"\n- ... {len(out) - max_shapes} more shapes" if len(out) > max_shapes else ""
    return f"{count} nodes. Distinct node shapes:\n" + "\n".join(out[:max_shapes]) + more


def save_map(nav: dict, path: Path) -> None:
    path.write_text(json.dumps(nav))
