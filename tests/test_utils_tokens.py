import pytest

from pawgrab.utils.tokens import estimate_tokens


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", 0),
        ("x", 0),
        ("test", 1),
        ("a" * 400, 100),
        ("{}" * 5, 2),
    ],
)
def test_estimate_tokens_fixed(text, expected):
    assert estimate_tokens(text) == expected


def test_returns_integer():
    assert isinstance(estimate_tokens("some text here"), int)


def test_longer_text_more_tokens():
    assert estimate_tokens("Hello world " * 100) > estimate_tokens("Hello world")


def test_short_english_text_range():
    tokens = estimate_tokens("Hello world this is a test")
    assert 4 <= tokens <= 10


def test_code_higher_token_density_than_prose():
    code = "def foo(): { return (x + y) * (a - b) } " * 20
    prose = "This is a long paragraph of natural language text. " * 20
    code_ratio = estimate_tokens(code) / len(code)
    prose_ratio = estimate_tokens(prose) / len(prose)
    assert code_ratio > prose_ratio


def test_whitespace_only():
    assert estimate_tokens("     ") == 1
