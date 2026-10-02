"""Render generated Markdown documentation as PDF and JPG without another AI call."""

from __future__ import annotations

import html
import io
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle


class ExportError(ValueError):
    """Raised for invalid or unsupported export requests."""


@dataclass(frozen=True)
class Block:
    kind: str
    text: str = ""
    level: int = 0
    items: tuple[str, ...] = ()
    ordered: bool = False
    rows: tuple[tuple[str, ...], ...] = ()


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
BULLET_RE = re.compile(r"^\s*[-*+]\s+(.+)$")
ORDERED_RE = re.compile(r"^\s*\d+[.)]\s+(.+)$")


def _table_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in line.split("|")]


def _table_separator(line: str) -> bool:
    cells = _table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def parse_markdown(markdown: str) -> list[Block]:
    """Parse the Markdown structures produced by the documentation generator."""
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    paragraph: list[str] = []
    i = 0

    def flush() -> None:
        if paragraph:
            text = " ".join(x.strip() for x in paragraph if x.strip())
            if text:
                blocks.append(Block("paragraph", text=text))
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        fence_token = chr(96) * 3

        if stripped.startswith(fence_token) or stripped.startswith("~~~"):
            flush()
            fence = stripped[:3]
            i += 1
            code: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith(fence):
                code.append(lines[i])
                i += 1
            blocks.append(Block("code", text="\n".join(code)))
            i += 1
            continue

        heading = HEADING_RE.match(stripped)
        if heading:
            flush()
            blocks.append(Block("heading", text=heading.group(2), level=len(heading.group(1))))
            i += 1
            continue

        if i + 1 < len(lines) and "|" in stripped and _table_separator(lines[i + 1]):
            flush()
            header = tuple(_table_row(stripped))
            rows = [header]
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                rows.append(tuple(_table_row(lines[i])))
                i += 1
            width = len(header)
            rows = [tuple(list(row[:width]) + [""] * max(0, width - len(row))) for row in rows]
            blocks.append(Block("table", rows=tuple(rows)))
            continue

        bullet = BULLET_RE.match(line)
        if bullet:
            flush()
            items = [bullet.group(1).strip()]
            i += 1
            while i < len(lines):
                match = BULLET_RE.match(lines[i])
                if not match:
                    break
                items.append(match.group(1).strip())
                i += 1
            blocks.append(Block("list", items=tuple(items)))
            continue

        ordered = ORDERED_RE.match(line)
        if ordered:
            flush()
            items = [ordered.group(1).strip()]
            i += 1
            while i < len(lines):
                match = ORDERED_RE.match(lines[i])
                if not match:
                    break
                items.append(match.group(1).strip())
                i += 1
            blocks.append(Block("list", items=tuple(items), ordered=True))
            continue

        if stripped.startswith(">"):
            flush()
            quote = [stripped[1:].lstrip()]
            i += 1
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].lstrip())
                i += 1
            blocks.append(Block("quote", text=" ".join(quote)))
            continue

        if stripped in {"---", "***", "___"}:
            flush()
            blocks.append(Block("hr"))
            i += 1
            continue

        if not stripped:
            flush()
            i += 1
            continue

        paragraph.append(line)
        i += 1

    flush()
    return blocks


def _plain(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return html.unescape(re.sub(r"[*_]", "", text).replace(chr(96), ""))


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__([^_]+)__", r"<b>\1</b>", text)
    text = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", text)
    text = re.sub(r"_([^_]+)_", r"<i>\1</i>", text)
    text = re.sub(r"\[([^\]]+)\]\((?:[^)]+)\)", r"\1", text)
    return text


def _font_path(*candidates: str) -> str | None:
    return next((p for p in candidates if Path(p).exists()), None)


def _pdf_fonts() -> tuple[str, str, str]:
    regular = _font_path(
        r"C:\\Windows\\Fonts\\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    bold = _font_path(
        r"C:\\Windows\\Fonts\\arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    )
    mono = _font_path(
        r"C:\\Windows\\Fonts\\consola.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationMono-Regular.ttf",
    )
    if not (regular and bold and mono):
        return "Helvetica", "Helvetica-Bold", "Courier"
    try:
        for name, path in (("DocSans", regular), ("DocSansBold", bold), ("DocMono", mono)):
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, path))
        return "DocSans", "DocSansBold", "DocMono"
    except Exception:
        return "Helvetica", "Helvetica-Bold", "Courier"


