"""Render TAT-HQA contexts into a text-based PDF (approach as in domains/manufacturing/render.py, not imported).

Front matter: one paragraph on what the excerpts are, then the list of chapters. Each context is a scope
("Report R-NNN"), a level-0 outline entry with two level-1 sections: Text (the paragraphs, in their released
order) and Table (the table as a ruled grid). Every cell and paragraph is printed verbatim: numbers keep their
parentheses, dashes, $ and % signs, and multi-row headers and the row-label column are kept as released.

Styling only (no text changes): leading header rows (see `header_rows`) are bold and repeat if a table runs onto
a second page, and in a header row a label followed by empty cells spans those cells when the header row below
has labels there (e.g. "Years Ended December 31," over "2019 | 2018"). Column widths are measured so that no
number or word is ever broken inside a cell (the font shrinks for very wide tables, see `fit_columns`); rows
whose cells are all empty keep a visible height.

Fonts, chosen so that every character reads back exactly from the PDF text layer with any extractor:
- Helvetica / Helvetica-Bold (standard PDF fonts, WinAnsiEncoding) for every character in that encoding, which
  is nearly all text including the currency signs, quotes and dashes. A standard encoding needs no lookup table,
  so readers cannot misdecode it.
- Arial / Arial-Bold (TrueType, embedded) only for the characters Helvetica cannot encode (U+2212 minus, U+2015
  bar, U+2264, ...) and for U+2022 bullet, which reportlab writes as WinAnsi code 127, which pdfminer reads as
  "(cid:127)". reportlab gives these characters private codes that only the font's ToUnicode table explains
  (a reader that ignores that table sees control bytes or U+FFFD), which is why Arial is no longer the main font.

Character substitutions (`printable`), the only ones made, so that the PDF text layer reads as the source:
- U+00A0 no-break space and U+2009 thin space -> space. Some paragraphs separate every word with U+00A0, which
  makes a whole line one unbreakable "word" that the layout engine then cuts at arbitrary letters.
- U+2010 hyphen and U+2011 non-breaking hyphen -> "-". reportlab maps these glyphs to no character in the text
  layer (they extract as nothing or as U+0000), so "in-store" would read "instore". They occur only in paragraph
  text (8 times in the dev split), never in table cells, questions or answers.
- Ligatures U+FB01, U+FB02 -> "fi", "fl" (left over from the reports' own PDF extraction; readers disagree on
  whether they return the ligature or the two letters).
- U+207E superscript ")" and full-width U+FF0C, U+FF1A, U+FF1F -> ")", ",", ":", "?" (no glyph in Arial;
  train split only).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .data import Context

DOC_TITLE = "Annual Report Excerpts"
FONT_DIR = Path("C:/Windows/Fonts")
FONT, FONT_BOLD = "Helvetica", "Helvetica-Bold"
FALLBACK, FALLBACK_BOLD = "Arial", "Arial-Bold"
CELL_PT = 7.5
MIN_CELL_PT = 5.0
CELL_PAD = 2.5        # left and right padding of a cell, points
TEXT_WIDTH_IN = 7.1   # letter width minus 0.7 in margins
_SUBST = {" ": " ", " ": " ", "‐": "-", "‑": "-", "ﬁ": "fi", "ﬂ": "fl",
          "⁾": ")", "，": ",", "：": ":", "？": "?"}
_HELVETICA_BAD = {"•"}   # encodable in WinAnsi, but written as code 127 (see the module docstring)

_YEAR = re.compile(r"^\s*(FY\s*)?'?((19|20)?\d\d)\s*$|^\s*(fiscal\s+)?(19|20)\d\d\s*(\(.*\))?\s*$", re.I)


def _register_fonts() -> None:
    if FALLBACK not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FALLBACK, str(FONT_DIR / "arial.ttf")))
        pdfmetrics.registerFont(TTFont(FALLBACK_BOLD, str(FONT_DIR / "arialbd.ttf")))


def printable(text: str) -> str:
    """The text as printed (see the module docstring for the substitutions)."""
    return "".join(_SUBST.get(ch, ch) for ch in text)


def needs_fallback(ch: str) -> bool:
    if ch in _HELVETICA_BAD:
        return True
    try:
        ch.encode("cp1252")
        return False
    except UnicodeEncodeError:
        return True


def _runs(text: str) -> list[tuple[bool, str]]:
    """(uses fallback font?, text) runs of printable(text)."""
    out: list[tuple[bool, str]] = []
    for ch in printable(text):
        fb = needs_fallback(ch)
        if out and out[-1][0] == fb:
            out[-1] = (fb, out[-1][1] + ch)
        else:
            out.append((fb, ch))
    return out


def markup(text: str, bold: bool = False) -> str:
    """Paragraph markup of printable(text): escaped, with fallback-font runs wrapped in <font>."""
    fb_font = FALLBACK_BOLD if bold else FALLBACK
    return "".join(f'<font name="{fb_font}">{escape(t)}</font>' if fb else escape(t) for fb, t in _runs(text))


def text_width(text: str, bold: bool, size: float) -> float:
    return sum(pdfmetrics.stringWidth(t, (FALLBACK_BOLD if bold else FALLBACK) if fb else
                                      (FONT_BOLD if bold else FONT), size) for fb, t in _runs(text))


def _is_amount(cell: str) -> bool:
    """A cell that reads as a reported value (has a digit, is not a year, has no word of 3+ letters)."""
    return bool(re.search(r"\d", cell)) and not _YEAR.match(cell) and not re.search(r"[A-Za-z]{3,}", cell)


def header_rows(table: list[list[str]]) -> int:
    """Number of leading header rows: rows before the first row that has an amount outside the label column,
    or that is a section label (label cell filled, every other cell empty)."""
    k = 0
    while k < len(table) - 1:
        row = table[k]
        if any(_is_amount(c) for c in row[1:]):
            break
        if row[0].strip() and not any(c.strip() for c in row[1:]):
            break
        k += 1
    return k


def header_spans(table: list[list[str]], n_head: int) -> list[tuple[int, int, int]]:
    """(row, first col, last col) spans in header rows; see the module docstring."""
    spans = []
    for r in range(max(n_head - 1, 0)):
        row, below = table[r], table[r + 1]
        c = 1
        while c < len(row):
            if row[c].strip():
                e = c
                while e + 1 < len(row) and not row[e + 1].strip() and below[e + 1].strip():
                    e += 1
                if e > c:
                    spans.append((r, c, e))
                c = e + 1
            else:
                c += 1
    return spans


@dataclass
class ScopeSection:
    ctx: Context
    title: str
    start_page: int = 0
    end_page: int = 0


@dataclass
class RenderedDoc:
    pdf_path: Path
    sections: list[ScopeSection] = field(default_factory=list)

    def manifest(self) -> dict:
        scopes = [{"title": s.title, "tat_split": s.ctx.split, "tat_table_uid": s.ctx.uid,
                   "tat_paragraph_uids": [p["uid"] for p in s.ctx.paragraphs], "tat_file_index": s.ctx.index,
                   "n_table_rows": len(s.ctx.table), "n_table_cols": len(s.ctx.table[0]),
                   "header_rows": header_rows(s.ctx.table), "start_page": s.start_page, "end_page": s.end_page}
                  for s in self.sections]
        # "videos" mirrors the CLEVRER manifest shape the shared report code reads (scene_index = scope title)
        return {"pdf": str(self.pdf_path), "domain": "finance", "source": "TAT-HQA (Apache-2.0)",
                "scopes": scopes,
                "videos": [{"scene_index": s.title, "title": s.title, "start_page": s.start_page,
                            "end_page": s.end_page} for s in self.sections]}


def intro() -> str:
    return ("This document collects excerpts of company annual reports. Each excerpt is a chapter titled "
            "'Report R-&lt;NNN&gt;' with two sections: 'Text', paragraphs from the report, and 'Table', the table "
            "they accompany. Amounts are given as printed in the report, with the scale it states (for example "
            "'in thousands' or '$M'); questions refer to a chapter by its title.")


def _cell_style(name: str, bold: bool, size: float) -> ParagraphStyle:
    return ParagraphStyle(name, fontName=FONT_BOLD if bold else FONT, fontSize=size, leading=size + 1.5,
                          splitLongWords=0)


def fit_columns(table: list[list[str]], n_head: int, spans) -> tuple[float, list[float]] | None:
    """(font size, column widths in points) such that every cell's longest word fits its column, trying sizes
    from CELL_PT down to MIN_CELL_PT. Spare width goes to the columns whose full text would not fit on one line.
    Cells covered by a header span are left out of the measurement (they may wrap at spaces). None if even
    MIN_CELL_PT does not fit."""
    spanned = {(r, c) for r, c0, c1 in spans for c in range(c0, c1 + 1)}
    total = TEXT_WIDTH_IN * inch
    n = len(table[0])
    size = CELL_PT
    while size >= MIN_CELL_PT - 1e-9:
        lo, nat = [0.0] * n, [0.0] * n
        for r, row in enumerate(table):
            bold = r < n_head
            for c, cell in enumerate(row):
                if (r, c) in spanned:
                    continue
                words = printable(cell).split() or [""]
                lo[c] = max(lo[c], max(text_width(w, bold, size) for w in words) + 2 * CELL_PAD + 1)
                nat[c] = max(nat[c], text_width(" ".join(words), bold, size) + 2 * CELL_PAD + 1)
        lo = [max(w, 18.0) for w in lo]
        nat = [max(a, b) for a, b in zip(nat, lo)]
        if sum(lo) <= total:
            if sum(nat) <= total:   # everything fits on one line: share the spare width evenly
                return size, [w + (total - sum(nat)) / n for w in nat]
            extra = total - sum(lo)
            need = [b - a for a, b in zip(lo, nat)]
            return size, [a + extra * d / sum(need) for a, d in zip(lo, need)]
        size -= 0.5
    return None


def table_flowable(table: list[list[str]]) -> Table:
    n_head = header_rows(table)
    spans = header_spans(table, n_head)
    fit = fit_columns(table, n_head, spans)
    if fit is None:
        raise ValueError(f"table too wide to print without breaking a word: {table[0]}")
    size, widths = fit
    st_head, st_body = _cell_style("th", True, size), _cell_style("td", False, size)
    data = [[Paragraph(markup(c, r < n_head), st_head if r < n_head else st_body) for c in row]
            for r, row in enumerate(table)]
    t = Table(data, colWidths=widths, repeatRows=n_head)
    style = [("GRID", (0, 0), (-1, -1), 0.4, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
             ("LEFTPADDING", (0, 0), (-1, -1), CELL_PAD), ("RIGHTPADDING", (0, 0), (-1, -1), CELL_PAD)]
    style += [("SPAN", (c0, r), (c1, r)) for r, c0, c1 in spans]
    style += [("TOPPADDING", (0, r), (-1, r), size + 1.5) for r, row in enumerate(table)
              if not any(c.strip() for c in row)]
    t.setStyle(TableStyle(style))
    return t


def build_pdf(contexts: list[tuple[str, Context]], pdf_path: Path, doc_label: str) -> RenderedDoc:
    """contexts: (scope title, context) in document order."""
    _register_fonts()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1f", parent=styles["Heading1"], fontName=FONT_BOLD)
    h2 = ParagraphStyle("h2f", parent=styles["Heading2"], fontName=FONT_BOLD)
    title = ParagraphStyle("tf", parent=styles["Title"], fontName=FONT_BOLD)
    body = ParagraphStyle("bf", parent=styles["BodyText"], fontName=FONT)
    sections = [ScopeSection(c, t) for t, c in contexts]
    doc = RenderedDoc(pdf_path, sections)
    by_key: dict[str, ScopeSection] = {}

    class Doc(SimpleDocTemplate):
        def afterFlowable(self, fl):
            info = getattr(fl, "_outline", None)
            if info:
                key, text, level = info
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(text, key, level=level)
                if level == 0 and key in by_key:
                    by_key[key].start_page = self.page

    def heading(text, style, key, level):
        p = Paragraph(escape(text), style)
        p._outline = (key, text, level)
        return p

    story = [heading(DOC_TITLE, title, "intro", 0), Paragraph(intro(), body),
             Paragraph(f"Chapters in this document ({doc_label}): " + ", ".join(s.title for s in sections) + ".",
                       body)]
    for sec in sections:
        key = "s" + sec.title.split("-")[-1]
        by_key[key] = sec
        T = sec.title
        story += [PageBreak(), heading(T, h1, key, 0), heading(f"{T}: Text", h2, key + "x", 1)]
        story += [Paragraph(markup(p["text"]), body) for p in sec.ctx.paragraphs]
        story.append(KeepTogether([heading(f"{T}: Table", h2, key + "t", 1), Spacer(1, 3),
                                   table_flowable(sec.ctx.table)]))

    d = Doc(str(pdf_path), pagesize=letter, title=DOC_TITLE,
            leftMargin=0.7 * inch, rightMargin=0.7 * inch, topMargin=0.7 * inch, bottomMargin=0.7 * inch)
    d.build(story)
    total = d.page
    for i, sec in enumerate(sections):
        sec.end_page = sections[i + 1].start_page - 1 if i + 1 < len(sections) else total
    return doc


def extract_pdf_pages(pdf_path: Path) -> list[str]:
    """Each page's text exactly as a PDF reader sees it."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(pdf_path))
    return [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]


def save_manifest(doc: RenderedDoc, path: Path) -> None:
    path.write_text(json.dumps(doc.manifest(), indent=2))
