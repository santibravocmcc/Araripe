"""Convert REVISAO_TECNICA.md to a well-formatted PDF using ReportLab.

Usage:
    python scripts/md_to_pdf.py
"""

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ─── Paths ───────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DOCS = {
    "pt": {
        "md": ROOT / "REVISAO_TECNICA.md",
        "pdf": ROOT / "REVISAO_TECNICA.pdf",
        "title": "Revisão Técnica — Sistema de Monitoramento de Desmatamento da Chapada do Araripe",
    },
    "en": {
        "md": ROOT / "TECHNICAL_REVIEW.md",
        "pdf": ROOT / "TECHNICAL_REVIEW.pdf",
        "title": "Technical Review — Chapada do Araripe Deforestation Monitoring System",
    },
}

# ─── Styles ──────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

BODY = ParagraphStyle(
    "Body",
    parent=styles["Normal"],
    fontSize=9.5,
    leading=13,
    alignment=TA_JUSTIFY,
    spaceAfter=6,
)

BODY_INDENT = ParagraphStyle(
    "BodyIndent",
    parent=BODY,
    leftIndent=20,
)

CODE_BLOCK = ParagraphStyle(
    "CodeBlock",
    parent=styles["Normal"],
    fontName="Courier",
    fontSize=8.5,
    leading=11,
    leftIndent=20,
    spaceAfter=6,
    backColor=colors.Color(0.95, 0.95, 0.95),
)

H1 = ParagraphStyle(
    "H1",
    parent=styles["Heading1"],
    fontSize=16,
    leading=20,
    spaceBefore=18,
    spaceAfter=8,
    textColor=colors.HexColor("#1B5E20"),
)

H2 = ParagraphStyle(
    "H2",
    parent=styles["Heading2"],
    fontSize=13,
    leading=16,
    spaceBefore=14,
    spaceAfter=6,
    textColor=colors.HexColor("#2E7D32"),
)

H3 = ParagraphStyle(
    "H3",
    parent=styles["Heading3"],
    fontSize=11,
    leading=14,
    spaceBefore=10,
    spaceAfter=4,
    textColor=colors.HexColor("#388E3C"),
)

H4 = ParagraphStyle(
    "H4",
    parent=styles["Heading4"],
    fontSize=10,
    leading=13,
    spaceBefore=8,
    spaceAfter=3,
    textColor=colors.HexColor("#43A047"),
)

TITLE_STYLE = ParagraphStyle(
    "DocTitle",
    parent=styles["Title"],
    fontSize=18,
    leading=22,
    alignment=TA_CENTER,
    spaceAfter=4,
    textColor=colors.HexColor("#1B5E20"),
)

SUBTITLE_STYLE = ParagraphStyle(
    "Subtitle",
    parent=styles["Normal"],
    fontSize=10,
    leading=13,
    alignment=TA_CENTER,
    spaceAfter=2,
    textColor=colors.gray,
)

TABLE_CELL = ParagraphStyle(
    "TableCell",
    parent=styles["Normal"],
    fontSize=7.5,
    leading=10,
    alignment=TA_LEFT,
)

TABLE_HEADER = ParagraphStyle(
    "TableHeader",
    parent=TABLE_CELL,
    fontName="Helvetica-Bold",
    textColor=colors.white,
    fontSize=7.5,
)


def md_inline(text: str) -> str:
    """Convert inline Markdown (bold, italic, code, links) to ReportLab XML."""
    # Code spans first (before bold/italic to avoid conflicts)
    text = re.sub(r"`([^`]+)`", r'<font face="Courier" size="8">\1</font>', text)
    # Bold + italic
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    # Links [text](url) → just text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Escape remaining ampersands and angle brackets
    # (but not our XML tags)
    return text


def parse_table(lines: list[str]) -> list[list[str]]:
    """Parse Markdown table lines into rows of cells."""
    rows = []
    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        # Remove empty first/last from leading/trailing pipes
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        # Skip separator rows (e.g. |---|---|)
        if all(re.match(r"^[-:]+$", c) for c in cells):
            continue
        rows.append(cells)
    return rows


