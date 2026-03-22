"""Usage analytics tracking per API key."""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

import structlog

logger = structlog.get_logger()


class UsageTracker:
    """Track API usage per client key."""

    def __init__(self):
        self._lock = Lock()
        self._requests: dict[str, int] = defaultdict(int)
        self._bandwidth: dict[str, int] = defaultdict(int)  # bytes
        self._endpoints: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._errors: dict[str, int] = defaultdict(int)
        self._last_seen: dict[str, float] = {}
        self._first_seen: dict[str, float] = {}

    def record_request(self, client_key: str, endpoint: str, response_size: int = 0, is_error: bool = False):
        """Record an API request."""
        now = time.time()
        with self._lock:
            self._requests[client_key] += 1
            self._bandwidth[client_key] += response_size
            self._endpoints[client_key][endpoint] += 1
            self._last_seen[client_key] = now
            if client_key not in self._first_seen:
                self._first_seen[client_key] = now
            if is_error:
                self._errors[client_key] += 1

    def get_usage(self, client_key: str) -> dict:
        """Get usage stats for a specific client."""
        with self._lock:
            if client_key not in self._requests:
                return {"client": client_key, "total_requests": 0}
            return {
                "client": client_key,
                "total_requests": self._requests[client_key],
                "total_bandwidth_bytes": self._bandwidth[client_key],
                "total_errors": self._errors.get(client_key, 0),
                "endpoints": dict(self._endpoints.get(client_key, {})),
                "first_seen": self._first_seen.get(client_key, 0),
                "last_seen": self._last_seen.get(client_key, 0),
                "error_rate": round(self._errors.get(client_key, 0) / max(self._requests[client_key], 1), 4),
            }

    def get_all_usage(self) -> list[dict]:
        """Get usage stats for all clients."""
        with self._lock:
            clients = sorted(self._requests.keys())
        return [self.get_usage(c) for c in clients]

    def get_summary(self) -> dict:
        """Get aggregate usage summary."""
        with self._lock:
            total_requests = sum(self._requests.values())
            total_bandwidth = sum(self._bandwidth.values())
            total_errors = sum(self._errors.values())
            unique_clients = len(self._requests)
            top_clients = sorted(self._requests.items(), key=lambda x: x[1], reverse=True)[:10]
            endpoint_totals: dict[str, int] = defaultdict(int)
            for client_endpoints in self._endpoints.values():
                for ep, count in client_endpoints.items():
                    endpoint_totals[ep] += count

        return {
            "total_requests": total_requests,
            "total_bandwidth_bytes": total_bandwidth,
            "total_errors": total_errors,
            "unique_clients": unique_clients,
            "error_rate": round(total_errors / max(total_requests, 1), 4),
            "top_clients": [{"client": k, "requests": v} for k, v in top_clients],
            "endpoints": dict(sorted(endpoint_totals.items(), key=lambda x: x[1], reverse=True)),
        }


# Global singleton
usage_tracker = UsageTracker()
