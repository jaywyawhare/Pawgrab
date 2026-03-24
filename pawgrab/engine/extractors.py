"""CSS, XPath, and Regex extraction strategies."""

from __future__ import annotations

import concurrent.futures
import re
from typing import Any

from bs4 import BeautifulSoup, Tag
from lxml import etree

from pawgrab.utils.text import make_soup

_REGEX_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def _safe_findall(pattern: str, text: str, timeout: int) -> list:
    """re.findall with a thread-based timeout to prevent catastrophic backtracking."""
    try:
        future = _REGEX_POOL.submit(re.findall, pattern, text, re.MULTILINE | re.DOTALL)
        return future.result(timeout=timeout)
    except (concurrent.futures.TimeoutError, re.error):
        return []


def _safe_finditer(pattern: str, text: str, timeout: int) -> list[re.Match]:
    """re.finditer with a thread-based timeout. Returns list since threads can't yield."""
    try:
        future = _REGEX_POOL.submit(lambda: list(re.finditer(pattern, text, re.MULTILINE | re.DOTALL)))
        return future.result(timeout=timeout)
    except (concurrent.futures.TimeoutError, re.error):
        return []


class BaseExtractor:
    """Abstract base for extraction strategies."""

    def extract(self, html: str) -> list[dict[str, Any]]:
        raise NotImplementedError


