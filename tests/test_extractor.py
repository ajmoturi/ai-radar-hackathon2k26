"""Unit tests for extractor service."""
import pytest
from backend.services.extractor import (
    extract_text_and_metadata,
    truncate_for_llm,
    extract_text_from_url_content,
)


SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>OpenAI Launches GPT-4 Turbo</title>
  <meta name="description" content="GPT-4 Turbo offers improved performance and lower cost.">
  <meta property="og:title" content="GPT-4 Turbo - OpenAI">
  <meta name="author" content="OpenAI Team">
  <meta property="article:published_time" content="2024-11-01T10:00:00Z">
</head>
<body>
  <article>
    <h1>GPT-4 Turbo Launch</h1>
    <p>Today we are announcing GPT-4 Turbo, our latest model with a 128k context window.</p>
    <p>The new model supports JSON mode and improved function calling.</p>
  </article>
</body>
</html>"""


class TestExtractTextAndMetadata:
    def test_title_extracted(self):
        result = extract_text_and_metadata(SAMPLE_HTML)
        # og:title overrides <title>
        assert "GPT-4 Turbo" in result.get("title", "")

    def test_description_extracted(self):
        result = extract_text_and_metadata(SAMPLE_HTML)
        assert "performance" in result.get("description", "").lower() or \
               "performance" in result.get("text", "").lower()

    def test_text_extracted(self):
        result = extract_text_and_metadata(SAMPLE_HTML)
        text = result.get("text", "")
        assert len(text) > 0

    def test_date_parsed(self):
        result = extract_text_and_metadata(SAMPLE_HTML)
        assert result.get("date") is not None

    def test_empty_html(self):
        result = extract_text_and_metadata("")
        assert isinstance(result, dict)
        assert "text" in result

    def test_malformed_html(self):
        result = extract_text_and_metadata("<not valid html<<<<")
        assert isinstance(result, dict)


class TestTruncateForLlm:
    def test_short_text_unchanged(self):
        text = "Hello world"
        assert truncate_for_llm(text) == text

    def test_long_text_truncated(self):
        text = "x" * 20000
        result = truncate_for_llm(text, max_chars=12000)
        assert len(result) <= 12100  # allows for the truncation notice
        assert "truncated" in result

    def test_custom_max_chars(self):
        text = "a" * 1000
        result = truncate_for_llm(text, max_chars=500)
        assert len(result) <= 600


class TestExtractTextFromUrlContent:
    def test_css_selector_scope(self):
        html = """<html><body>
        <nav>Navigation text</nav>
        <article id="main">Important article content here.</article>
        </body></html>"""
        result = extract_text_from_url_content(html, css_selector="#main")
        assert "Important article content" in result
        # navigation text may not be present
        assert "Navigation text" not in result

    def test_no_selector_falls_back_to_trafilatura(self):
        result = extract_text_from_url_content(SAMPLE_HTML)
        assert len(result) > 0

    def test_invalid_selector_falls_back(self):
        result = extract_text_from_url_content(SAMPLE_HTML, css_selector=".nonexistent-class")
        assert len(result) > 0
