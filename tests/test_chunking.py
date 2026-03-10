"""Tests for Phase 3: Content chunking strategies."""

import pytest

from pawgrab.ai.chunking import (
    FixedLengthChunker,
    SemanticChunker,
    SlidingWindowChunker,
    get_chunker,
)


class TestFixedLengthChunker:
    def test_short_text_single_chunk(self):
        chunker = FixedLengthChunker(chunk_size=100)
        text = "This is a short sentence."
        chunks = chunker.chunk(text)
        assert len(chunks) == 1

    def test_splits_at_chunk_size(self):
        chunker = FixedLengthChunker(chunk_size=10)
        # Create text with clear sentence boundaries
        text = "First sentence here. Second sentence here. Third sentence here. Fourth sentence here."
        chunks = chunker.chunk(text)
        assert len(chunks) >= 2

    def test_overlap(self):
        chunker = FixedLengthChunker(chunk_size=10, overlap=5)
        # Multiple sentences so the splitter can find boundaries
        text = "First sentence here today. Second sentence is here. Third one too. Fourth goes. Fifth sentence now. Sixth is last."
        chunks = chunker.chunk(text)
        assert len(chunks) >= 2

    def test_empty_text(self):
        chunker = FixedLengthChunker(chunk_size=10)
        assert chunker.chunk("") == []
        assert chunker.chunk("   ") == []


class TestSlidingWindowChunker:
    def test_short_text_single_chunk(self):
        chunker = SlidingWindowChunker(chunk_size=100)
        text = "Short text here."
        chunks = chunker.chunk(text)
        assert len(chunks) == 1

    def test_overlapping_windows(self):
        chunker = SlidingWindowChunker(chunk_size=10, overlap=3)
        words = ["word"] * 25
        text = " ".join(words)
        chunks = chunker.chunk(text)
        assert len(chunks) >= 3

    def test_empty_text(self):
        chunker = SlidingWindowChunker(chunk_size=10)
        assert chunker.chunk("") == []


class TestSemanticChunker:
    def test_splits_at_headings(self):
        chunker = SemanticChunker(chunk_size=100)
        text = "# Heading 1\n\nFirst section content.\n\n# Heading 2\n\nSecond section content."
        chunks = chunker.chunk(text)
        assert len(chunks) == 2
        assert "Heading 1" in chunks[0]
        assert "Heading 2" in chunks[1]

    def test_splits_at_paragraphs(self):
        chunker = SemanticChunker(chunk_size=5)
        text = "First paragraph with some words.\n\nSecond paragraph with more words."
        chunks = chunker.chunk(text)
        assert len(chunks) >= 2

    def test_empty_text(self):
        chunker = SemanticChunker(chunk_size=10)
        assert chunker.chunk("") == []


class TestChunkerFactory:
    def test_fixed(self):
        c = get_chunker("fixed", chunk_size=100)
        assert isinstance(c, FixedLengthChunker)

    def test_sliding(self):
        c = get_chunker("sliding", chunk_size=100)
        assert isinstance(c, SlidingWindowChunker)

    def test_semantic(self):
        c = get_chunker("semantic", chunk_size=100)
        assert isinstance(c, SemanticChunker)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown chunking strategy"):
            get_chunker("unknown")
