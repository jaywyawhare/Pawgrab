import pytest

from pawgrab.engine.table_extractor import extract_tables, tables_to_csv


class TestExtractTables:
    def test_basic_table(self):
        html = """<table>
  <thead><tr><th>Name</th><th>Age</th></tr></thead>
  <tbody>
    <tr><td>Alice</td><td>30</td></tr>
    <tr><td>Bob</td><td>25</td></tr>
  </tbody>
</table>"""
        tables = extract_tables(html)
        assert len(tables) == 1
        t = tables[0]
        assert t["headers"] == ["Name", "Age"]
        assert t["row_count"] == 2
        assert t["column_count"] == 2
        assert t["rows"][0] == {"Name": "Alice", "Age": "30"}
        assert t["rows"][1] == {"Name": "Bob", "Age": "25"}

    def test_caption(self):
        html = """<table>
  <caption>Employee Data</caption>
  <tr><th>ID</th><th>Role</th></tr>
  <tr><td>1</td><td>Engineer</td></tr>
</table>"""
        assert extract_tables(html)[0]["caption"] == "Employee Data"

    def test_th_rows_without_thead(self):
        html = """<table>
  <tr><th>Col1</th><th>Col2</th></tr>
  <tr><td>val1</td><td>val2</td></tr>
</table>"""
        t = extract_tables(html)[0]
        assert t["headers"] == ["Col1", "Col2"]
        assert t["row_count"] == 1

    def test_multiple_tables_indexed(self):
        html = """
<table><tr><th>A</th></tr><tr><td>1</td></tr></table>
<table><tr><th>B</th></tr><tr><td>2</td></tr></table>
"""
        tables = extract_tables(html)
        assert len(tables) == 2
        assert tables[0]["index"] == 0
        assert tables[1]["index"] == 1

    def test_select_by_index(self):
        html = """
<table><tr><th>First</th></tr><tr><td>a</td></tr></table>
<table><tr><th>Second</th></tr><tr><td>b</td></tr></table>
"""
        tables = extract_tables(html, table_index=1)
        assert len(tables) == 1
        assert tables[0]["headers"] == ["Second"]

    def test_index_out_of_range(self):
        assert extract_tables("<table><tr><td>only one</td></tr></table>", table_index=5) == []

    @pytest.mark.parametrize(
        "html",
        [
            "<html><body><p>No tables here</p></body></html>",
            "",
        ],
    )
    def test_no_tables_returns_empty(self, html):
        assert extract_tables(html) == []

    def test_raw_rows_populated(self):
        html = """<table>
  <tr><th>X</th><th>Y</th></tr>
  <tr><td>1</td><td>2</td></tr>
</table>"""
        assert extract_tables(html)[0]["raw_rows"] == [["1", "2"]]

    def test_no_headers(self):
        html = """<table>
  <tbody>
    <tr><td>a</td><td>b</td></tr>
    <tr><td>c</td><td>d</td></tr>
  </tbody>
</table>"""
        t = extract_tables(html)[0]
        assert t["headers"] == []
        assert t["raw_rows"] == [["a", "b"], ["c", "d"]]

    def test_partial_row_maps_available_headers(self):
        html = """<table>
  <tr><th>A</th><th>B</th><th>C</th></tr>
  <tr><td>x</td><td>y</td></tr>
</table>"""
        row = extract_tables(html)[0]["rows"][0]
        assert row["A"] == "x"
        assert row["B"] == "y"


class TestTablesToCSV:
    def test_basic_csv(self):
        tables = [{"caption": None, "headers": ["Name", "Age"], "raw_rows": [["Alice", "30"], ["Bob", "25"]]}]
        lines = tables_to_csv(tables).strip().splitlines()
        assert lines[0] == "Name,Age"
        assert "Alice,30" in lines
        assert "Bob,25" in lines

    def test_caption_as_comment(self):
        tables = [{"caption": "My Table", "headers": ["Col"], "raw_rows": [["val"]]}]
        assert "# My Table" in tables_to_csv(tables)

    def test_multiple_tables_separated(self):
        tables = [
            {"caption": None, "headers": ["A"], "raw_rows": [["1"]]},
            {"caption": None, "headers": ["B"], "raw_rows": [["2"]]},
        ]
        assert "\n\n" in tables_to_csv(tables) or "\r\n\r\n" in tables_to_csv(tables)

    def test_empty_tables(self):
        assert tables_to_csv([]) == ""

    def test_no_headers(self):
        tables = [{"caption": None, "headers": [], "raw_rows": [["a", "b"], ["c", "d"]]}]
        csv = tables_to_csv(tables)
        assert "a,b" in csv
        assert "c,d" in csv
