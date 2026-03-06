"""Unit tests for change_detector service."""
import pytest
from unittest.mock import MagicMock, patch
from backend.services.change_detector import (
    dedup_findings,
    _title_tokens,
    _jaccard,
)


class TestTitleTokens:
    def test_basic_tokenization(self):
        tokens = _title_tokens("GPT-4 Release Notes")
        assert "gpt-4" in tokens
        assert "release" in tokens
        assert "notes" in tokens

    def test_stopword_removal(self):
        tokens = _title_tokens("the state of the art model")
        assert "the" not in tokens
        assert "of" not in tokens
        assert "state" in tokens
        assert "model" in tokens

    def test_short_word_removal(self):
        # "is" has len=2, filtered out (requires len > 2). "now" has len=3, kept.
        tokens = _title_tokens("AI is now better")
        assert "is" not in tokens
        assert "now" in tokens
        assert "better" in tokens

    def test_empty_string(self):
        tokens = _title_tokens("")
        assert tokens == set()


class TestJaccard:
    def test_identical_sets(self):
        s = {"a", "b", "c"}
        assert _jaccard(s, s) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial_overlap(self):
        a = {"a", "b", "c"}
        b = {"b", "c", "d"}
        # |A∩B| = 2, |A∪B| = 4 → 0.5
        assert _jaccard(a, b) == pytest.approx(0.5)

    def test_empty_sets(self):
        assert _jaccard(set(), {"a"}) == 0.0
        assert _jaccard({"a"}, set()) == 0.0


class TestDedupFindings:
    def _make_finding(self, title, url, score=0.5, diff_hash=None):
        return {
            "title": title,
            "source_url": url,
            "impact_score": score,
            "diff_hash": diff_hash or url,
        }

    def test_exact_url_dedup(self):
        f1 = self._make_finding("GPT-4 Release", "https://openai.com/gpt4")
        f2 = self._make_finding("GPT-4 Released", "https://openai.com/gpt4")  # same URL
        result = dedup_findings([f1, f2])
        assert len(result) == 1

    def test_no_duplicates(self):
        f1 = self._make_finding("GPT-4 Release", "https://openai.com/gpt4")
        f2 = self._make_finding("Claude 3 Launch", "https://anthropic.com/claude")
        result = dedup_findings([f1, f2])
        assert len(result) == 2

    def test_semantic_title_dedup_keeps_higher_impact(self):
        f1 = self._make_finding("GPT-4 Turbo New Release by OpenAI", "https://openai.com/1", score=0.3)
        f2 = self._make_finding("GPT-4 Turbo New Release from OpenAI", "https://openai.com/2", score=0.8)
        result = dedup_findings([f1, f2])
        assert len(result) == 1
        assert result[0]["impact_score"] == 0.8

    def test_semantic_dedup_threshold(self):
        # Very different titles should NOT be deduped
        f1 = self._make_finding("GPT-4 model released by OpenAI company", "https://openai.com/1")
        f2 = self._make_finding("Gemini Ultra benchmark results published", "https://google.com/1")
        result = dedup_findings([f1, f2])
        assert len(result) == 2

    def test_empty_list(self):
        assert dedup_findings([]) == []

    def test_single_finding(self):
        f = self._make_finding("Test Finding", "https://example.com")
        result = dedup_findings([f])
        assert len(result) == 1
