"""Tests for Phase 2: Extraction strategies — CSS, XPath, Regex, auto-schema."""

import pytest

from pawgrab.engine.extractors import (
    CSSExtractor,
    RegexExtractor,
    XPathExtractor,
    auto_generate_schema,
    get_extractor,
)

SAMPLE_HTML = """
<html><body>
<div class="product">
    <h2 class="title">Widget A</h2>
    <span class="price">$29.99</span>
    <a href="/products/widget-a">Details</a>
</div>
<div class="product">
    <h2 class="title">Widget B</h2>
    <span class="price">$49.99</span>
    <a href="/products/widget-b">Details</a>
</div>
<p>Contact us at support@example.com or sales@example.com</p>
</body></html>
"""


class TestCSSExtractor:
    def test_simple_field_extraction(self):
        ext = CSSExtractor({"first_title": "h2.title"})
        results = ext.extract(SAMPLE_HTML)
        assert len(results) == 1
        assert results[0]["first_title"] == "Widget A"

    def test_repeated_extraction(self):
        ext = CSSExtractor(
            {
                "container": "div.product",
                "fields": {
                    "name": "h2.title",
                    "price": "span.price",
                    "link": {"selector": "a", "attribute": "href"},
                },
            }
        )
        results = ext.extract(SAMPLE_HTML)
        assert len(results) == 2
        assert results[0]["name"] == "Widget A"
        assert results[0]["price"] == "$29.99"
        assert results[0]["link"] == "/products/widget-a"
        assert results[1]["name"] == "Widget B"

    def test_missing_element_returns_none(self):
        ext = CSSExtractor({"missing": "div.nonexistent"})
        results = ext.extract(SAMPLE_HTML)
        assert results[0]["missing"] is None


class TestXPathExtractor:
    def test_basic_xpath(self):
        ext = XPathExtractor(
            {
                "titles": "//h2[@class='title']/text()",
            }
        )
        results = ext.extract(SAMPLE_HTML)
        assert results[0]["titles"] == ["Widget A", "Widget B"]

    def test_single_result(self):
        ext = XPathExtractor(
            {
                "first_price": "(//span[@class='price'])[1]/text()",
            }
        )
        results = ext.extract(SAMPLE_HTML)
        assert results[0]["first_price"] == "$29.99"

    def test_invalid_xpath_returns_none(self):
        ext = XPathExtractor({"bad": "///invalid[["})
        results = ext.extract(SAMPLE_HTML)
        assert results[0]["bad"] is None


class TestRegexExtractor:
    def test_named_patterns(self):
        ext = RegexExtractor(
            {
                "emails": r"[\w.]+@[\w.]+\.\w+",
            }
        )
        results = ext.extract(SAMPLE_HTML)
        assert len(results[0]["emails"]) == 2
        assert "support@example.com" in results[0]["emails"]

    def test_single_pattern_with_groups(self):
        ext = RegexExtractor(r"(?P<name>Widget [A-Z])")
        results = ext.extract(SAMPLE_HTML)
        assert len(results) == 2
        assert results[0]["name"] == "Widget A"
        assert results[1]["name"] == "Widget B"

    def test_no_matches(self):
        ext = RegexExtractor({"phone": r"\d{3}-\d{3}-\d{4}"})
        results = ext.extract(SAMPLE_HTML)
        assert results[0]["phone"] is None


class TestAutoGenerateSchema:
    def test_from_list(self):
        data = [{"name": "Widget", "price": 29.99, "in_stock": True}]
        schema = auto_generate_schema(data)
        assert schema["type"] == "array"
        assert schema["items"]["properties"]["name"]["type"] == "string"
        assert schema["items"]["properties"]["price"]["type"] == "number"
        assert schema["items"]["properties"]["in_stock"]["type"] == "boolean"

    def test_from_dict(self):
        data = {"title": "Test", "count": 5}
        schema = auto_generate_schema(data)
        assert schema["type"] == "object"
        assert "title" in schema["properties"]

    def test_nested_types(self):
        data = {"tags": ["a", "b"], "nested": {"key": "val"}}
        schema = auto_generate_schema(data)
        assert schema["properties"]["tags"]["type"] == "array"
        assert schema["properties"]["nested"]["type"] == "object"

    def test_null_values(self):
        data = {"field": None}
        schema = auto_generate_schema(data)
        assert "null" in schema["properties"]["field"]["type"]


class TestExtractorFactory:
    def test_css_factory(self):
        ext = get_extractor("css", selectors={"title": "h1"})
        assert isinstance(ext, CSSExtractor)

    def test_xpath_factory(self):
        ext = get_extractor("xpath", xpath_queries={"title": "//h1/text()"})
        assert isinstance(ext, XPathExtractor)

    def test_regex_factory(self):
        ext = get_extractor("regex", patterns={"num": r"\d+"})
        assert isinstance(ext, RegexExtractor)

    def test_unknown_strategy_raises(self):
        with pytest.raises(ValueError, match="Unknown extraction strategy"):
            get_extractor("unknown")

    def test_missing_config_raises(self):
        with pytest.raises(ValueError, match="requires"):
            get_extractor("css")
