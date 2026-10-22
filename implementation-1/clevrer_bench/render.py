"""Render CLEVRER ground-truth annotations (observed frames only) into a text-based PDF.

Each sampled video becomes one chapter ("Video <scene_index>") with three sections:
Objects, Events, Motion log. The PDF carries an embedded outline (bookmarks) so
tree-based indexers can pick up the structure.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

STATIONARY_SPEED = 0.1  # speeds are bimodal: exactly 0 when at rest, >0.25 when moving


@dataclass
class VideoSection:
    scene_index: int
    objects: list[str]
    events: list[str]
    motion_header: list[str]
    motion_rows: list[list[str]]
    start_page: int = 0
    end_page: int = 0

    @property
    def title(self) -> str:
        return f"Video {self.scene_index}"


@dataclass
class RenderedDoc:
    pdf_path: Path
    intro: list[str]
    sections: list[VideoSection] = field(default_factory=list)

    def manifest(self) -> dict:
        return {"pdf": str(self.pdf_path),
                "videos": [{"scene_index": s.scene_index, "title": s.title,
                            "start_page": s.start_page, "end_page": s.end_page} for s in self.sections]}


def describe(obj: dict) -> str:
    return f"{obj['color']} {obj['material']} {obj['shape']}"


def build_section(ann: dict, stride: int) -> VideoSection:
    props = {o["object_id"]: o for o in ann["object_property"]}
    frames = ann["motion_trajectory"]
    last = frames[-1]["frame_id"]

    objects = [f"Object {oid}: {describe(o)} (color={o['color']}, material={o['material']}, shape={o['shape']})"
               for oid, o in sorted(props.items())]

    # (frame, order, text): visibility transitions + collisions, chronological
    events: list[tuple[int, int, str]] = []
    prev = {oid: False for oid in props}
    for fr in frames:
        f = fr["frame_id"]
        for o in fr["objects"]:
            oid, vis = o["object_id"], o["inside_camera_view"]
            if vis and not prev[oid]:
                txt = (f"Object {oid} ({describe(props[oid])}) is in view when the video begins"
                       if f == 0 else f"Object {oid} ({describe(props[oid])}) enters the scene")
                events.append((f, 0, txt))
            elif prev[oid] and not vis:
                events.append((f, 2, f"Object {oid} ({describe(props[oid])}) exits the scene"))
            prev[oid] = vis
    for c in ann["collision"]:
        a, b = c["object_ids"]
        events.append((c["frame_id"], 1,
                       f"Object {a} ({describe(props[a])}) collides with Object {b} ({describe(props[b])})"))
    events.sort()
    event_lines = [f"Frame {f}: {t}." for f, _, t in events]
    event_lines.append(f"Frame {last}: The video ends.")

    keep = set(range(0, last + 1, stride)) | {f for f, _, _ in events} | {last}
    header = ["frame", "object", "x", "y", "vx", "vy", "speed"]
    rows = []
    for fr in frames:
        if fr["frame_id"] not in keep:
            continue
        for o in sorted(fr["objects"], key=lambda o: o["object_id"]):
            if not o["inside_camera_view"]:
                continue  # not visible in the video -> not observable
            x, y = o["location"][:2]
            vx, vy = o["velocity"][:2]
            rows.append([str(fr["frame_id"]), f"{o['object_id']} {describe(props[o['object_id']])}",
                         f"{x:.2f}", f"{y:.2f}", f"{vx:.2f}", f"{vy:.2f}", f"{math.hypot(vx, vy):.2f}"])
    return VideoSection(ann["scene_index"], objects, event_lines, header, rows)


INTRO = [
    "This document describes short physics videos from the CLEVRER benchmark. Each video is 128 frames "
    "(frame 0 to frame 127, about 5 seconds) showing solid objects sliding on a flat floor and colliding.",
    "Every video has its own chapter titled 'Video &lt;number&gt;'. Questions refer to a video by that number.",
    "Each chapter has three sections. 'Objects' lists every object with its color, material (metal or rubber) "
    "and shape (cube, sphere or cylinder). 'Events' lists, in time order, when objects enter the scene, exit the "
    "scene and collide with each other. 'Motion log' gives sampled positions (x, y) and velocities (vx, vy) on "
    "the floor plane for objects that are visible in the video.",
    f"An object is stationary at a frame if its speed is below {STATIONARY_SPEED}; otherwise it is moving. "
    "Only what is visible during the 128 frames is recorded; nothing after the video ends is described.",
]


def build_pdf(sections: list[VideoSection], pdf_path: Path) -> RenderedDoc:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    h1, h2, body = styles["Heading1"], styles["Heading2"], styles["BodyText"]
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10)
    doc = RenderedDoc(pdf_path, INTRO, sections)

    class Doc(SimpleDocTemplate):
        def afterFlowable(self, fl):
            info = getattr(fl, "_outline", None)
            if info:
                key, title, level = info
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(title, key, level=level)
                if level == 0 and key.startswith("v"):
                    sec = by_key[key]
                    sec.start_page = self.page

    by_key: dict[str, VideoSection] = {}

    def heading(text, style, key, level):
        p = Paragraph(text, style)
        p._outline = (key, text, level)
        return p

    story = [heading("CLEVRER Video Annotations", styles["Title"], "intro", 0)]
    story += [Paragraph(t, body) for t in INTRO]
    story.append(Paragraph("Videos in this document: " +
                           ", ".join(s.title for s in sections) + ".", body))
    for s in sections:
        key = f"v{s.scene_index}"
        by_key[key] = s
        story += [PageBreak(), heading(s.title, h1, key, 0),
                  heading(f"Video {s.scene_index}: Objects", h2, key + "o", 1)]
        story += [Paragraph(t, body) for t in s.objects]
        story.append(heading(f"Video {s.scene_index}: Events", h2, key + "e", 1))
        story += [Paragraph(t, body) for t in s.events]
        story.append(heading(f"Video {s.scene_index}: Motion log", h2, key + "m", 1))
        table = Table([s.motion_header] + s.motion_rows, repeatRows=1,
                      colWidths=[0.6 * inch, 2.4 * inch] + [0.75 * inch] * 5)
        table.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
            ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        story += [Spacer(1, 4), table]

    d = Doc(str(pdf_path), pagesize=letter, title="CLEVRER Video Annotations",
            leftMargin=0.7 * inch, rightMargin=0.7 * inch, topMargin=0.7 * inch, bottomMargin=0.7 * inch)
    d.build(story)
    total = d.page
    for i, s in enumerate(sections):
        s.end_page = sections[i + 1].start_page - 1 if i + 1 < len(sections) else total
    return doc


def extract_pdf_pages(pdf_path: Path) -> list[str]:
    """Each page's text exactly as a PDF reader sees it, wrapped in <page n> markers."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(pdf_path))
    pages = []
    for i in range(len(pdf)):
        tp = pdf[i].get_textpage()
        pages.append(f"<page {i + 1}>\n{tp.get_text_range()}\n</page {i + 1}>")
    return pages


def extract_pdf_text(pdf_path: Path) -> str:
    """Text exactly as a PDF reader sees it (used by the full-context baseline)."""
    return "\n".join(extract_pdf_pages(pdf_path))


def save_manifest(doc: RenderedDoc, path: Path) -> None:
    path.write_text(json.dumps(doc.manifest(), indent=2))
