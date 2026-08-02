import pytest

from pawgrab.engine.url_filter import (
    ContentTypeFilter,
    DomainFilter,
    DuplicateFilter,
    FilterChain,
    PathFilter,
)


class TestDomainFilter:
    def test_allows_all_when_no_config(self):
        assert DomainFilter().accept("https://anything.com/page") is True

    def test_allowed_domains(self):
        f = DomainFilter(allowed_domains=["example.com"])
        assert f.accept("https://example.com/page") is True
        assert f.accept("https://other.com/page") is False

    def test_blocked_domains(self):
        f = DomainFilter(blocked_domains=["evil.com"])
        assert f.accept("https://evil.com/page") is False
        assert f.accept("https://good.com/page") is True

    def test_blocked_takes_precedence_over_allowed(self):
        f = DomainFilter(allowed_domains=["example.com"], blocked_domains=["example.com"])
        assert f.accept("https://example.com/page") is False

    def test_multiple_allowed_domains(self):
        f = DomainFilter(allowed_domains=["a.com", "b.com"])
        assert f.accept("https://a.com/") is True
        assert f.accept("https://b.com/") is True
        assert f.accept("https://c.com/") is False

    def test_case_insensitive(self):
        f = DomainFilter(allowed_domains=["example.com"])
        assert f.accept("https://EXAMPLE.COM/page") is True


class TestPathFilter:
    def test_accepts_all_when_no_config(self):
        assert PathFilter().accept("https://example.com/any/path") is True

    def test_include_pattern(self):
        f = PathFilter(include_patterns=[r"/blog/"])
        assert f.accept("https://example.com/blog/post") is True
        assert f.accept("https://example.com/shop/item") is False

    def test_exclude_pattern(self):
        f = PathFilter(exclude_patterns=[r"\.pdf$"])
        assert f.accept("https://example.com/doc.pdf") is False
        assert f.accept("https://example.com/page.html") is True

    def test_exclude_overrides_include(self):
        f = PathFilter(include_patterns=[r"/docs/"], exclude_patterns=[r"\.pdf$"])
        assert f.accept("https://example.com/docs/guide.pdf") is False

    def test_multiple_include_patterns_any_match(self):
        f = PathFilter(include_patterns=[r"/blog/", r"/news/"])
        assert f.accept("https://example.com/blog/post") is True
        assert f.accept("https://example.com/news/article") is True
        assert f.accept("https://example.com/shop/item") is False


class TestContentTypeFilter:
    def test_accepts_html_pages(self):
        f = ContentTypeFilter()
        assert f.accept("https://example.com/page") is True
        assert f.accept("https://example.com/article.html") is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/photo.jpg",
            "https://example.com/img.png",
            "https://example.com/animation.gif",
            "https://example.com/app.exe",
            "https://example.com/archive.zip",
            "https://example.com/style.css",
            "https://example.com/script.js",
        ],
    )
    def test_blocks_binary_and_media_by_default(self, url):
        assert ContentTypeFilter().accept(url) is False

    def test_allows_custom_extension(self):
        f = ContentTypeFilter(allowed_extensions={".htm"})
        assert f.accept("https://example.com/page.htm") is True
        assert f.accept("https://example.com/page.php") is False

    def test_custom_blocked_overrides_default(self):
        f = ContentTypeFilter(blocked_extensions={".html"})
        assert f.accept("https://example.com/page.html") is False
        assert f.accept("https://example.com/photo.jpg") is True

    def test_no_extension_accepted(self):
        assert ContentTypeFilter().accept("https://example.com/api/v1/data") is True


class TestDuplicateFilter:
    def test_first_url_accepted(self):
        assert DuplicateFilter().accept("https://example.com/page") is True

    def test_duplicate_rejected(self):
        f = DuplicateFilter()
        f.accept("https://example.com/page")
        assert f.accept("https://example.com/page") is False

    def test_different_urls_both_accepted(self):
        f = DuplicateFilter()
        assert f.accept("https://example.com/a") is True
        assert f.accept("https://example.com/b") is True

    def test_trailing_slash_normalized(self):
        f = DuplicateFilter()
        f.accept("https://example.com/page/")
        assert f.accept("https://example.com/page") is False

    def test_seen_count_and_reset(self):
        f = DuplicateFilter()
        f.accept("https://example.com/a")
        f.accept("https://example.com/b")
        assert f.seen_count == 2
        f.reset()
        assert f.seen_count == 0
        assert f.accept("https://example.com/a") is True

    def test_query_string_preserved(self):
        f = DuplicateFilter()
        f.accept("https://example.com/search?q=test")
        assert f.accept("https://example.com/search?q=test") is False
        assert f.accept("https://example.com/search?q=other") is True


class TestFilterChain:
    def test_empty_chain_accepts_all(self):
        assert FilterChain().accept("https://example.com/page") is True

    def test_all_filters_must_pass(self):
        chain = FilterChain(
            [
                DomainFilter(allowed_domains=["example.com"]),
                PathFilter(include_patterns=[r"/blog/"]),
            ]
        )
        assert chain.accept("https://example.com/blog/post") is True
        assert chain.accept("https://other.com/blog/post") is False
        assert chain.accept("https://example.com/shop/item") is False

    def test_add_returns_self_for_chaining(self):
        chain = FilterChain()
        assert chain.add(DuplicateFilter()) is chain

    def test_add_filter_works(self):
        chain = FilterChain()
        chain.add(DuplicateFilter())
        assert chain.accept("https://example.com/page") is True
        assert chain.accept("https://example.com/page") is False

    def test_single_blocking_filter_rejects(self):
        assert FilterChain([ContentTypeFilter()]).accept("https://example.com/image.jpg") is False
