"""Convert a Word (.docx) document into markdown text, in document order."""

from __future__ import annotations

import re
from pathlib import Path

HEADING_STYLE = re.compile(r"^Heading\s+(\d)$", re.IGNORECASE)
TITLE_STYLES = ("title",)
LIST_STYLE_PREFIX = "list"
TABLE_RULE_CELL = "---"


def _load_docx_module():
    try:
        import docx
    except ImportError as error:
        raise RuntimeError("Reading .docx files requires the 'python-docx' package.") from error
    return docx


def _text(paragraph) -> str:
    return " ".join(paragraph.text.split())


def _list_level(paragraph) -> int | None:
    properties = paragraph._p.pPr
    numbering = properties.numPr if properties is not None else None
    if numbering is not None:
        return int(numbering.ilvl.val) if numbering.ilvl is not None else 0
    if paragraph.style is not None and paragraph.style.name.lower().startswith(LIST_STYLE_PREFIX):
        return 0
    return None


def _paragraph_line(paragraph) -> str:
    text = _text(paragraph)
    if not text:
        return ""
    style = paragraph.style.name if paragraph.style is not None else ""
    heading = HEADING_STYLE.match(style)
    if heading:
        return f"{'#' * int(heading.group(1))} {text}"
    if style.lower() in TITLE_STYLES:
        return f"# {text}"
    level = _list_level(paragraph)
    if level is not None:
        return f"{'  ' * level}- {text}"
    return text


def _row_cells(row) -> list:
    cells, previous = [], None
    for cell in row.cells:
        if cell._tc is not previous:
            cells.append(" ".join(cell.text.split()))
        previous = cell._tc
    return cells


def _table_lines(table) -> list:
    lines = []
    for index, row in enumerate(table.rows):
        cells = _row_cells(row)
        lines.append("| " + " | ".join(cells) + " |")
        if index == 0:
            lines.append("| " + " | ".join(TABLE_RULE_CELL for _ in cells) + " |")
    return lines


def docx_to_markdown(path: str | Path) -> str:
    """Return the document as markdown: headings, list items and tables in their original order."""
    docx = _load_docx_module()
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(str(path))
    lines: list = []
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            line = _paragraph_line(Paragraph(child, document))
            is_list_line = line.lstrip().startswith("- ")
            if is_list_line or not line or (lines and lines[-1] == ""):
                lines.append(line)
            else:
                lines.extend(["", line])
        elif child.tag.endswith("}tbl"):
            lines.extend(["", *_table_lines(Table(child, document)), ""])
    return "\n".join(lines).strip() + "\n"
