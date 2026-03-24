"""Prometheus-compatible metrics collection."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock


class _Counter:
    __slots__ = ("_value", "_lock")

    def __init__(self):
        self._value = 0
        self._lock = Lock()

    def inc(self, n: int = 1):
        with self._lock:
            self._value += n

    @property
    def value(self) -> int:
        return self._value


class _Histogram:
    __slots__ = ("_sum", "_count", "_buckets", "_bucket_bounds", "_lock")

    def __init__(self, buckets: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)):
        self._sum = 0.0
        self._count = 0
        self._bucket_bounds = buckets
        self._buckets = [0] * len(buckets)
        self._lock = Lock()

    def observe(self, value: float):
        with self._lock:
            self._sum += value
            self._count += 1
            for i, bound in enumerate(self._bucket_bounds):
                if value <= bound:
                    self._buckets[i] += 1

    @property
    def count(self) -> int:
        return self._count

    @property
    def sum(self) -> float:
        return self._sum

    def snapshot(self) -> dict:
        with self._lock:
            cumulative = 0
            buckets = {}
            for i, bound in enumerate(self._bucket_bounds):
                cumulative += self._buckets[i]
                buckets[str(bound)] = cumulative
            buckets["+Inf"] = self._count
            return {"count": self._count, "sum": round(self._sum, 4), "buckets": buckets}


class Metrics:
    """Application-wide metrics singleton."""

    def __init__(self):
        self.scrape_total = _Counter()
        self.scrape_success = _Counter()
        self.scrape_failed = _Counter()
        self.scrape_cached = _Counter()
        self.extract_total = _Counter()
        self.extract_success = _Counter()
        self.extract_failed = _Counter()
        self.crawl_total = _Counter()
        self.crawl_pages = _Counter()
        self.batch_total = _Counter()
        self.search_total = _Counter()
        self.captcha_detected = _Counter()
        self.captcha_solved = _Counter()
        self.browser_sessions = _Counter()
        self.request_duration = _Histogram()
        self.scrape_duration = _Histogram()
        self._domain_success: dict[str, int] = defaultdict(int)
        self._domain_failure: dict[str, int] = defaultdict(int)
        self._lock = Lock()

    def record_domain_success(self, domain: str):
        with self._lock:
            self._domain_success[domain] += 1

    def record_domain_failure(self, domain: str):
        with self._lock:
            self._domain_failure[domain] += 1

    def domain_stats(self) -> dict:
        with self._lock:
            domains = set(self._domain_success) | set(self._domain_failure)
            stats = {}
            for d in sorted(domains):
                s = self._domain_success.get(d, 0)
                f = self._domain_failure.get(d, 0)
                total = s + f
                stats[d] = {"success": s, "failed": f, "total": total, "success_rate": round(s / total, 3) if total > 0 else 0}
            return stats

    def to_prometheus(self) -> str:
        """Export metrics in Prometheus text exposition format."""
        lines = []

        def _counter(name: str, help_text: str, value: int):
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {value}")

        def _histogram(name: str, help_text: str, hist: _Histogram):
            snap = hist.snapshot()
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} histogram")
            for bound, count in snap["buckets"].items():
                lines.append(f'{name}_bucket{{le="{bound}"}} {count}')
            lines.append(f"{name}_sum {snap['sum']}")
            lines.append(f"{name}_count {snap['count']}")

        _counter("pawgrab_scrape_total", "Total scrape requests", self.scrape_total.value)
        _counter("pawgrab_scrape_success", "Successful scrape requests", self.scrape_success.value)
        _counter("pawgrab_scrape_failed", "Failed scrape requests", self.scrape_failed.value)
        _counter("pawgrab_scrape_cached", "Cache-hit scrape requests", self.scrape_cached.value)
        _counter("pawgrab_extract_total", "Total extract requests", self.extract_total.value)
        _counter("pawgrab_extract_success", "Successful extract requests", self.extract_success.value)
        _counter("pawgrab_extract_failed", "Failed extract requests", self.extract_failed.value)
        _counter("pawgrab_crawl_total", "Total crawl jobs", self.crawl_total.value)
        _counter("pawgrab_crawl_pages", "Total pages crawled", self.crawl_pages.value)
        _counter("pawgrab_batch_total", "Total batch jobs", self.batch_total.value)
        _counter("pawgrab_search_total", "Total search requests", self.search_total.value)
        _counter("pawgrab_captcha_detected", "CAPTCHAs detected", self.captcha_detected.value)
        _counter("pawgrab_captcha_solved", "CAPTCHAs solved", self.captcha_solved.value)
        _counter("pawgrab_browser_sessions", "Browser sessions opened", self.browser_sessions.value)
        _histogram("pawgrab_request_duration_seconds", "HTTP request duration", self.request_duration)
        _histogram("pawgrab_scrape_duration_seconds", "Scrape pipeline duration", self.scrape_duration)

        return "\n".join(lines) + "\n"

    def to_dict(self) -> dict:
        """Export metrics as a JSON-friendly dict."""
        return {
            "scrape": {
                "total": self.scrape_total.value,
                "success": self.scrape_success.value,
                "failed": self.scrape_failed.value,
                "cached": self.scrape_cached.value,
            },
            "extract": {
                "total": self.extract_total.value,
                "success": self.extract_success.value,
                "failed": self.extract_failed.value,
            },
            "crawl": {"total": self.crawl_total.value, "pages": self.crawl_pages.value},
            "batch": {"total": self.batch_total.value},
            "search": {"total": self.search_total.value},
            "captcha": {"detected": self.captcha_detected.value, "solved": self.captcha_solved.value},
            "browser_sessions": self.browser_sessions.value,
            "request_duration": self.request_duration.snapshot(),
            "scrape_duration": self.scrape_duration.snapshot(),
            "domains": self.domain_stats(),
        }


# Global singleton
metrics = Metrics()
