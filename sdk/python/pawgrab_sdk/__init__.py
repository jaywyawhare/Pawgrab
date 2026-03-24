"""Pawgrab Python SDK — official client for the Pawgrab web scraping API."""

from pawgrab_sdk.client import PawgrabClient
from pawgrab_sdk.models import CrawlOptions, ExtractOptions, ScrapeOptions, SearchOptions

__version__ = "0.2.0"
__all__ = ["PawgrabClient", "ScrapeOptions", "ExtractOptions", "CrawlOptions", "SearchOptions"]
