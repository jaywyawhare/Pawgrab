"""Tests for the extraction benchmark harness.

The scoring tests are pure-Python and always run. The end-to-end extraction
test is skipped automatically when pawgrab's heavier extraction dependencies
(readability, trafilatura, bs4, structlog) aren't installed.
"""

from __future__ import annotations

import pytest

from benchmarks.run import DEFAULT_DATASET, load_cases, run
from benchmarks.score import mean_f1, score_tokens, tokenize
from benchmarks.stealth import (
    judge_incolumitas,
    judge_sannysoft,
    judge_tls_echo,
    render_markdown,
)


def test_tokenize_lowercases_and_drops_punctuation():
    assert tokenize("Hello, World! 429s") == ["hello", "world", "429s"]


def test_score_perfect_match_is_one():
    s = score_tokens("the quick brown fox", "the quick brown fox")
    assert s.precision == 1.0
    assert s.recall == 1.0
    assert s.f1 == 1.0


def test_score_leaked_boilerplate_lowers_precision():

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

        assert score.recall >= 0.8, f"{name} dropped main content: {score.as_dict()}"
    assert mean_f1(scores) >= 0.5, {name: score.as_dict() for name, score, _ in results}


# --- Anti-bot stealth harness: offline judge tests (no network) ---

_TLS_BROWSER = '{"user_agent": "Mozilla/5.0 (Macintosh) Safari/605.1.15", "tls": {"ja3": "771,4865-4866", "ja3_hash": "abc123", "ja4": "t13d"}}'
_TLS_BOT = '{"user_agent": "python-requests/2.31", "tls": {"ja3": "771,4865"}}'
_TLS_NO_FP = '{"user_agent": "Mozilla/5.0 Safari/605", "tls": {}}'


def test_judge_tls_echo_passes_browser_fingerprint():
    j = judge_tls_echo(_TLS_BROWSER)
    assert j.ok is True
    assert j.score == 1.0
    assert j.metrics["ja3_hash" if "ja3_hash" in j.metrics else "ja3"]


def test_judge_tls_echo_fails_library_user_agent():
    j = judge_tls_echo(_TLS_BOT)
    assert j.ok is False
    assert j.score == 0.0


def test_judge_tls_echo_fails_without_fingerprint():
    assert judge_tls_echo(_TLS_NO_FP).ok is False


def test_judge_tls_echo_handles_non_json():
    j = judge_tls_echo("<html>not json</html>")
    assert j.ok is False
    assert j.score is None


def test_judge_sannysoft_counts_pass_fail_cells():
    html = '<td class="passed">missing (passed)</td><td class="passed">ok</td><td class="passed">ok</td><td class="failed">present (failed)</td>'
    j = judge_sannysoft(html)
    assert j.metrics == {"passed": 3, "failed": 1}
    assert j.score == 0.75
    assert j.ok is False  # below the 0.85 threshold


def test_judge_sannysoft_all_passed_is_ok():
    html = '<td class="passed">a</td>' * 10
    j = judge_sannysoft(html)
    assert j.score == 1.0
    assert j.ok is True


def test_judge_sannysoft_no_cells_is_unscored():
    j = judge_sannysoft("<html><body>loading…</body></html>")
    assert j.score is None
    assert j.ok is False


def test_judge_incolumitas_detects_reachability():
    assert judge_incolumitas("<title>Incolumitas detection</title>").ok is True
    assert judge_incolumitas("<html>something else</html>").ok is False


def test_render_markdown_table_shape():
    rows = [
        {"site": "tls_echo", "ok": True, "score": 1.0, "status": 200, "used_browser": False, "challenge": None, "detail": "browser-like"},
        {"site": "sannysoft", "ok": False, "score": 0.75, "status": 200, "used_browser": True, "challenge": None, "detail": "3/4"},
    ]
    md = render_markdown(rows)
    assert md.startswith("| Check | Result |")
    assert "✅ pass" in md
    assert "❌ fail" in md
    assert "100%" in md and "75%" in md
