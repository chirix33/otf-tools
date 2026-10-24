"""Render manufacturing scopes into a text-based PDF (approach copied from clevrer_bench/render.py, not imported).

Front matter: what the records are, the stock/dispatch policy in prose, the constants and the units.
Each scope ("Plant <id>, Period <NN>") is a level-0 outline entry with four level-1 sections: Products,
Daily ledger, Events, Order book. Tables are ruled grids.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .data import Records
from .scopes import CAPACITY_PERCENTILE, CAPACITY_ROUND_KG, OPENING_COVER_DAYS, OPENING_WINDOW, ORDER_BOOK_DAYS, PERIOD_DAYS
from .sim import Scope, SimResult, events

DOC_TITLE = "Plant Stock and Dispatch Records"


@dataclass
class ScopeSection:
    scope: Scope
    start_page: int = 0
    end_page: int = 0

    @property
    def title(self) -> str:
        return self.scope.title


@dataclass
class RenderedDoc:
    pdf_path: Path
    sections: list[ScopeSection] = field(default_factory=list)

    def manifest(self) -> dict:
        scopes = [{"title": s.title, "plant": s.scope.plant, "period": s.scope.period,
                   "first_day": s.scope.first_day, "last_day": s.scope.last_day,
                   "start_page": s.start_page, "end_page": s.end_page} for s in self.sections]
        # "videos" mirrors the CLEVRER manifest shape the shared report code reads (scene_index = scope title)
        return {"pdf": str(self.pdf_path), "domain": "manufacturing", "scopes": scopes,
                "videos": [{"scene_index": s.title, "title": s.title, "start_page": s.start_page,
                            "end_page": s.end_page} for s in self.sections]}


def intro(rec: Records, caps: dict[str, int]) -> list[str]:
    plants = ", ".join(f"Plant {p}: {c} kg per day" for p, c in sorted(caps.items()))
    return [
        "This document records stock and dispatch at the plants of a manufacturer of packaged consumer goods. "
        "The daily production and daily sales-order quantities of every product are real company records "
        f"(day 1 is {rec.date_of(1)}). Stock, shipments and backorders are not recorded by the company: they are "
        "computed from those records by the stock and dispatch policy stated below, applied exactly.",
        f"The document is divided into chapters titled 'Plant &lt;id&gt;, Period &lt;NN&gt;'. A period is "
        f"{PERIOD_DAYS} consecutive days; period 01 is days 1 to {PERIOD_DAYS}, period 02 is days "
        f"{PERIOD_DAYS + 1} to {2 * PERIOD_DAYS}, and so on. Questions refer to a chapter by that title. "
        "Days are numbered from day 1 and each day's calendar date is given next to it.",
        "Each chapter has four sections. 'Products' lists the products dispatched by the plant, with product "
        "group, sub-group, storage location, weight per unit and opening stock. 'Daily ledger' gives, for every "
        "day of the period and every product, the units produced, the units ordered that day, the units shipped, "
        "the units backordered at the end of the day and the stock at the end of the day. 'Events' lists, in "
        "time order, the days on which the dispatch capacity was reached, products ran out of stock, orders "
        "were fully backordered and backlogs were cleared. 'Order book' gives, for the "
        f"{ORDER_BOOK_DAYS} days after the period, the orders already received and the production already "
        "planned; these quantities are exactly what then happened.",
        "<b>Stock and dispatch policy.</b> Each plant dispatches all of its products from one storage location "
        "with one truck fleet. Every period is an independent run: on its first day each product starts with "
        "its opening stock and there are no open orders. Then, every day, in this order:",
        "1. <b>Production arrives.</b> The day's production of each product is added to its stock.",
        "2. <b>Orders join the queue.</b> The day's sales order of each product, if it is above zero, becomes "
        "one order (product, quantity, day placed). Orders not completely shipped on earlier days stay in the "
        "queue with their remaining quantity (they are backordered).",
        "3. <b>Dispatch.</b> The plant has a daily dispatch capacity in kilograms, shared by all of its products. "
        "Open orders are served one at a time, oldest first; among orders placed on the same day, the one with "
        "the smaller remaining quantity goes first, then the lower product code (alphabetical order). Each order "
        "ships as many whole units as both the product's stock and the capacity still unused that day allow "
        "(a unit uses its weight in capacity). Whatever it cannot ship stays open, and the next order is served. "
        "Capacity used by one product is not available to the other products that day; unused capacity is "
        "not carried over to the next day.",
        "4. <b>Records.</b> The ledger row of a product for a day gives: produced (units that arrived), "
        "ordered (quantity of the order placed that day, 0 if none), shipped (units shipped that day, for all "
        "of its orders together), backordered (units of all its open orders at the end of the day) and stock "
        "(units on hand at the end of the day). Stock at the end of a day = stock at the end of the previous "
        "day + produced - shipped; backordered = previous backordered + ordered - shipped.",
        "<b>Terms used in the Events section and in questions.</b> A product <i>runs out of stock</i> on a day "
        "when, at the end of that day, it has no stock while some of its units are backordered; the Events "
        "section lists the first day of each such run of days. The <i>dispatch capacity is reached</i> on a day "
        "when at least one order shipped fewer units than its product's stock would have allowed because the "
        "remaining capacity was too small. An order is <i>fully backordered</i> when nothing of it ships on the "
        "day it is placed. A product's <i>backlog is cleared</i> when its backordered units return to 0. An "
        "order <i>ships in full</i> on a day when all of its units ship that day.",
        f"<b>Constants.</b> Opening stock of a product = {OPENING_COVER_DAYS} x its mean daily order over days 1 "
        f"to {OPENING_WINDOW}, rounded to whole units (the same in every period; listed in each chapter's "
        "Products table). Daily dispatch capacity: " + plants + f". Each capacity is the {CAPACITY_PERCENTILE}th "
        f"percentile of the plant's daily ordered weight over the whole record, rounded to the nearest "
        f"{CAPACITY_ROUND_KG} kg.",
        "<b>Units.</b> Quantities are whole units (cases); weights in kilograms (kg). Recorded quantities are "
        "rounded to whole units.",
    ]


def _grid(data: list[list[str]], widths: list[float]) -> Table:
    t = Table(data, repeatRows=1, colWidths=[w * inch for w in widths])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t


def build_pdf(rec: Records, caps: dict[str, int], runs: list[tuple[Scope, SimResult]], pdf_path: Path,
              doc_label: str) -> RenderedDoc:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    h1, h2, body = styles["Heading1"], styles["Heading2"], styles["BodyText"]
    sections = [ScopeSection(s) for s, _ in runs]
    doc = RenderedDoc(pdf_path, sections)
    by_key: dict[str, ScopeSection] = {}

    class Doc(SimpleDocTemplate):
        def afterFlowable(self, fl):
            info = getattr(fl, "_outline", None)
            if info:
                key, title, level = info
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(title, key, level=level)
                if level == 0 and key in by_key:
                    by_key[key].start_page = self.page

    def heading(text, style, key, level):
        p = Paragraph(text, style)
        p._outline = (key, text, level)
        return p

    story = [heading(DOC_TITLE, styles["Title"], "intro", 0)]
    story += [Paragraph(t, body) for t in intro(rec, caps)]
    story.append(Paragraph(f"Chapters in this document ({doc_label}): " +
                           ", ".join(s.title for s in sections) + ".", body))
    for sec, (s, res) in zip(sections, runs):
        key = f"s{s.plant}_{s.period:02d}"
        by_key[key] = sec
        T = s.title
        story += [PageBreak(), heading(T, h1, key, 0),
                  Paragraph(f"Days {s.first_day} to {s.last_day} ({rec.date_of(s.first_day)} to "
                            f"{rec.date_of(s.last_day)}). Plant {s.plant} dispatches {len(s.products)} products. "
                            f"Daily dispatch capacity: {s.capacity_kg} kg.", body)]
        # Products
        story.append(heading(f"{T}: Products", h2, key + "p", 1))
        rows = [["product", "group", "sub-group", "storage location", "kg per unit", "opening stock"]]
        for p in s.products:
            pr = rec.products[p]
            rows.append([p, pr.group, pr.subgroup, pr.storage, f"{pr.kg_per_unit:.3f}".rstrip("0").rstrip("."),
                         str(s.opening_stock[p])])
        story += [Spacer(1, 4), _grid(rows, [1.3, 0.6, 0.9, 1.1, 0.9, 1.0])]
        # Daily ledger
        story.append(heading(f"{T}: Daily ledger", h2, key + "l", 1))
        rows = [["day", "date", "product", "produced", "ordered", "shipped", "backordered", "stock"]]
        for d in s.days:
            for p in s.products:
                r = res.rows[(d, p)]
                rows.append([str(d), rec.date_of(d), p] + [str(r[k]) for k in
                            ("produced", "ordered", "shipped", "backordered", "stock")])
        story += [Spacer(1, 4), _grid(rows, [0.45, 0.85, 1.3, 0.8, 0.8, 0.8, 0.9, 0.8])]
        # Events
        story.append(heading(f"{T}: Events", h2, key + "e", 1))
        ev = events(s, res)
        if not ev:
            story.append(Paragraph("No events in this period.", body))
        story += [Paragraph(f"Day {d} ({rec.date_of(d)}): {txt}.", body) for d, _, _, txt in ev]
        # Order book
        story.append(heading(f"{T}: Order book", h2, key + "o", 1))
        story.append(Paragraph(
            f"Order book at the end of day {s.last_day}: orders received and production planned for days "
            f"{s.last_day + 1} to {s.horizon_day}. These quantities are exactly what then happened.", body))
        open_rows = [["product", "day placed", "units still open"]]
        for o in sorted(res.orders.values(), key=lambda o: (o.day, o.product)):
            left = o.qty - sum(n for dd, n in o.shipped.items() if dd <= s.last_day)
            if o.day <= s.last_day and left > 0:
                open_rows.append([o.product, str(o.day), str(left)])
        if len(open_rows) > 1:
            story += [Paragraph(f"Open orders at the end of day {s.last_day} (backordered):", body),
                      Spacer(1, 4), _grid(open_rows, [1.3, 0.9, 1.2]), Spacer(1, 6)]
        else:
            story.append(Paragraph(f"There are no open orders at the end of day {s.last_day}.", body))
        story.append(Paragraph(f"Orders received and production planned for days {s.last_day + 1} to "
                               f"{s.horizon_day}:", body))
        rows = [["day", "date", "product", "planned production", "ordered"]]
        for d in s.future_days:
            for p in s.products:
                rows.append([str(d), rec.date_of(d), p, str(s.production[d][p]), str(s.orders[d][p])])
        story += [Spacer(1, 4), _grid(rows, [0.45, 0.85, 1.3, 1.3, 0.8])]

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
