"""CSS, XPath, and Regex extraction strategies."""

from __future__ import annotations

import concurrent.futures
import re
from typing import Any

from bs4 import BeautifulSoup, Tag
from lxml import etree

from pawgrab.engine.adaptive import element_signature, find_by_signature
from pawgrab.utils.text import make_soup

try:
    import regex as _regex

    _HAS_REGEX = True
except ImportError:
    _regex = None
    _HAS_REGEX = False
_REGEX_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2)

_MAX_PATTERN_LEN = 2000


def _safe_findall(pattern: str, text: str, timeout: int) -> list:
    """findall that can truly abort on catastrophic backtracking."""
    if _HAS_REGEX:
        try:
            return _regex.findall(pattern, text, _regex.MULTILINE | _regex.DOTALL, timeout=timeout)
        except TimeoutError:
            return []
        except _regex.error:
            return []
    try:
        future = _REGEX_POOL.submit(re.findall, pattern, text, re.MULTILINE | re.DOTALL)
        return future.result(timeout=timeout)
    except (concurrent.futures.TimeoutError, re.error):
        return []


def _safe_finditer(pattern: str, text: str, timeout: int) -> list:
    """finditer that can truly abort on catastrophic backtracking (returns a list)."""
    if _HAS_REGEX:
        try:
            return list(_regex.finditer(pattern, text, _regex.MULTILINE | _regex.DOTALL, timeout=timeout))
        except TimeoutError:
            return []
        except _regex.error:
            return []
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

    def __init__(
        self,
        selectors: dict[str, Any],
        *,
        adaptive: bool = False,
        signatures: dict[str, Any] | None = None,
        min_score: float = 0.6,
    ):
        self.selectors = selectors
        self.adaptive = adaptive
        self.signatures = signatures or {}
        self.min_score = min_score
        # Populated during extract() when adaptive is on.
        self.healed: list[str] = []
        self.learned_signatures: dict[str, Any] = {}

    def extract(self, html: str) -> list[dict[str, Any]]:
        self.healed = []
        self.learned_signatures = {}
        soup = make_soup(html)
        if "container" in self.selectors and "fields" in self.selectors:
            # Repeated-element mode has no single element per field to heal.
            return self._extract_repeated(soup)
        return [self._extract_fields(soup, self.selectors, heal_root=soup)]

    def _extract_repeated(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        containers = soup.select(self.selectors["container"])
        fields = self.selectors["fields"]
        results = []
        for container in containers:
            row = self._extract_fields(container, fields)
            if any(v is not None for v in row.values()):
                results.append(row)
        return results

    def _extract_fields(
        self,
        element: BeautifulSoup | Tag,
        fields: dict[str, Any],
        *,
        heal_root: BeautifulSoup | None = None,
    ) -> dict[str, Any]:
        healing = heal_root is not None and self.adaptive
        result: dict[str, Any] = {}
        for name, selector in fields.items():
            if isinstance(selector, dict):
                css = selector.get("selector", "")
                attr = selector.get("attribute")
                all_matches = selector.get("all", False)
                els = element.select(css)
                if all_matches:
                    result[name] = [self._get_value(el, attr) for el in els]
                    if els and healing:
                        self.learned_signatures[name] = element_signature(els[0])
                elif els:
                    result[name] = self._get_value(els[0], attr)
                    if healing:
                        self.learned_signatures[name] = element_signature(els[0])
                else:
                    result[name] = self._heal(name, attr, heal_root) if healing else None
            else:
                els = element.select(selector)
                if els:
                    result[name] = els[0].get_text(strip=True)
                    if healing:
                        self.learned_signatures[name] = element_signature(els[0])
                else:
                    result[name] = self._heal(name, None, heal_root) if healing else None
        return result

    def _heal(self, name: str, attr: str | None, root: BeautifulSoup) -> str | None:
        """Relocate a drifted field via its stored signature."""
        sig = self.signatures.get(name)
        if not sig:
            return None
        el = find_by_signature(root, sig, min_score=self.min_score)
        if el is None:
            return None
        value = self._get_value(el, attr)
        if value is None:
            # Relocated element lacks the requested attribute — not a real recovery.
            return None
        self.healed.append(name)
        self.learned_signatures[name] = element_signature(el)
        return value

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
                if len(p) > _MAX_PATTERN_LEN:
                    raise ValueError(f"Regex for '{name}' exceeds {_MAX_PATTERN_LEN} chars")
                try:
                    re.compile(p)
                except re.error as exc:
                    raise ValueError(f"Invalid regex for '{name}': {exc}") from exc
        else:
            if len(patterns) > _MAX_PATTERN_LEN:
                raise ValueError(f"Regex pattern exceeds {_MAX_PATTERN_LEN} chars")
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
    adaptive: bool = False,
    signatures: dict[str, Any] | None = None,
    min_score: float = 0.6,
) -> BaseExtractor:
    """Create an extractor instance by strategy name."""
    match strategy:
        case "css":
            if not selectors:
                raise ValueError("CSS strategy requires 'selectors' config")
            return CSSExtractor(selectors, adaptive=adaptive, signatures=signatures, min_score=min_score)
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