def markdown_to_pdf(markdown: str, document_name: str = "Documentation") -> bytes:
    blocks = parse_markdown(markdown)
    if not blocks:
        raise ExportError("No documentation content is available to export.")

    font, bold, mono = _pdf_fonts()
    styles = getSampleStyleSheet()
    body = ParagraphStyle("ExportBody", parent=styles["BodyText"], fontName=font, fontSize=10, leading=14.5, textColor=colors.HexColor("#243447"), spaceAfter=7)
    h1 = ParagraphStyle("ExportH1", parent=body, fontName=bold, fontSize=20, leading=24, textColor=colors.HexColor("#1f2a44"), spaceBefore=10, spaceAfter=8)
    h2 = ParagraphStyle("ExportH2", parent=body, fontName=bold, fontSize=15, leading=19, textColor=colors.HexColor("#324a73"), spaceBefore=12, spaceAfter=6)
    h3 = ParagraphStyle("ExportH3", parent=body, fontName=bold, fontSize=12, leading=16, spaceBefore=9, spaceAfter=5)
    quote = ParagraphStyle("ExportQuote", parent=body, leftIndent=12, borderPadding=7, backColor=colors.HexColor("#f4f7fb"), borderColor=colors.HexColor("#8aa4c4"), borderWidth=1, borderLeft=True)
    code = ParagraphStyle("ExportCode", parent=body, fontName=mono, fontSize=7.8, leading=10, backColor=colors.HexColor("#101827"), textColor=colors.HexColor("#e2e8f0"), borderPadding=8)
    bullet = ParagraphStyle("ExportBullet", parent=body, leftIndent=14, firstLineIndent=-9, spaceAfter=3)
    table_head = ParagraphStyle("ExportTableHead", parent=body, fontName=bold, fontSize=8.3, leading=10.5)
    table_body = ParagraphStyle("ExportTableBody", parent=body, fontSize=8, leading=10.5)

    title = document_name.strip() or "Documentation"
    story = [
        Paragraph(html.escape(title), ParagraphStyle("ExportTitle", parent=h1, alignment=TA_CENTER, fontSize=24, leading=28, spaceAfter=4)),
        Paragraph("Generated documentation", ParagraphStyle("ExportSubtitle", parent=body, alignment=TA_CENTER, textColor=colors.HexColor("#64748b"), spaceAfter=16)),
    ]

    for block in blocks:
        if block.kind == "heading":
            style = h1 if block.level == 1 else h2 if block.level == 2 else h3
            story.append(Paragraph(_inline(block.text), style))
        elif block.kind == "paragraph":
            story.append(Paragraph(_inline(block.text), body))
        elif block.kind == "list":
            for n, item in enumerate(block.items, 1):
                marker = f"{n}." if block.ordered else "•"
                story.append(Paragraph(f"{marker} {_inline(item)}", bullet))
            story.append(Spacer(1, 3))
        elif block.kind == "quote":
            story.extend([Paragraph(_inline(block.text), quote), Spacer(1, 5)])
        elif block.kind == "code":
            story.append(Preformatted(block.text, code))
        elif block.kind == "table" and block.rows:
            data = []
            for row_index, row in enumerate(block.rows):
                style = table_head if row_index == 0 else table_body
                data.append([Paragraph(_inline(cell), style) for cell in row])
            col_width = 168 * mm / max(1, len(block.rows[0]))
            table = Table(data, colWidths=[col_width] * len(block.rows[0]), repeatRows=1)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf0f7")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8d2df")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.extend([table, Spacer(1, 7)])
        elif block.kind == "hr":
            story.append(Spacer(1, 4))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=21 * mm, bottomMargin=16 * mm, title=title,
        author="AI Documentation Assistant",
    )

    def footer(canvas, doc):
        canvas.saveState()
        width, height = A4
        canvas.setStrokeColor(colors.HexColor("#d8e0ea"))
        canvas.line(18 * mm, height - 14 * mm, width - 18 * mm, height - 14 * mm)
        canvas.setFont(font, 7.5)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(18 * mm, height - 10.5 * mm, title[:80])
        canvas.drawRightString(width - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def _pil_fonts() -> tuple[ImageFont.ImageFont, ImageFont.ImageFont, ImageFont.ImageFont]:
    regular = _font_path(r"C:\\Windows\\Fonts\\arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    bold = _font_path(r"C:\\Windows\\Fonts\\arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    mono = _font_path(r"C:\\Windows\\Fonts\\consola.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")

    def load(path: str | None, size: int) -> ImageFont.ImageFont:
        if path:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
        return ImageFont.load_default()

    return load(regular, 34), load(bold, 42), load(mono, 25)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def markdown_to_jpg(markdown: str, document_name: str = "Documentation", width: int = 1600) -> bytes:
    blocks = parse_markdown(markdown)
    if not blocks:
        raise ExportError("No documentation content is available to export.")
    if not 1000 <= width <= 2400:
        raise ExportError("JPG export width must be between 1000 and 2400 pixels.")

    regular, bold, mono = _pil_fonts()
    regular_size = int(getattr(regular, "size", 18))
    bold_size = int(getattr(bold, "size", 24))
    mono_size = int(getattr(mono, "size", 16))
    pad = 90
    content_width = width - pad * 2
    probe = Image.new("RGB", (width, 100), "white")
    pdraw = ImageDraw.Draw(probe)

    estimated = 220
    for block in blocks:
        if block.kind == "heading":
            size = bold_size if block.level == 1 else max(26, bold_size - 10)
            estimated += size + 45
        elif block.kind == "paragraph":
            estimated += len(_wrap(pdraw, _plain(block.text), regular, content_width)) * (regular_size + 12) + 22
        elif block.kind == "list":
            for item in block.items:
                estimated += len(_wrap(pdraw, _plain(item), regular, content_width - 60)) * (regular_size + 12) + 10
            estimated += 10
        elif block.kind == "quote":
            estimated += len(_wrap(pdraw, _plain(block.text), regular, content_width - 40)) * (regular_size + 12) + 35
        elif block.kind == "code":
            estimated += max(1, len(block.text.splitlines())) * (mono_size + 10) + 40
        elif block.kind == "table":
            for row in block.rows:
                estimated += max(
                    len(_wrap(pdraw, _plain(cell), regular, max(120, content_width // max(1, len(row)) - 24)))
                    for cell in row
                ) * (regular_size + 7) + 24
        else:
            estimated += 30

    estimated = min(max(estimated + 120, 1000), 60000)
    image = Image.new("RGB", (width, estimated), "white")
    draw = ImageDraw.Draw(image)
    title = document_name.strip() or "Documentation"
    y = pad

    draw.text((pad, y), title, font=bold, fill="#1f2a44")
    y += bold_size + 20
    draw.text((pad, y), "Generated documentation", font=regular, fill="#64748b")
    y += regular_size + 30
    draw.line((pad, y, width - pad, y), fill="#c8d2df", width=3)
    y += 30

    def paragraph(text: str, font, color: str, x: int = pad, max_width: int = content_width, prefix: str = "") -> None:
        nonlocal y
        lines = _wrap(draw, _plain(text), font, max_width - (45 if prefix else 0))
        if prefix:
            draw.text((x, y), prefix, font=font, fill=color)
        for line in lines:
            draw.text((x + (45 if prefix else 0), y), line, font=font, fill=color)
            y += int(getattr(font, "size", regular_size)) + 12

    for block in blocks:
        if block.kind == "heading":
            font = bold
            y += 14
            paragraph(block.text, font, "#1f2a44" if block.level == 1 else "#324a73", max_width=content_width)
            draw.line((pad, y, width - pad, y), fill="#e0e6ee", width=2 if block.level == 1 else 1)
            y += 16
        elif block.kind == "paragraph":
            paragraph(block.text, regular, "#243447")
            y += 8
        elif block.kind == "list":
            for n, item in enumerate(block.items, 1):
                paragraph(item, regular, "#243447", prefix=f"{n}." if block.ordered else "•")
            y += 8
        elif block.kind == "quote":
            lines = _wrap(draw, _plain(block.text), regular, content_width - 40)
            height = len(lines) * (regular_size + 12) + 24
            top = y
            draw.rounded_rectangle((pad, top, width - pad, top + height), radius=10, fill="#f4f7fb", outline="#8aa4c4", width=2)
            y += 12
            for line in lines:
                draw.text((pad + 24, y), line, font=regular, fill="#52667f")
                y += regular_size + 12
            y += 22
        elif block.kind == "code":
            code_lines = block.text.splitlines() or [""]
            line_h = mono_size + 10
            box_h = len(code_lines) * line_h + 26
            draw.rounded_rectangle((pad, y, width - pad, y + box_h), radius=10, fill="#101827")
            y += 13
            for line in code_lines:
                for wrapped in _wrap(draw, line, mono, content_width - 20):
                    draw.text((pad + 12, y), wrapped, font=mono, fill="#e2e8f0")
                    y += line_h
            y += 24
        elif block.kind == "table" and block.rows:
            cols = max(1, len(block.rows[0]))
            col_width = content_width // cols
            for row_index, row in enumerate(block.rows):
                cell_lines = [
                    _wrap(draw, _plain(cell), regular, max(120, col_width - 24))
                    for cell in row
                ]
                row_h = max(len(lines) for lines in cell_lines) * (regular_size + 7) + 20
                fill = "#eaf0f7" if row_index == 0 else "#ffffff"
                draw.rectangle((pad, y, width - pad, y + row_h), fill=fill, outline="#c8d2df")
                for col_index, lines in enumerate(cell_lines):
                    x = pad + col_index * col_width + 12
                    yy = y + 8
                    for line in lines:
                        draw.text((x, yy), line, font=bold if row_index == 0 else regular, fill="#1f2a44")
                        yy += regular_size + 7
                    draw.line((pad + col_index * col_width, y, pad + col_index * col_width, y + row_h), fill="#c8d2df")
                y += row_h
            draw.line((pad + cols * col_width, y - sum(0 for _ in []), pad + cols * col_width, y), fill="#c8d2df")
            y += 22
        else:
            y += 20

    y += 30
    draw.text((pad, y), "Generated by AI Documentation Assistant", font=regular, fill="#94a3b8")
    if y + pad > 60000:
        raise ExportError("This documentation is too long for a single JPG image. Use the PDF export instead.")

    image = image.crop((0, 0, width, y + pad))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=94, optimize=True, progressive=True)
    return output.getvalue()
