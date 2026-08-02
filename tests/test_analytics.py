import threading

import pytest

from pawgrab.engine.analytics import UsageTracker


@pytest.fixture
def tracker():
    return UsageTracker()


def test_record_request(tracker):
    tracker.record_request("client1", "/v1/scrape")
    assert tracker.get_usage("client1")["total_requests"] == 1


def test_unknown_client_defaults_zero(tracker):
    usage = tracker.get_usage("nonexistent")
    assert usage["total_requests"] == 0
    assert usage["client"] == "nonexistent"


def test_multiple_requests(tracker):
    for _ in range(5):
        tracker.record_request("client1", "/v1/scrape")
    assert tracker.get_usage("client1")["total_requests"] == 5


def test_bandwidth_accumulates(tracker):
    tracker.record_request("client1", "/v1/scrape", response_size=1024)
    tracker.record_request("client1", "/v1/scrape", response_size=512)
    assert tracker.get_usage("client1")["total_bandwidth_bytes"] == 1536


def test_error_tracking(tracker):
    tracker.record_request("client1", "/v1/scrape", is_error=True)
    tracker.record_request("client1", "/v1/scrape", is_error=False)
    usage = tracker.get_usage("client1")
    assert usage["total_errors"] == 1
    assert usage["error_rate"] == 0.5


def test_endpoint_counts(tracker):
    tracker.record_request("client1", "/v1/scrape")
    tracker.record_request("client1", "/v1/scrape")
    tracker.record_request("client1", "/v1/extract")
    endpoints = tracker.get_usage("client1")["endpoints"]
    assert endpoints["/v1/scrape"] == 2
    assert endpoints["/v1/extract"] == 1


def test_timestamps_set(tracker):
    tracker.record_request("client1", "/v1/scrape")
    usage = tracker.get_usage("client1")
    assert usage["first_seen"] > 0
    assert usage["last_seen"] >= usage["first_seen"]


def test_get_all_usage(tracker):
    tracker.record_request("alpha", "/v1/scrape")
    tracker.record_request("beta", "/v1/scrape")
    all_usage = tracker.get_all_usage()
    assert len(all_usage) == 2
    assert {u["client"] for u in all_usage} == {"alpha", "beta"}


def test_get_all_usage_sorted(tracker):
    tracker.record_request("z_client", "/v1/scrape")
    tracker.record_request("a_client", "/v1/scrape")
    all_usage = tracker.get_all_usage()
    assert all_usage[0]["client"] == "a_client"


def test_summary_aggregate(tracker):
    tracker.record_request("c1", "/v1/scrape", response_size=100)
    tracker.record_request("c2", "/v1/scrape", response_size=200, is_error=True)
    summary = tracker.get_summary()
    assert summary["total_requests"] == 2
    assert summary["total_bandwidth_bytes"] == 300
    assert summary["total_errors"] == 1
    assert summary["unique_clients"] == 2


def test_summary_top_clients(tracker):
    for _ in range(10):
        tracker.record_request("power_user", "/v1/scrape")
    tracker.record_request("light_user", "/v1/scrape")
    top = tracker.get_summary()["top_clients"]
    assert top[0]["client"] == "power_user"
    assert top[0]["requests"] == 10


def test_summary_endpoint_totals(tracker):
    tracker.record_request("c1", "/v1/scrape")
    tracker.record_request("c2", "/v1/scrape")
    tracker.record_request("c1", "/v1/extract")
    endpoints = tracker.get_summary()["endpoints"]
    assert endpoints["/v1/scrape"] == 2
    assert endpoints["/v1/extract"] == 1


def test_summary_empty(tracker):
    summary = tracker.get_summary()
    assert summary["total_requests"] == 0
    assert summary["unique_clients"] == 0
    assert summary["error_rate"] == 0.0


def test_thread_safety(tracker):
    def record():
        for _ in range(100):
            tracker.record_request("shared_client", "/v1/scrape")

    threads = [threading.Thread(target=record) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert tracker.get_usage("shared_client")["total_requests"] == 500
