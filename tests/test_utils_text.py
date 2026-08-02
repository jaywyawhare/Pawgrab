import pytest

from pawgrab.utils.text import make_soup, tokenize, word_count


class TestTokenize:
    def test_basic_words(self):
        tokens = tokenize("Hello World")
        assert "hello" in tokens
        assert "world" in tokens

    def test_lowercased(self):
        assert all(t == t.lower() for t in tokenize("UPPER lower MiXeD"))

    def test_strips_punctuation(self):
        tokens = tokenize("Hello, world! How are you?")
        assert "hello" in tokens
        assert "world" in tokens
        assert "," not in tokens
        assert "!" not in tokens

    def test_empty_and_punctuation_only(self):
        assert tokenize("") == []
        assert tokenize("!@#$%^&*()") == []

    def test_hyphenated_splits(self):
        tokens = tokenize("well-known fact")
        assert "well" in tokens
        assert "known" in tokens

    def test_alphanumeric_preserved(self):
        tokens = tokenize("abc123 def456")
        assert "abc123" in tokens
        assert "def456" in tokens

    def test_extracts_numbers(self):
        tokens = tokenize("Python 3.11 is great")
        assert "python" in tokens


class TestWordCount:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("", 0),
            ("hello", 1),
            ("one two three four", 4),
            ("  hello world  ", 2),
            ("hello   world", 2),
            ("line1\nline2\nline3", 3),
        ],
    )
    def test_word_count(self, text, expected):
        assert word_count(text) == expected


class TestMakeSoup:
    def test_basic_parsing(self):
        soup = make_soup("<html><body><p>Hello</p></body></html>")
        p = soup.find("p")
        assert p is not None
        assert p.get_text() == "Hello"

    def test_finds_nested_elements(self):
        soup = make_soup("<div><ul><li>item1</li><li>item2</li></ul></div>")
        assert len(soup.find_all("li")) == 2

    def test_empty_and_malformed_html(self):
        assert make_soup("") is not None
        soup = make_soup("<p>unclosed paragraph")
        assert soup.find("p") is not None

    def test_attributes_accessible(self):
        soup = make_soup('<a href="https://example.com" class="link">Click</a>')
        a = soup.find("a")
        assert a["href"] == "https://example.com"
        assert "link" in a["class"]
