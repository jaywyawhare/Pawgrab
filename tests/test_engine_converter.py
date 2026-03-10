"""Tests for HTML conversion."""

from pawgrab.engine.converter import convert, html_to_markdown, html_to_text, word_count
from pawgrab.models.common import OutputFormat


def test_html_to_markdown():
    html = "<h1>Title</h1><p>Some paragraph text.</p>"
    md = html_to_markdown(html)
    assert "# Title" in md
    assert "Some paragraph text." in md


def test_html_to_text():
    html = "<h1>Title</h1><p>Some paragraph text.</p>"
    text = html_to_text(html)
    assert "Title" in text
    assert "Some paragraph text." in text
    assert "<" not in text


def test_convert_markdown():
    html = "<p>Hello world</p>"
    result = convert(html, OutputFormat.MARKDOWN)
    assert "Hello world" in result


def test_convert_html_passthrough():
    html = "<p>Hello world</p>"
    result = convert(html, OutputFormat.HTML)
    assert result == html


def test_convert_text():
    html = "<p>Hello world</p>"
    result = convert(html, OutputFormat.TEXT)
    assert "Hello world" in result
    assert "<p>" not in result


def test_convert_json():
    html = "<h1>Heading</h1><p>Content here</p>"
    result = convert(html, OutputFormat.JSON)
    assert "Heading" in result
    assert "Content here" in result


def test_word_count():
    assert word_count("hello world foo bar") == 4
    assert word_count("") == 0
