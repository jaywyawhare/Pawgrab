"""Pawgrab — web scraping API.

Public API::

    from pawgrab import scrape_url, fetch_page, extract_from_url
    from pawgrab import html_to_markdown, extract_content, convert
    from pawgrab import OutputFormat, PawgrabError, ErrorCode
"""

from pawgrab._version import __version__


def __getattr__(name: str):
    _exports = {
        "scrape_url": ("pawgrab.engine.scrape_service", "scrape_url"),
        "fetch_page": ("pawgrab.engine.fetcher", "fetch_page"),
        "FetchResult": ("pawgrab.engine.fetcher", "FetchResult"),
        "extract_content": ("pawgrab.engine.cleaner", "extract_content"),
        "CleanedContent": ("pawgrab.engine.cleaner", "CleanedContent"),
        "convert": ("pawgrab.engine.converter", "convert"),
        "html_to_markdown": ("pawgrab.engine.converter", "html_to_markdown"),
        "html_to_text": ("pawgrab.engine.converter", "html_to_text"),
        "html_to_json": ("pawgrab.engine.converter", "html_to_json"),
        "extract_from_url": ("pawgrab.ai.extractor", "extract_from_url"),
        "OutputFormat": ("pawgrab.models.common", "OutputFormat"),
        "PawgrabError": ("pawgrab.exceptions", "PawgrabError"),
        "ErrorCode": ("pawgrab.exceptions", "ErrorCode"),
    }
    if name in _exports:
        module_path, attr = _exports[name]
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)
    raise AttributeError(f"module 'pawgrab' has no attribute {name!r}")


__all__ = [
    "__version__",
    "scrape_url",
    "fetch_page",
    "FetchResult",
    "extract_content",
    "CleanedContent",
    "convert",
    "html_to_markdown",
    "html_to_text",
    "html_to_json",
    "extract_from_url",
    "OutputFormat",
    "PawgrabError",
    "ErrorCode",
]
