"""Dependency-free token-level scoring for extraction-quality benchmarks.

The metric is a bag-of-tokens (multiset) precision / recall / F1 comparing the
extractor's output against ground-truth main content. This mirrors how content
extraction is commonly scored (e.g. trafilatura's evaluation): it rewards
keeping the article prose and punishes both dropped content (recall) and leaked
boilerplate such as nav menus, sidebars, and footers (precision).

Kept free of third-party imports so it can be unit-tested and run anywhere,
even without pawgrab's full dependency set installed.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens; punctuation and whitespace are dropped."""
    return _WORD_RE.findall((text or "").lower())


@dataclass(frozen=True)
class Score:
    precision: float
    recall: float
    f1: float
    pred_tokens: int
    gold_tokens: int

    def as_dict(self) -> dict:
        return {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "pred_tokens": self.pred_tokens,
            "gold_tokens": self.gold_tokens,
        }


def score_tokens(predicted: str, gold: str) -> Score:
    """Bag-of-tokens precision/recall/F1 of ``predicted`` against ``gold``."""
    pred = Counter(tokenize(predicted))
    gold_c = Counter(tokenize(gold))
    overlap = sum((pred & gold_c).values())
    pred_total = sum(pred.values())
    gold_total = sum(gold_c.values())

    precision = overlap / pred_total if pred_total else 0.0
    recall = overlap / gold_total if gold_total else 0.0
    denom = precision + recall
    f1 = (2 * precision * recall / denom) if denom else 0.0
    return Score(precision, recall, f1, pred_total, gold_total)


def mean_f1(scores: list[Score]) -> float:
    return sum(s.f1 for s in scores) / len(scores) if scores else 0.0