def build_table(rows: list[list[str]], available_width: float) -> Table:
    """Build a ReportLab Table from parsed rows."""
    if not rows:
        return None

    n_cols = max(len(r) for r in rows)

    # Normalize row lengths
    for r in rows:
        while len(r) < n_cols:
            r.append("")

    # Convert cells to Paragraphs
    header_row = rows[0]
    data_rows = rows[1:]

    table_data = []
    # Header
    table_data.append(
        [Paragraph(md_inline(c), TABLE_HEADER) for c in header_row]
    )
    # Data
    for row in data_rows:
        table_data.append(
            [Paragraph(md_inline(c), TABLE_CELL) for c in row]
        )

    # Calculate column widths proportionally
    col_widths = []
    for i in range(n_cols):
        max_len = max(len(rows[r][i]) if i < len(rows[r]) else 0 for r in range(len(rows)))
        col_widths.append(max(max_len, 5))

    total = sum(col_widths)
    col_widths = [available_width * (w / total) for w in col_widths]

    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E7D32")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BDBDBD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def convert_md_to_pdf(md_file: Path, pdf_file: Path, doc_title: str):
    """Convert one Markdown file to PDF."""
    md_text = md_file.read_text(encoding="utf-8")
    lines = md_text.split("\n")

    doc = SimpleDocTemplate(
        str(pdf_file),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=doc_title,
        author="Santiago Bravo",
    )

    available_width = A4[0] - 4 * cm  # page width minus margins

    story = []
    i = 0
    in_list = False
    list_items = []
    table_lines = []
    in_table = False

    def flush_list():
        nonlocal list_items, in_list
        if list_items:
            for item in list_items:
                story.append(Paragraph(md_inline(item), BODY_INDENT))
            list_items = []
            in_list = False

    def flush_table():
        nonlocal table_lines, in_table
        if table_lines:
            rows = parse_table(table_lines)
            if rows:
                t = build_table(rows, available_width)
                if t:
                    story.append(Spacer(1, 4 * mm))
                    story.append(t)
                    story.append(Spacer(1, 4 * mm))
            table_lines = []
            in_table = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            if in_list:
                flush_list()
            if in_table:
                flush_table()
            i += 1
            continue

        # Horizontal rule
        if stripped == "---":
            if in_table:
                flush_table()
            if in_list:
                flush_list()
            story.append(Spacer(1, 3 * mm))
            i += 1
            continue

        # Table detection
        if stripped.startswith("|") and "|" in stripped[1:]:
            if in_list:
                flush_list()
            in_table = True
            table_lines.append(stripped)
            i += 1
            continue

        if in_table:
            flush_table()

        # Title (# heading)
        if stripped.startswith("# ") and not stripped.startswith("## "):
            flush_list()
            title_text = stripped[2:].strip()
            story.append(Paragraph(md_inline(title_text), TITLE_STYLE))
            story.append(Spacer(1, 2 * mm))
            i += 1
            continue

        # Headings
        if stripped.startswith("#### "):
            flush_list()
            story.append(Paragraph(md_inline(stripped[5:].strip()), H4))
            i += 1
            continue

        if stripped.startswith("### "):
            flush_list()
            story.append(Paragraph(md_inline(stripped[4:].strip()), H3))
            i += 1
            continue

        if stripped.startswith("## "):
            flush_list()
            story.append(Paragraph(md_inline(stripped[3:].strip()), H2))
            i += 1
            continue

        # Metadata lines (Version, Date, etc.)
        if stripped.startswith("**") and ":**" in stripped and i < 10:
            story.append(Paragraph(md_inline(stripped), SUBTITLE_STYLE))
            i += 1
            continue

        # Code block (indented with 4 spaces)
        if line.startswith("    ") and not stripped.startswith("-") and not stripped.startswith("|"):
            flush_list()
            code_text = stripped.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(code_text, CODE_BLOCK))
            i += 1
            continue

        # Numbered list items
        if re.match(r"^\d+\.\s", stripped):
            in_list = True
            item_text = re.sub(r"^\d+\.\s+", "", stripped)
            # Use bullet-style with number prefix
            num = re.match(r"^(\d+)\.", stripped).group(1)
            list_items.append(f"<b>{num}.</b> {item_text}")
            i += 1
            continue

        # Bullet list items
        if stripped.startswith("- "):
            in_list = True
            item_text = stripped[2:]
            list_items.append(f"\u2022 {item_text}")
            i += 1
            continue

        # Regular paragraph
        flush_list()
        # Collect continuation lines
        para_text = stripped
        while i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if (
                not next_line
                or next_line.startswith("#")
                or next_line.startswith("-")
                or next_line.startswith("|")
                or next_line == "---"
                or re.match(r"^\d+\.\s", next_line)
                or lines[i + 1].startswith("    ")
            ):
                break
            para_text += " " + next_line
            i += 1

        story.append(Paragraph(md_inline(para_text), BODY))
        i += 1

    # Flush remaining
    flush_list()
    flush_table()

    # Build PDF
    doc.build(story)
    print(f"PDF saved to: {pdf_file}")


if __name__ == "__main__":
    for lang, info in DOCS.items():
        if not info["md"].exists():
            print(f"[{lang}] source not found: {info['md']}")
            continue
        convert_md_to_pdf(info["md"], info["pdf"], info["title"])
