"""Token count estimation for LLM-ready output."""

from __future__ import annotations


def _is_cjk(ch: str) -> bool:
    """Whether a character is CJK/Japanese/Korean (roughly 1–2 chars per token)."""
    o = ord(ch)
    return 0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF or 0xF900 <= o <= 0xFAFF


def estimate_tokens(text: str) -> int:
    """Estimate token count using a simple heuristic.

    Latin text is ~4 chars/token (~3.5 for code-heavy). CJK text is far denser
    (~1.5 chars/token), so a plain char/4 rule under-counts CJK by ~2.6x; those
    characters are counted separately to keep the estimate usable for budgeting.
    This avoids requiring tiktoken as a dependency.
    """
    if not text:
        return 0
    cjk_chars = sum(1 for ch in text if _is_cjk(ch))
    latin_len = len(text) - cjk_chars
    tokens = cjk_chars / 1.5
    if latin_len > 0:
        code_chars = text.count("{") + text.count("}") + text.count("(") + text.count(")")
        code_ratio = code_chars / len(text)
        chars_per_token = 3.5 if code_ratio > 0.05 else 4.0
        tokens += latin_len / chars_per_token
    return int(tokens)
