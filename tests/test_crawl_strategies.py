"""Tests for Phase 4: Crawl strategies and URL filters."""

import pytest

from pawgrab.engine.crawl_strategy import (
    BestFirstStrategy,
    BFSStrategy,
    DFSStrategy,
    URLScorer,
    get_strategy,
)
from pawgrab.engine.url_filter import (
    ContentTypeFilter,
    DomainFilter,
    DuplicateFilter,
    FilterChain,
    PathFilter,
)


class TestURLScorer:
    def test_short_path_higher_score(self):
        scorer = URLScorer()
        short = scorer.score("https://example.com/about")
        deep = scorer.score("https://example.com/a/b/c/d/e/f")
        assert short > deep

    def test_keyword_boost(self):
        scorer = URLScorer(keywords=["python"])
        with_kw = scorer.score("https://example.com/python-tutorial")
        without_kw = scorer.score("https://example.com/cooking-tips")
        assert with_kw > without_kw

    def test_high_value_path(self):
        scorer = URLScorer()
        article = scorer.score("https://example.com/article/great-post")
        login = scorer.score("https://example.com/login")
        assert article > login

    def test_score_bounds(self):
        scorer = URLScorer()
        score = scorer.score("https://example.com/some-page")
        assert 0.0 <= score <= 1.0


class TestBFSStrategy:
    def test_fifo_order(self):
        s = BFSStrategy()
        s.add("http://a.com", 0)
        s.add("http://b.com", 1)
        s.add("http://c.com", 2)
        assert s.next() == ("http://a.com", 0)
        assert s.next() == ("http://b.com", 1)
        assert s.next() == ("http://c.com", 2)

    def test_empty_returns_none(self):
        s = BFSStrategy()
        assert s.next() is None

    def test_len(self):
        s = BFSStrategy()
        s.add("http://a.com", 0)
        assert len(s) == 1


class TestDFSStrategy:
    def test_lifo_order(self):
        s = DFSStrategy()
        s.add("http://a.com", 0)
        s.add("http://b.com", 1)
        s.add("http://c.com", 2)
        assert s.next() == ("http://c.com", 2)
        assert s.next() == ("http://b.com", 1)
        assert s.next() == ("http://a.com", 0)

    def test_empty_returns_none(self):
        s = DFSStrategy()
        assert s.next() is None


class TestBestFirstStrategy:
    def test_highest_score_first(self):
        scorer = URLScorer(keywords=["python"])
        s = BestFirstStrategy(scorer=scorer)
        s.add("https://example.com/cooking", 0)
        s.add("https://example.com/python-guide", 0)
        url, _ = s.next()
        assert "python" in url

    def test_empty_returns_none(self):
        s = BestFirstStrategy()
        assert s.next() is None


class TestStrategyFactory:
    def test_bfs(self):
        s = get_strategy("bfs")
        assert isinstance(s, BFSStrategy)

    def test_dfs(self):
        s = get_strategy("dfs")
        assert isinstance(s, DFSStrategy)

    def test_best_first(self):
        s = get_strategy("best_first", keywords=["test"])
        assert isinstance(s, BestFirstStrategy)

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            get_strategy("unknown")


class TestDomainFilter:
    def test_allowed_domains(self):
        f = DomainFilter(allowed_domains=["example.com"])
        assert f.accept("https://example.com/page")
        assert not f.accept("https://other.com/page")

    def test_blocked_domains(self):
        f = DomainFilter(blocked_domains=["bad.com"])
        assert f.accept("https://good.com/page")
        assert not f.accept("https://bad.com/page")

    def test_no_restrictions(self):
        f = DomainFilter()
        assert f.accept("https://anything.com")


class TestPathFilter:
    def test_include_patterns(self):
        f = PathFilter(include_patterns=[r"/blog/", r"/article/"])
        assert f.accept("https://example.com/blog/post-1")
        assert not f.accept("https://example.com/contact")

    def test_exclude_patterns(self):
        f = PathFilter(exclude_patterns=[r"/admin", r"/login"])
        assert f.accept("https://example.com/blog")
        assert not f.accept("https://example.com/admin/dashboard")


class TestContentTypeFilter:
    def test_blocks_images(self):
        f = ContentTypeFilter()
        assert not f.accept("https://example.com/photo.jpg")
        assert not f.accept("https://example.com/style.css")

    def test_allows_html(self):
        f = ContentTypeFilter()
        assert f.accept("https://example.com/page")
        assert f.accept("https://example.com/page.html")


class TestDuplicateFilter:
    def test_deduplication(self):
        f = DuplicateFilter()
        assert f.accept("https://example.com/page")
        assert not f.accept("https://example.com/page")

    def test_normalizes_trailing_slash(self):
        f = DuplicateFilter()
        assert f.accept("https://example.com/page")
        assert not f.accept("https://example.com/page/")

    def test_reset(self):
        f = DuplicateFilter()
        f.accept("https://example.com/page")
        f.reset()
        assert f.accept("https://example.com/page")


class TestFilterChain:
    def test_all_must_pass(self):
        chain = FilterChain([
            DomainFilter(allowed_domains=["example.com"]),
            PathFilter(exclude_patterns=[r"/admin"]),
        ])
        assert chain.accept("https://example.com/blog")
        assert not chain.accept("https://example.com/admin")
        assert not chain.accept("https://other.com/blog")

    def test_add_method(self):
        chain = FilterChain()
        chain.add(DomainFilter(allowed_domains=["example.com"]))
        assert chain.accept("https://example.com/page")
        assert not chain.accept("https://other.com/page")
