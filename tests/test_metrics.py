import pytest

from pawgrab.engine.metrics import Metrics, _Counter, _Histogram


class TestCounter:
    def test_counter_operations(self):
        c = _Counter()
        assert c.value == 0
        c.inc()
        assert c.value == 1
        c.inc(5)
        assert c.value == 6
        c.inc(3)
        c.inc(7)
        assert c.value == 16

    def test_thread_safe_concurrent_increments(self):
        import threading

        c = _Counter()

        def worker():
            for _ in range(1000):
                c.inc()

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert c.value == 10_000


class TestHistogram:
    def test_initial_state(self):
        h = _Histogram()
        assert h.count == 0
        assert h.sum == 0.0

    def test_observe(self):
        h = _Histogram()
        h.observe(1.0)
        h.observe(2.0)
        assert h.count == 2
        assert h.sum == 3.0

    def test_snapshot_has_inf_bucket(self):
        h = _Histogram()
        h.observe(0.1)
        snap = h.snapshot()
        assert "buckets" in snap
        assert snap["buckets"]["+Inf"] == 1

    def test_bucket_cumulative_counts(self):
        h = _Histogram(buckets=(0.5, 1.0, 2.0))
        h.observe(0.3)
        h.observe(0.8)
        h.observe(1.5)
        snap = h.snapshot()
        assert snap["buckets"]["0.5"] == 1
        assert snap["buckets"]["1.0"] == 3
        assert snap["buckets"]["2.0"] == 6
        assert snap["buckets"]["+Inf"] == 3

    def test_snapshot_sum_rounded(self):
        h = _Histogram()
        h.observe(1.0 / 3)
        snap = h.snapshot()
        assert len(str(snap["sum"])) < 10


class TestMetrics:
    @pytest.fixture
    def m(self):
        return Metrics()

    def test_initial_counters_zero(self, m):
        assert m.scrape_total.value == 0
        assert m.extract_total.value == 0
        assert m.crawl_total.value == 0

    def test_domain_success_and_failure(self, m):
        m.record_domain_success("example.com")
        m.record_domain_success("example.com")
        m.record_domain_failure("example.com")
        stats = m.domain_stats()["example.com"]
        assert stats["success"] == 2
        assert stats["failed"] == 1
        assert stats["total"] == 3
        assert round(stats["success_rate"], 3) == round(2 / 3, 3)

    def test_to_prometheus_format(self, m):
        m.scrape_total.inc(3)
        output = m.to_prometheus()
        assert "pawgrab_scrape_total 3" in output
        assert "# TYPE pawgrab_scrape_total counter" in output
        assert "pawgrab_request_duration_seconds" in output
        assert '_bucket{le="' in output
        assert output.endswith("\n")

    def test_to_dict_structure(self, m):
        m.scrape_total.inc(5)
        m.scrape_success.inc(4)
        d = m.to_dict()
        assert d["scrape"]["total"] == 5
        assert d["scrape"]["success"] == 4
        assert "request_duration" in d
        assert "domains" in d

    def test_to_dict_histogram_snapshot(self, m):
        m.scrape_duration.observe(1.5)
        d = m.to_dict()
        assert d["scrape_duration"]["count"] == 1
        assert d["scrape_duration"]["sum"] == 1.5
