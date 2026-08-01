"""Tests for the extraction benchmark harness.

The scoring tests are pure-Python and always run. The end-to-end extraction
test is skipped automatically when pawgrab's heavier extraction dependencies
(readability, trafilatura, bs4, structlog) aren't installed.
"""

from __future__ import annotations

import pytest

from benchmarks.run import DEFAULT_DATASET, load_cases, run
from benchmarks.score import mean_f1, score_tokens, tokenize


def test_tokenize_lowercases_and_drops_punctuation():
    assert tokenize("Hello, World! 429s") == ["hello", "world", "429s"]


def test_score_perfect_match_is_one():
    s = score_tokens("the quick brown fox", "the quick brown fox")
    assert s.precision == 1.0
    assert s.recall == 1.0
    assert s.f1 == 1.0


def test_score_leaked_boilerplate_lowers_precision():
    # Predicted keeps all gold tokens but adds nav/footer noise.
    s = score_tokens("article body home login privacy contact", "article body")
    assert s.recall == 1.0
    assert s.precision < 1.0
    assert 0.0 < s.f1 < 1.0


def test_score_dropped_content_lowers_recall():
    s = score_tokens("article", "article body extra content here")
    assert s.precision == 1.0
    assert s.recall < 1.0


def test_score_empty_prediction_is_zero():
    s = score_tokens("", "some gold content")
    assert s.f1 == 0.0
    assert s.pred_tokens == 0


def test_dataset_cases_load_and_have_content():
    cases = load_cases(DEFAULT_DATASET)
    assert len(cases) >= 3
    for name, html, expected in cases:
        assert html.strip(), f"{name} has empty html"
        assert len(expected.strip()) > 200, f"{name} ground truth too short"


def test_end_to_end_extraction_does_not_collapse():
    """Regression gate: guards against the extractor returning nothing.

    A modest floor rather than a tight target — the adversarial fixtures
    (comments-heavy, promo-in-article) are *designed* to leak boilerplate and
    score low. Use ``python -m benchmarks.run`` to track the real per-case
    precision/recall and drive quality work; this test only fails if extraction
    catastrophically breaks.
    """
    pytest.importorskip("readability")
    pytest.importorskip("trafilatura")
    pytest.importorskip("bs4")

    results = run(DEFAULT_DATASET)
    scores = [s for _, s, _ in results]

    for name, score, _ in results:
        assert score.pred_tokens > 0, f"{name} extracted nothing"
        # Recall guards against dropping real content; tolerant of minor
        # reformatting/tokenization differences.
        assert score.recall >= 0.8, f"{name} dropped main content: {score.as_dict()}"
    assert mean_f1(scores) >= 0.5, {name: score.as_dict() for name, score, _ in results}
