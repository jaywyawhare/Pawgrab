"""Tests for next-page detection used in pagination stitching."""

import pytest

from pawgrab.engine.pagination import find_next_url


def test_rel_next_link_head():
    html = '<html><head><link rel="next" href="/page2"></head></html>'
    assert find_next_url(html, "https://x.com/page1") == "https://x.com/page2"


def test_rel_next_anchor_relative():
    assert find_next_url('<a rel="next" href="p3">go</a>', "https://x.com/dir/p2") == "https://x.com/dir/p3"


@pytest.mark.parametrize(
    "label",
    ["Next", "Next Page", "Next »", "»", "Older Posts", "More"],
)
def test_next_text_variants(label):
    assert find_next_url(f'<a href="/n">{label}</a>', "https://x.com") == "https://x.com/n"


@pytest.mark.parametrize(
    "html",
    [
        '<a href="/p">Previous</a>',
        '<a href="/nd">Nextdoor app</a>',
        '<a href="/x">Home</a>',
        "<p>no links</p>",
        "",
    ],
)
def test_no_false_positive(html):
    assert find_next_url(html, "https://x.com") is None


def test_aria_label():
    assert find_next_url('<a href="/2" aria-label="Next page">›</a>', "https://x.com") == "https://x.com/2"
