"""Reducing a document to the list of HTML tables it holds, whichever form they were written in.

Three forms converge here so ``metrics.table.parse_table`` stays the only parser:
``<table>`` markup embedded in markdown, markdown pipe tables, and real ``.docx``
tables. Predictions and ground truth for one stem routinely use different forms -
``tonghopdon`` gold is pipe and its prediction is ``<table>`` - so the comparison
would measure the writing style rather than the engine if they did not.

Tables come back in **document order**, interleaved regardless of form, because a
table's position in the returned list is the index the scorer pairs and tie-breaks
on.

The docx walker is public because two callers need it: ``extract_docx_tables`` here
and ``ground_truth.load``, which builds the plain-text stream. Both have to avoid
``row.cells``, which reports a vertically merged cell once per row it spans.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from xml.sax.saxutils import escape

from docx import Document
from docx.table import Table, _Cell
from lxml import etree, html

# A pipe-table delimiter cell: three or more dashes, optionally colon-aligned.
PIPE_DELIMITER_RE = re.compile(r"^:?-{3,}:?$")

# Cell boundaries are unescaped pipes only; ``\|`` is a literal pipe inside a cell.
PIPE_SPLIT_RE = re.compile(r"(?<!\\)\|")

# ``w:vMerge`` with this value continues the span above rather than starting a cell.
# A cell with no ``vMerge`` at all reads back as None, which means *not merged*.
VMERGE_CONTINUE = "continue"


@dataclass(frozen=True)
class DocxCell:
    """One docx table cell, visited once however many grid positions it spans."""

    row: int
    column: int  # grid column, which advances by colspan rather than by list index
    colspan: int
    rowspan: int
    text: str


class TableExtractError(Exception):
    """Raised when a document's table markup cannot be read at all."""


# Return every table in a markdown or HTML document, as HTML markup, in document order.
def extract_html_tables(text: str) -> list[str]:
    # Empty and whitespace-only input have no tables; lxml raises on both
    if not text or not text.strip():
        return []

    # Split the document into pipe-table runs and the markup between them, in order
    lines = text.split("\n")
    segments: list[tuple[str, list[str]]] = []
    buffered: list[str] = []
    index = 0
    while index < len(lines):
        run_end = _pipe_run_end(lines, index)
        if run_end is None:
            buffered.append(lines[index])
            index += 1
            continue

        segments.append(("markup", buffered))
        segments.append(("pipe", lines[index:run_end]))
        buffered = []
        index = run_end
    segments.append(("markup", buffered))

    tables: list[str] = []
    for kind, payload in segments:
        if kind == "pipe":
            tables.append(_pipe_run_to_html(payload))
            continue

        # Markup between runs may hold no table, or several, or none parseable
        joined = "\n".join(payload)
        if not joined.strip():
            continue
        try:
            root = html.fromstring(joined)
        except (etree.ParserError, etree.XMLSyntaxError, ValueError):
            continue

        # A table nested in another table is part of its parent, not a table of its own
        tables.extend(
            etree.tostring(found, encoding="unicode", method="html", with_tail=False)
            for found in root.iter("table")
            if next(found.iterancestors("table"), None) is None
        )

    return tables


# Return every table in a .docx, as HTML markup, in document order.
def extract_docx_tables(path: Path) -> list[str]:
    if not path.exists():
        raise TableExtractError(f"docx not found: {path}")

    document = Document(str(path))
    tables: list[str] = []
    for table in document.tables:
        # Group the walker's stream back into rows, which it yields in row-major order
        rows: dict[int, list[DocxCell]] = {}
        for cell in walk_docx_cells(table):
            rows.setdefault(cell.row, []).append(cell)

        markup = ["<table>"]
        for row_index in sorted(rows):
            markup.append("<tr>")
            for cell in rows[row_index]:
                spans = ""
                if cell.colspan > 1:
                    spans += f' colspan="{cell.colspan}"'
                if cell.rowspan > 1:
                    spans += f' rowspan="{cell.rowspan}"'
                markup.append(f"<td{spans}>{escape(cell.text)}</td>")
            markup.append("</tr>")
        markup.append("</table>")
        tables.append("".join(markup))

    return tables


# Yield each cell of a docx table once, with its grid position and spans.
def walk_docx_cells(table: Table) -> Iterator[DocxCell]:
    # Index every row by grid column, so a vertical span can be counted down one column
    grid: list[dict[int, tuple[object, int, str | None]]] = []
    for tr in table._tbl.tr_lst:
        column = 0
        row_cells: dict[int, tuple[object, int, str | None]] = {}
        for tc in tr.tc_lst:
            merge = tc.tcPr.vMerge_val if tc.tcPr is not None else None
            row_cells[column] = (tc, tc.grid_span, merge)
            column += tc.grid_span
        grid.append(row_cells)

    for row_index, row_cells in enumerate(grid):
        for column in sorted(row_cells):
            tc, colspan, merge = row_cells[column]

            # A continuation carries no content of its own; its text sits on the restart
            if merge == VMERGE_CONTINUE:
                continue

            # Walk down the same grid column while later rows keep continuing this cell
            rowspan = 1
            for later in grid[row_index + 1 :]:
                entry = later.get(column)
                if entry is None or entry[2] != VMERGE_CONTINUE:
                    break
                rowspan += 1

            yield DocxCell(
                row=row_index,
                column=column,
                colspan=colspan,
                rowspan=rowspan,
                text=_Cell(tc, table).text,
            )


# Find where a pipe-table run starting at this line ends, or None if none starts here.
# style: keep - extract_html_tables is already 45 lines, and this shares no locals with it.
def _pipe_run_end(lines: list[str], start: int) -> int | None:  # style: keep
    # A run needs the start line and a delimiter row directly under it
    if start + 1 >= len(lines) or not lines[start].lstrip().startswith("|"):
        return None

    delimiter = lines[start + 1].lstrip()
    if not delimiter.startswith("|"):
        return None
    if not all(PIPE_DELIMITER_RE.match(cell) for cell in _pipe_cells(delimiter)):
        return None

    end = start + 2
    while end < len(lines) and lines[end].lstrip().startswith("|"):
        end += 1

    return end


# Convert one pipe-table run into HTML, header row first.
# style: keep - called from extract_html_tables only, but inlining it would push that
# function past 60 lines and it shares no locals beyond the run it is handed.
def _pipe_run_to_html(run: list[str]) -> str:  # style: keep
    markup = ["<table>"]

    # The first line is the header; the second is the delimiter and carries no content
    for line_index, line in enumerate(run):
        if line_index == 1:
            continue
        tag = "th" if line_index == 0 else "td"
        cells = "".join(f"<{tag}>{escape(cell)}</{tag}>" for cell in _pipe_cells(line))
        markup.append(f"<tr>{cells}</tr>")

    markup.append("</table>")
    return "".join(markup)


# Split one pipe-table line into its cell texts, honouring escaped pipes.
# style: keep - called from _pipe_run_end and _pipe_run_to_html, in two different passes.
def _pipe_cells(line: str) -> list[str]:  # style: keep
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]

    return [cell.strip().replace("\\|", "|") for cell in PIPE_SPLIT_RE.split(body)]
