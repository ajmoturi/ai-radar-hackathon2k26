"""HTTP fetcher with rate limiting, retries, robots.txt support, and Playwright fallback.

Key design decisions:
  - Per-domain rate limiting via timestamp dict (no asyncio.Lock — locks are bound
    to the event loop they were created on, which breaks when Prefect creates a new
    loop per run).
  - Exponential back-off on 429 (rate limited) and transient errors.
  - PDF URLs are detected and text is extracted via pdfminer instead of returning raw bytes.
  - Playwright is a fallback only for JS-heavy pages that return empty/short HTML.
"""
import asyncio
import hashlib
import time
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "FrontierAIRadar/1.0 (research bot; contact: radar@example.com)"

# Per-domain timestamp tracking for rate limiting.
# Dict[domain -> monotonic time of last request].
# Intentionally NOT using asyncio.Lock — see module docstring for rationale.
_domain_last_request: dict[str, float] = {}


def _get_domain(url: str) -> str:
    """Extract the netloc (hostname) from a URL for per-domain rate limiting."""
    return urlparse(url).netloc


async def _wait_for_rate_limit(domain: str, rate_limit: float):
    """Sleep until the minimum inter-request interval has elapsed for this domain.

    rate_limit is in requests-per-second; min_interval = 1 / rate_limit.
    """
    min_interval = 1.0 / max(rate_limit, 0.1)
    last = _domain_last_request.get(domain, 0)
    elapsed = time.monotonic() - last
    if elapsed < min_interval:
        await asyncio.sleep(min_interval - elapsed)
    _domain_last_request[domain] = time.monotonic()


async def check_robots(url: str, client: httpx.AsyncClient) -> bool:
    """Return True if the URL is allowed by the domain's robots.txt.

    Defaults to True (allow) when robots.txt cannot be fetched.
    """
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        resp = await client.get(robots_url, timeout=10)
        if resp.status_code == 200:
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            return rp.can_fetch(USER_AGENT, url)
    except Exception:
        pass
    return True  # allow by default if robots.txt is unreachable


def _is_pdf_url(url: str) -> bool:
    """Return True if the URL path ends with .pdf (ignoring query parameters)."""
    return url.lower().split("?")[0].endswith(".pdf")


def _extract_text_from_pdf_bytes(pdf_bytes: bytes) -> Optional[str]:
    """Extract plain text from raw PDF bytes using pdfminer.high_level."""
    try:
        import io
        from pdfminer.high_level import extract_text
        return extract_text(io.BytesIO(pdf_bytes))
    except Exception:
        return None


async def fetch_url(
    url: str,
    rate_limit: float = 1.0,
    max_retries: int = 2,
    timeout: int = 10,
    use_playwright: bool = False,
    check_robots_txt: bool = False,  # disabled by default — saves one request per domain
) -> Optional[str]:
    """Fetch a URL and return its text content (HTML or extracted PDF text).

    Returns None on persistent failure (network error, 4xx, or disallowed by robots.txt).

    Retry behaviour:
      - 429 Too Many Requests → exponential back-off with longer delay (5s, 10s, ...)
      - 404/403/410           → return None immediately (no retries)
      - Other errors/timeouts → exponential back-off (1s, 2s, ...)
    """
    domain = _get_domain(url)
    await _wait_for_rate_limit(domain, rate_limit)

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}

    # Playwright is requested explicitly for JS-rendered pages (e.g. HF leaderboards).
    if use_playwright:
        return await _fetch_with_playwright(url)

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        if check_robots_txt:
            allowed = await check_robots(url, client)
            if not allowed:
                return None

        for attempt in range(max_retries):
            try:
                resp = await client.get(url, timeout=timeout)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                # Transparently extract text when the server returns a PDF.
                if "application/pdf" in content_type or _is_pdf_url(url):
                    return _extract_text_from_pdf_bytes(resp.content)
                return resp.text
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    await asyncio.sleep(2 ** attempt * 5)  # longer delay for rate-limit errors
                elif e.response.status_code in (404, 403, 410):
                    return None  # permanent failure — don't retry
                else:
                    await asyncio.sleep(2 ** attempt)
            except (httpx.RequestError, httpx.TimeoutException):
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
    return None


async def _fetch_with_playwright(url: str) -> Optional[str]:
    """Render a JS-heavy page using headless Chromium via Playwright.

    Used as a fallback when plain HTTP returns empty or minimal HTML.
    Requires `playwright install chromium` to be run once on the machine.
    """
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                user_agent=USER_AGENT,
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            # wait_until="networkidle" ensures dynamic JS content finishes loading.
            await page.goto(url, wait_until="networkidle", timeout=30000)
            content = await page.content()
            await browser.close()
            return content
    except Exception:
        return None


async def fetch_rss(url: str, rate_limit: float = 1.0) -> list[dict]:
    """Fetch and parse an RSS/Atom feed.

    Returns a list of entry dicts: [{title, link, published, summary}].
    Returns empty list on fetch failure or feedparser parse error.
    """
    import feedparser
    html = await fetch_url(url, rate_limit=rate_limit)
    if not html:
        return []
    feed = feedparser.parse(html)
    entries = []
    for entry in feed.entries:
        entries.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
            "summary": entry.get("summary", ""),
        })
    return entries


def compute_hash(text: str) -> str:
    """Return a SHA-256 hex digest of normalised text for change detection.

    Text is lowercased and whitespace-collapsed before hashing so that minor
    formatting changes (extra spaces, line endings) don't trigger false positives.
    """
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()
