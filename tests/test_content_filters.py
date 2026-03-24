"""Tests for Phase 1: Content processing — filters, tag exclusion, CSS scoping."""

from pawgrab.engine.filters import BM25ContentFilter, PruningContentFilter


class TestPruningContentFilter:
    def test_removes_nav_footer(self):
        html = """
        <html><body>
            <nav><a href="/">Home</a><a href="/about">About</a></nav>
            <article><p>Main article content here with enough words to pass.</p></article>
            <footer><p>Copyright 2024</p></footer>
        </body></html>
        """
        f = PruningContentFilter()
        result = f.filter_html(html)
        assert "Main article content" in result
        assert "<nav>" not in result
        assert "<footer>" not in result

    def test_removes_sidebar_by_class(self):
        html = """
        <div>
            <div class="sidebar"><p>Side content</p></div>
            <div class="main"><p>Important content for the reader to see.</p></div>
        </div>
        """
        f = PruningContentFilter()
        result = f.filter_html(html)
        assert "Side content" not in result

    def test_empty_html_passthrough(self):
        f = PruningContentFilter()
        assert f.filter_html("") == ""
        assert f.filter_html("   ") == "   "

    def test_preserves_content_rich_elements(self):
        html = """
        <div>
            <p>This is a substantial paragraph with enough text density to pass the filter
            and remain in the output document.</p>
        </div>
        """
        f = PruningContentFilter()
        result = f.filter_html(html)
        assert "substantial paragraph" in result


class TestBM25ContentFilter:
    def test_filters_by_query_relevance(self):
        html = """
        <div>
            <p>Python is a great programming language for machine learning and data science.</p>
            <p>The weather today is sunny with clear skies across the region.</p>
            <p>Python frameworks like Django and Flask are popular for web development.</p>
        </div>
        """
        f = BM25ContentFilter(query="python programming", top_k=2)
        result = f.filter_html(html)
        assert "Python" in result
        assert "programming" in result

    def test_returns_original_on_empty_query(self):
        html = "<p>Some content here</p>"
        f = BM25ContentFilter(query="", top_k=5)
        result = f.filter_html(html)
        assert "Some content" in result

    def test_handles_empty_html(self):
        f = BM25ContentFilter(query="test")
        assert f.filter_html("") == ""


class TestCleanerPreprocessing:
    def test_excluded_tags(self):
        from pawgrab.engine.cleaner import _preprocess

        html = "<html><body><nav>nav</nav><p>content</p><footer>foot</footer></body></html>"
        result = _preprocess(html, excluded_tags=["nav", "footer"], excluded_selector=None, css_selector=None)
        assert "<nav>" not in result
        assert "<footer>" not in result
        assert "content" in result

    def test_excluded_selector(self):
        from pawgrab.engine.cleaner import _preprocess

        html = '<html><body><div class="ads">ad</div><p>real</p></body></html>'
        result = _preprocess(html, excluded_tags=None, excluded_selector=".ads", css_selector=None)
        assert "ad" not in result
        assert "real" in result

    def test_css_scoping(self):
        from pawgrab.engine.cleaner import _preprocess

        html = '<html><body><div class="main"><p>keep</p></div><div class="extra"><p>remove</p></div></body></html>'
        result = _preprocess(html, excluded_tags=None, excluded_selector=None, css_selector=".main")
        assert "keep" in result

    def test_no_filters_passthrough(self):
        from pawgrab.engine.cleaner import _preprocess

        html = "<p>untouched</p>"
        result = _preprocess(html, None, None, None)
        assert result == html

    def test_word_count_threshold(self):
        from pawgrab.engine.cleaner import _apply_word_count_threshold

        html = "<div><p>short</p><p>This paragraph has enough words to pass the threshold check easily.</p></div>"
        result = _apply_word_count_threshold(html, threshold=5)
        assert "enough words" in result
        assert ">short<" not in result
