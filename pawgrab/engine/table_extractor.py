"""Dedicated HTML table extraction to structured data."""

from __future__ import annotations

from typing import Any

import structlog
from bs4 import BeautifulSoup

logger = structlog.get_logger()


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

        headers = []
        thead = table.find("thead")
        if thead:
            header_row = thead.find("tr")
            if header_row:
                headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]

        if not headers:
            first_row = table.find("tr")
            if first_row:
                ths = first_row.find_all("th")
                if ths:
                    headers = [th.get_text(strip=True) for th in ths]

        raw_rows = []
        row_dicts = []
        tbody = table.find("tbody") or table
        for tr in tbody.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue

            # Skip header row if we already extracted headers from it
            cell_texts = [cell.get_text(strip=True) for cell in cells]
            if cell_texts == headers:
                continue

            raw_rows.append(cell_texts)

            if headers and len(cell_texts) <= len(headers):
                row_dict = {}
                for i, value in enumerate(cell_texts):
                    key = headers[i] if i < len(headers) else f"column_{i}"
                    row_dict[key] = value
                row_dicts.append(row_dict)
            elif headers:
                row_dict = {headers[i]: cell_texts[i] for i in range(len(headers)) if i < len(cell_texts)}
                row_dicts.append(row_dict)

        results.append(
            {
                "index": table_index if table_index is not None else idx,
                "caption": caption,
                "headers": headers,
                "rows": row_dicts,
                "raw_rows": raw_rows,
                "row_count": len(raw_rows),
                "column_count": len(headers),
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
            writer.writerow([])  # blank line between tables
        if table.get("caption"):
            writer.writerow([f"# {table['caption']}"])
        if table["headers"]:
            writer.writerow(table["headers"])
        for row in table["raw_rows"]:
            writer.writerow(row)

    return output.getvalue()
