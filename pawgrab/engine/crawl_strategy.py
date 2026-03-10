"""Crawl strategies: BFS, DFS, and BestFirst (priority queue) crawling.

URLScorer scores discovered URLs by relevance heuristics.
Each strategy manages its own frontier and returns the next URL to visit.
"""

from __future__ import annotations

import heapq
import re
from abc import ABC, abstractmethod
from collections import deque
from urllib.parse import urlparse


class URLScorer:
    """Score URLs by relevance heuristics for priority-based crawling.

    Scoring factors:
      - Keyword presence in path/query (configurable)
      - Path depth (shorter = higher priority)
      - Known high-value path patterns
    """

    # Path patterns commonly associated with valuable content
    _HIGH_VALUE_PATTERNS = re.compile(
        r"/(article|blog|post|news|docs|guide|tutorial|product|page|category)",
        re.IGNORECASE,
    )

    _LOW_VALUE_PATTERNS = re.compile(
        r"/(tag|author|comment|feed|rss|print|share|login|register|cart|checkout)",
        re.IGNORECASE,
    )

    def __init__(self, keywords: list[str] | None = None):
        self.keywords = [k.lower() for k in (keywords or [])]

    def score(self, url: str) -> float:
        """Score a URL from 0.0 (low priority) to 1.0 (high priority)."""
        parsed = urlparse(url)
        path = parsed.path.lower()
        score = 0.5  # base score

        # Path depth: shorter paths are generally more important
        depth = path.count("/")
        if depth <= 2:
            score += 0.15
        elif depth >= 5:
            score -= 0.15

        # Keyword presence in URL
        url_lower = url.lower()
        for keyword in self.keywords:
            if keyword in url_lower:
                score += 0.2
                break  # cap keyword bonus

        # High-value path patterns
        if self._HIGH_VALUE_PATTERNS.search(path):
            score += 0.1

        # Low-value path patterns
        if self._LOW_VALUE_PATTERNS.search(path):
            score -= 0.2

        # Penalize URLs with too many query params (usually filters/pagination)
        query_params = parsed.query.count("&") + (1 if parsed.query else 0)
        if query_params > 3:
            score -= 0.1

        return max(0.0, min(1.0, score))


class CrawlStrategy(ABC):
    """Abstract base for crawl strategies."""

    @abstractmethod
    def add(self, url: str, depth: int) -> None:
        """Add a URL to the frontier."""
        ...

    @abstractmethod
    def next(self) -> tuple[str, int] | None:
        """Get the next URL to visit. Returns (url, depth) or None if empty."""
        ...

    @abstractmethod
    def __len__(self) -> int:
        ...

    @property
    def is_empty(self) -> bool:
        return len(self) == 0


class BFSStrategy(CrawlStrategy):
    """Breadth-first search: visit URLs in FIFO order."""

    def __init__(self):
        self._queue: deque[tuple[str, int]] = deque()

    def add(self, url: str, depth: int) -> None:
        self._queue.append((url, depth))

    def next(self) -> tuple[str, int] | None:
        if self._queue:
            return self._queue.popleft()
        return None

    def __len__(self) -> int:
        return len(self._queue)

    def to_list(self) -> list[tuple[str, int]]:
        return list(self._queue)


class DFSStrategy(CrawlStrategy):
    """Depth-first search: visit URLs in LIFO order (deeper pages first)."""

    def __init__(self):
        self._stack: list[tuple[str, int]] = []

    def add(self, url: str, depth: int) -> None:
        self._stack.append((url, depth))

    def next(self) -> tuple[str, int] | None:
        if self._stack:
            return self._stack.pop()
        return None

    def __len__(self) -> int:
        return len(self._stack)

    def to_list(self) -> list[tuple[str, int]]:
        return list(self._stack)


class BestFirstStrategy(CrawlStrategy):
    """Best-first search: visit highest-scored URLs first.

    Uses a max-heap (negated scores for Python's min-heap).
    """

    def __init__(self, scorer: URLScorer | None = None):
        self.scorer = scorer or URLScorer()
        self._heap: list[tuple[float, int, str, int]] = []  # (-score, counter, url, depth)
        self._counter = 0

    def add(self, url: str, depth: int) -> None:
        score = self.scorer.score(url)
        self._counter += 1
        heapq.heappush(self._heap, (-score, self._counter, url, depth))

    def next(self) -> tuple[str, int] | None:
        if self._heap:
            _, _, url, depth = heapq.heappop(self._heap)
            return (url, depth)
        return None

    def __len__(self) -> int:
        return len(self._heap)

    def to_list(self) -> list[tuple[str, int]]:
        return [(url, depth) for _, _, url, depth in self._heap]


def get_strategy(
    name: str,
    *,
    keywords: list[str] | None = None,
) -> CrawlStrategy:
    """Create a crawl strategy by name."""
    match name:
        case "bfs":
            return BFSStrategy()
        case "dfs":
            return DFSStrategy()
        case "best_first":
            scorer = URLScorer(keywords=keywords)
            return BestFirstStrategy(scorer=scorer)
        case _:
            raise ValueError(f"Unknown crawl strategy: {name}")
