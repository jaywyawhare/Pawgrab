"""Dedicated HTML table extraction to structured data."""

from __future__ import annotations

from typing import Any

import structlog
from bs4 import BeautifulSoup

logger = structlog.get_logger()


def _int_attr(value, default: int = 1) -> int:
    try:
        n = int(value)
        return n if n > 0 else default
    except (TypeError, ValueError):
        return default


def _own_rows(table):
    """<tr> elements belonging directly to *table*, not to a nested table."""
    return [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]


def _own_cells(tr):
    """<td>/<th> belonging directly to *tr*, not to a nested table's row."""
    return [c for c in tr.find_all(["td", "th"]) if c.find_parent("tr") is tr]


def _build_grid(table) -> list[list[str]]:
    """Expand a table into a dense grid, honoring colspan and rowspan."""
    occupied: dict[tuple[int, int], str] = {}
    max_col = 0
    for r, tr in enumerate(_own_rows(table)):
        c = 0
        for cell in _own_cells(tr):
            while (r, c) in occupied:
                c += 1
            text = cell.get_text(strip=True)
            cspan = _int_attr(cell.get("colspan"))
            rspan = _int_attr(cell.get("rowspan"))
            for dr in range(rspan):
                for dc in range(cspan):
                    occupied[(r + dr, c + dc)] = text
            c += cspan
            max_col = max(max_col, c)
    if not occupied:
        return []
    n_rows = max(k[0] for k in occupied) + 1
    return [[occupied.get((r, c), "") for c in range(max_col)] for r in range(n_rows)]


def extract_tables(html: str, *, table_index: int | None = None) -> list[dict[str, Any]]:
    """Extract HTML tables into structured data.

    Returns a list of table dicts, each with:
    - headers: list of column header strings
    - rows: list of row dicts (header -> value)
    - raw_rows: list of list of cell values
    - caption: table caption if present
    - index: table index in the page
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []
    tables = soup.find_all("table")
    if table_index is not None:
        if 0 <= table_index < len(tables):
            tables = [tables[table_index]]
        else:
            return []
    results = []
    for idx, table in enumerate(tables):
        caption_tag = table.find("caption")
        caption = caption_tag.get_text(strip=True) if caption_tag else None
        grid = _build_grid(table)
        if not grid:
            results.append(
                {
                    "index": table_index if table_index is not None else idx,
                    "caption": caption,
                    "headers": [],
                    "rows": [],
                    "raw_rows": [],
                    "row_count": 0,
                    "column_count": 0,
                }
            )
            continue
        column_count = max(len(r) for r in grid)

        first_tr = _own_rows(table)[0] if _own_rows(table) else None
        has_header = bool(table.find("thead")) or (first_tr is not None and any(c.name == "th" for c in _own_cells(first_tr)))
        if has_header:
            headers = grid[0]
            body = grid[1:]
        else:
            headers = []
            body = grid
        raw_rows = body
        row_dicts = []
        if headers:
            for row in body:
                row_dict = {}
                for i, value in enumerate(row):
                    key = headers[i] if i < len(headers) and headers[i] else f"column_{i}"
                    row_dict[key] = value
                row_dicts.append(row_dict)
        results.append(
            {
                "index": table_index if table_index is not None else idx,
                "caption": caption,
                "headers": headers,
                "rows": row_dicts,
                "raw_rows": raw_rows,
                "row_count": len(raw_rows),
                "column_count": column_count,
            }
        )
    return results


def tables_to_csv(tables: list[dict]) -> str:
    """Convert extracted tables to CSV format."""
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    for i, table in enumerate(tables):
        if i > 0:
            writer.writerow([])
        if table.get("caption"):
            writer.writerow([f"# {table['caption']}"])
        if table["headers"]:
            writer.writerow(table["headers"])
        for row in table["raw_rows"]:
            writer.writerow(row)
    return output.getvalue()
