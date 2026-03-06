"""Unit tests for fetcher service (with mocked HTTP)."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from backend.services.fetcher import compute_hash, _is_pdf_url, _extract_text_from_pdf_bytes


class TestComputeHash:
    def test_deterministic(self):
        text = "Hello World"
        assert compute_hash(text) == compute_hash(text)

    def test_normalizes_whitespace(self):
        assert compute_hash("hello   world") == compute_hash("hello world")

    def test_normalizes_case(self):
        assert compute_hash("Hello World") == compute_hash("hello world")

    def test_different_content_different_hash(self):
        assert compute_hash("content A") != compute_hash("content B")

    def test_empty_string(self):
        h = compute_hash("")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex


class TestIsPdfUrl:
    def test_pdf_extension(self):
        assert _is_pdf_url("https://arxiv.org/pdf/2401.00001.pdf") is True

    def test_pdf_with_query_params(self):
        assert _is_pdf_url("https://example.com/paper.pdf?download=1") is True

    def test_html_url(self):
        assert _is_pdf_url("https://openai.com/blog/gpt4") is False

    def test_case_insensitive(self):
        assert _is_pdf_url("https://example.com/paper.PDF") is True


class TestExtractTextFromPdfBytes:
    def test_returns_none_on_invalid_bytes(self):
        result = _extract_text_from_pdf_bytes(b"not a pdf")
        assert result is None

    def test_returns_none_on_empty_bytes(self):
        result = _extract_text_from_pdf_bytes(b"")
        assert result is None


@pytest.mark.asyncio
class TestFetchUrl:
    async def test_returns_html_on_success(self):
        from backend.services.fetcher import fetch_url

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.text = "<html><body>Hello</body></html>"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await fetch_url("https://example.com", check_robots_txt=False)
            assert result == "<html><body>Hello</body></html>"

    async def test_returns_none_on_404(self):
        import httpx
        from backend.services.fetcher import fetch_url

        mock_response = MagicMock()
        mock_response.status_code = 404
        http_error = httpx.HTTPStatusError("Not found", request=MagicMock(), response=mock_response)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=http_error)
            mock_client_cls.return_value = mock_client

            result = await fetch_url("https://example.com/missing", check_robots_txt=False)
            assert result is None


@pytest.mark.asyncio
class TestFetchRss:
    async def test_parses_feed(self):
        from backend.services.fetcher import fetch_rss

        sample_rss = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>Test Post</title>
              <link>https://example.com/post1</link>
              <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
            </item>
          </channel>
        </rss>"""

        with patch("backend.services.fetcher.fetch_url", AsyncMock(return_value=sample_rss)):
            entries = await fetch_rss("https://example.com/feed")
            assert len(entries) >= 1
            assert entries[0]["title"] == "Test Post"
            assert entries[0]["link"] == "https://example.com/post1"

    async def test_returns_empty_on_failure(self):
        from backend.services.fetcher import fetch_rss

        with patch("backend.services.fetcher.fetch_url", AsyncMock(return_value=None)):
            entries = await fetch_rss("https://example.com/feed")
            assert entries == []
