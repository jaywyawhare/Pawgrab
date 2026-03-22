"""Content chunking strategies for large-page extraction."""

from __future__ import annotations

import re


class FixedLengthChunker:
    """Split text into chunks of approximately `chunk_size` words.

    Splits at sentence boundaries when possible.
    """

    def __init__(self, chunk_size: int = 1000, overlap: int = 0):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str) -> list[str]:
        sentences = _split_sentences(text)
        if not sentences:
            return [text] if text.strip() else []

        chunks: list[str] = []
        current: list[str] = []
        current_words = 0

        for sentence in sentences:
            words = len(sentence.split())
            if current_words + words > self.chunk_size and current:
                chunks.append(" ".join(current))
                if self.overlap > 0:
                    overlap_sentences: list[str] = []
                    overlap_words = 0
                    for s in reversed(current):
                        sw = len(s.split())
                        if overlap_words + sw > self.overlap:
                            break
                        overlap_sentences.insert(0, s)
                        overlap_words += sw
                    current = overlap_sentences
                    current_words = overlap_words
                else:
                    current = []
                    current_words = 0
            current.append(sentence)
            current_words += words

        if current:
            chunks.append(" ".join(current))

        return chunks


class SlidingWindowChunker:
    """Overlapping sliding window chunks.

    Each chunk has `chunk_size` words with `overlap` words overlapping
    between adjacent chunks.
    """

    def __init__(self, chunk_size: int = 1000, overlap: int = 200):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str) -> list[str]:
        words = text.split()
        if len(words) <= self.chunk_size:
            return [text] if text.strip() else []

        step = max(self.chunk_size - self.overlap, 1)
        chunks: list[str] = []
        for i in range(0, len(words), step):
            chunk_words = words[i:i + self.chunk_size]
            if chunk_words:
                chunks.append(" ".join(chunk_words))
            if i + self.chunk_size >= len(words):
                break

        return chunks


class SemanticChunker:
    """Split at topic boundaries using sentence-level similarity.

    Uses a lightweight approach: splits at paragraph/heading boundaries
    and merges small paragraphs until chunk_size is reached.
    This avoids requiring heavy embedding models.
    """

    def __init__(self, chunk_size: int = 1000):
        self.chunk_size = chunk_size

    def chunk(self, text: str) -> list[str]:
        paragraphs = re.split(r"\n\s*\n|(?=^#{1,6}\s)", text, flags=re.MULTILINE)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        if not paragraphs:
            return [text] if text.strip() else []

        chunks: list[str] = []
        current: list[str] = []
        current_words = 0

        for para in paragraphs:
            words = len(para.split())
            is_heading = para.startswith("#")
            if is_heading and current and current_words > 0:
                chunks.append("\n\n".join(current))
                current = []
                current_words = 0

            if current_words + words > self.chunk_size and current:
                chunks.append("\n\n".join(current))
                current = []
                current_words = 0

            current.append(para)
            current_words += words

        if current:
            chunks.append("\n\n".join(current))

        return chunks


def get_chunker(
    strategy: str,
    chunk_size: int = 1000,
    overlap: int = 200,
):
    """Create a chunker by strategy name."""
    match strategy:
        case "fixed":
            return FixedLengthChunker(chunk_size=chunk_size, overlap=overlap)
        case "sliding":
            return SlidingWindowChunker(chunk_size=chunk_size, overlap=overlap)
        case "semantic":
            return SemanticChunker(chunk_size=chunk_size)
        case _:
            raise ValueError(f"Unknown chunking strategy: {strategy}")


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences at period/question/exclamation boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [s.strip() for s in sentences if s.strip()]
