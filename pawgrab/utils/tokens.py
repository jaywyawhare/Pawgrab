"""Token count estimation for LLM-ready output."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Estimate token count using a simple heuristic.

    Uses the common approximation: ~4 characters per token for English text,
    ~3.5 for code-heavy content. This avoids requiring tiktoken as a dependency.
    """
    if not text:
        return 0

    # Count code indicators
    code_chars = text.count("{") + text.count("}") + text.count("(") + text.count(")")
    text_len = len(text)

    if text_len == 0:
        return 0

    code_ratio = code_chars / text_len
    chars_per_token = 3.5 if code_ratio > 0.05 else 4.0

    return int(text_len / chars_per_token)