class CSSExtractor(BaseExtractor):
    """Extract structured data using CSS selectors.

    Config format:
        selectors = {
            "field_name": "css_selector",
            ...
        }
    Or a list of selector groups for repeated elements:
        selectors = {
            "container": "div.product",
            "fields": {
                "name": "h2.title",
                "price": "span.price",
                "link": {"selector": "a", "attribute": "href"},
            }
        }
    """

    def __init__(self, selectors: dict[str, Any]):
        self.selectors = selectors

    def extract(self, html: str) -> list[dict[str, Any]]:
        soup = make_soup(html)

        if "container" in self.selectors and "fields" in self.selectors:
            return self._extract_repeated(soup)
        return [self._extract_fields(soup, self.selectors)]

    def _extract_repeated(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        containers = soup.select(self.selectors["container"])
        fields = self.selectors["fields"]
        results = []
        for container in containers:
            row = self._extract_fields(container, fields)
            if any(v is not None for v in row.values()):
                results.append(row)
        return results

    def _extract_fields(self, element: BeautifulSoup | Tag, fields: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, selector in fields.items():
            if isinstance(selector, dict):
                css = selector.get("selector", "")
                attr = selector.get("attribute")
                all_matches = selector.get("all", False)
                els = element.select(css)
                if all_matches:
                    result[name] = [self._get_value(el, attr) for el in els]
                elif els:
                    result[name] = self._get_value(els[0], attr)
                else:
                    result[name] = None
            else:
                els = element.select(selector)
                result[name] = els[0].get_text(strip=True) if els else None
        return result

    @staticmethod
    def _get_value(el: Tag, attribute: str | None = None) -> str | None:
        if attribute:
            return el.get(attribute)
        return el.get_text(strip=True)


class XPathExtractor(BaseExtractor):
    """Extract data using XPath queries.

    Config format:
        xpath_queries = {
            "field_name": "//xpath/expression",
            ...
        }
    """

    def __init__(self, xpath_queries: dict[str, str]):
        self.xpath_queries = xpath_queries

    def extract(self, html: str) -> list[dict[str, Any]]:
        try:
            tree = etree.HTML(html)
        except Exception:
            return [{}]

        if tree is None:
            return [{}]

        result: dict[str, Any] = {}
        for name, xpath in self.xpath_queries.items():
            try:
                matches = tree.xpath(xpath)
                if not matches:
                    result[name] = None
                elif len(matches) == 1:
                    result[name] = self._node_to_text(matches[0])
                else:
                    result[name] = [self._node_to_text(m) for m in matches]
            except etree.XPathError:
                result[name] = None

        return [result]

    @staticmethod
    def _node_to_text(node: Any) -> str:
        if isinstance(node, str):
            return node
        if hasattr(node, "text"):
            text = node.text or ""
            tail = node.tail or ""
            children = "".join(etree.tostring(c, encoding="unicode", method="text") for c in node)
            return (text + children + tail).strip()
        return str(node)


class RegexExtractor(BaseExtractor):
    """Extract data using regex patterns with named groups.

    Config format:
        patterns = {
            "field_name": r"regex_pattern",
            ...
        }
    Or a single pattern with named groups:
        patterns = r"(?P<name>\\w+)\\s+(?P<value>\\d+)"
    """

    _REGEX_TIMEOUT = 5

    def __init__(self, patterns: dict[str, str] | str):
        if isinstance(patterns, dict):
            for name, p in patterns.items():
                try:
                    re.compile(p)
                except re.error as exc:
                    raise ValueError(f"Invalid regex for '{name}': {exc}") from exc
        else:
            try:
                re.compile(patterns)
            except re.error as exc:
                raise ValueError(f"Invalid regex pattern: {exc}") from exc
        self.patterns = patterns

    def extract(self, html: str) -> list[dict[str, Any]]:
        soup = make_soup(html)
        text = soup.get_text(separator="\n", strip=True)

        if isinstance(self.patterns, str):
            return self._extract_single_pattern(text, self.patterns)

        result: dict[str, Any] = {}
        for name, pattern in self.patterns.items():
            matches = _safe_findall(pattern, text, self._REGEX_TIMEOUT)
            if not matches:
                result[name] = None
            elif len(matches) == 1:
                result[name] = matches[0]
            else:
                result[name] = matches
        return [result]

    def _extract_single_pattern(self, text: str, pattern: str) -> list[dict[str, Any]]:
        results = []
        for m in _safe_finditer(pattern, text, self._REGEX_TIMEOUT):
            if m.groupdict():
                results.append(m.groupdict())
            elif m.groups():
                results.append({"match": m.groups()})
            else:
                results.append({"match": m.group(0)})
        return results or [{}]


def auto_generate_schema(data: list[dict[str, Any]] | dict[str, Any]) -> dict[str, Any]:
    """Auto-generate a JSON schema from sample extracted data.

    Useful for bootstrapping LLM extraction schemas from CSS/XPath results.
    """
    if isinstance(data, list):
        if not data:
            return {"type": "array", "items": {"type": "object"}}
        sample = data[0]
        item_schema = _infer_object_schema(sample)
        return {"type": "array", "items": item_schema}
    return _infer_object_schema(data)


def _infer_object_schema(obj: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for key, value in obj.items():
        properties[key] = _infer_type(value)
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties.keys()),
        "additionalProperties": False,
    }


def _infer_type(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": ["string", "null"]}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        if not value:
            return {"type": "array", "items": {"type": "string"}}
        item_type = _infer_type(value[0])
        return {"type": "array", "items": item_type}
    if isinstance(value, dict):
        return _infer_object_schema(value)
    return {"type": "string"}


def get_extractor(
    strategy: str,
    *,
    selectors: dict[str, Any] | None = None,
    xpath_queries: dict[str, str] | None = None,
    patterns: dict[str, str] | str | None = None,
) -> BaseExtractor:
    """Create an extractor instance by strategy name."""
    match strategy:
        case "css":
            if not selectors:
                raise ValueError("CSS strategy requires 'selectors' config")
            return CSSExtractor(selectors)
        case "xpath":
            if not xpath_queries:
                raise ValueError("XPath strategy requires 'xpath_queries' config")
            return XPathExtractor(xpath_queries)
        case "regex":
            if not patterns:
                raise ValueError("Regex strategy requires 'patterns' config")
            return RegexExtractor(patterns)
        case _:
            raise ValueError(f"Unknown extraction strategy: {strategy}")
