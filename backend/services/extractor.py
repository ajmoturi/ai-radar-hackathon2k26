"""Text and metadata extraction from HTML pages and PDF files.

Primary extraction: trafilatura (article-focused boilerplate removal).
Metadata: BeautifulSoup for Open Graph tags, meta tags, and <time> elements.
PDF: pdfminer.six for text extraction from PDF byte streams and file paths.
"""
from datetime import datetime
from typing import Optional
import re

from bs4 import BeautifulSoup


def extract_text_and_metadata(html: str, url: str = "") -> dict:
    """Extract main article text and page metadata from an HTML string.

    Returns a dict with keys: text, title, date, author, description.
    text falls back to the og:description meta if trafilatura finds nothing.
    """
    # trafilatura gives the best article extraction (removes nav, ads, footers).
    text = _extract_with_trafilatura(html, url)

    # Parse structured metadata separately (title, date, author, description).
    meta = _extract_metadata(html)

    return {
        "text": text or meta.get("description", ""),
        "title": meta.get("title", ""),
        "date": meta.get("date"),
        "author": meta.get("author", ""),
        "description": meta.get("description", ""),
    }


def _extract_with_trafilatura(html: str, url: str = "") -> Optional[str]:
    """Use trafilatura to extract the main article body from HTML.

    Returns clean article text or None if extraction fails/returns nothing.
    """
    try:
        import trafilatura
        result = trafilatura.extract(
            html,
            url=url,
            include_comments=False,  # skip comment sections
            include_tables=True,     # keep data tables (useful for benchmarks)
            no_fallback=False,       # allow heuristic fallback if main extractor fails
        )
        return result
    except Exception:
        return None


def _extract_metadata(html: str) -> dict:
    """Parse title, description, author, and publication date from HTML meta tags.

    Priority order for each field (first match wins):
      title:       og:title > <title>
      description: og:description > meta[name=description]
      date:        article:published_time / datePublished / DC.date / <time>
    """
    meta = {}
    try:
        soup = BeautifulSoup(html, "lxml")

        # ---- Title ----
        if soup.title:
            meta["title"] = soup.title.get_text(strip=True)
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            meta["title"] = og_title["content"]  # OG title preferred over <title>

        # ---- Description ----
        desc = soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content"):
            meta["description"] = desc["content"]
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            meta["description"] = og_desc["content"]

        # ---- Author ----
        author = soup.find("meta", attrs={"name": "author"})
        if author and author.get("content"):
            meta["author"] = author["content"]

        # ---- Publication date — try standard meta property names in order ----
        for prop in ["article:published_time", "og:article:published_time",
                     "datePublished", "date", "DC.date"]:
            tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            if tag and tag.get("content"):
                meta["date"] = _parse_date(tag["content"])
                break

        # ---- Date fallback: <time datetime="..."> element ----
        if "date" not in meta:
            time_tag = soup.find("time")
            if time_tag and time_tag.get("datetime"):
                meta["date"] = _parse_date(time_tag["datetime"])

    except Exception:
        pass
    return meta


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse a date string into a datetime using dateutil (handles ISO 8601 + many formats)."""
    from dateutil import parser as dateutil_parser
    try:
        return dateutil_parser.parse(date_str)
    except Exception:
        return None


def extract_pdf_text(pdf_path: str) -> str:
    """Extract plain text from a PDF file at the given path.

    Returns empty string if the file cannot be read or pdfminer fails.
    """
    try:
        from pdfminer.high_level import extract_text
        return extract_text(pdf_path)
    except Exception:
        return ""


def extract_text_from_url_content(html: str, url: str = "", css_selector: str = "") -> str:
    """Extract text from HTML, optionally scoped to a CSS selector.

    Fallback order:
      1. CSS selector element text (if css_selector is provided)
      2. trafilatura article extraction
      3. Raw tag-stripped text (truncated to 10,000 chars)
    """
    if css_selector:
        try:
            soup = BeautifulSoup(html, "lxml")
            el = soup.select_one(css_selector)
            if el:
                return el.get_text(separator="\n", strip=True)
        except Exception:
            pass
    result = _extract_with_trafilatura(html, url)
    if result:
        return result
    # Last resort: strip all HTML tags and return truncated plain text.
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(separator="\n", strip=True)[:10000]


def truncate_for_llm(text: str, max_chars: int = 12000) -> str:
    """Truncate text to stay within LLM context window limits.

    Appends a truncation notice so the LLM knows the content was cut off.
    Default max_chars=12000 leaves room for the prompt + response within 16k context.
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[... content truncated ...]"
