"""Tests for the content cleaner."""

from pawgrab.engine.cleaner import extract_content


def test_extract_title():
    html = "<html><head><title>Test Page</title></head><body><p>Hello world</p></body></html>"
    result = extract_content(html)
    assert result.title == "Test Page"


def test_extract_description():
    html = '<html><head><meta name="description" content="A test page"></head><body><p>Content</p></body></html>'
    result = extract_content(html)
    assert result.description == "A test page"


def test_extract_language():
    html = '<html lang="en"><head><title>Test</title></head><body><p>Hello</p></body></html>'
    result = extract_content(html)
    assert result.language == "en"


def test_extract_empty_html():
    result = extract_content("")
    assert result.title == ""
    assert result.content_html is not None


def test_extract_byline_from_meta():
    html = (
        '<html><head>'
        '<meta name="author" content="Jane Doe">'
        '<meta property="article:published_time" content="2025-03-14T09:00:00Z">'
        "</head><body><p>" + "Body text. " * 40 + "</p></body></html>"
    )
    result = extract_content(html)
    assert result.author == "Jane Doe"
    assert result.publish_date.startswith("2025-03-14")


def test_extract_byline_from_json_ld():
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@type":"Article","author":{"name":"John Smith"},"datePublished":"2024-11-02"}'
        "</script></head><body><p>" + "Body text. " * 40 + "</p></body></html>"
    )
    result = extract_content(html)
    assert result.author == "John Smith"
    assert result.publish_date == "2024-11-02"
