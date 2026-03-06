"""Agent 1: Competitor Release Watcher.

Monitors product blogs, changelogs, and release notes for AI competitors
(OpenAI, Google DeepMind, Meta AI, Mistral, etc.).

Discovery strategy (per source):
  1. RSS feeds  — up to 5 most-recent entries per feed
  2. Direct URLs — up to 2 fallback page URLs per source

Concurrency: up to 3 URLs processed in parallel per source (Semaphore).
Change detection: content is skipped if its SHA-256 hash matches the last snapshot.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend.agents.base import BaseAgent, Finding
from backend.config import settings
from backend.services.change_detector import is_content_changed, save_snapshot
from backend.services.extractor import extract_text_and_metadata, truncate_for_llm
from backend.services.fetcher import fetch_rss, fetch_url
from backend.services.summarizer import summarize_release

logger = logging.getLogger(__name__)


class CompetitorWatcher(BaseAgent):
    """Monitors competitor product blogs, changelogs, and release notes.

    Discovery order: RSS feeds → direct URL list.
    Only pages with content changes since the last run are sent to the LLM.
    """

    agent_type = "competitor"

    async def run(
        self,
        run_id: int,
        sources: list[dict],
        since_timestamp: Optional[datetime] = None,
    ) -> list[Finding]:
        findings: list[Finding] = []

        for source in sources:
            if not source.get("enabled", True):
                continue
            source_id = source.get("id")
            rate_limit = source.get("rate_limit", 1.0)
            name = source.get("name", "Unknown")

            urls_to_check: list[str] = []

            # 1. RSS feeds (preferred) — most recent 5 items per feed.
            for rss_url in source.get("rss_feeds", []):
                try:
                    entries = await fetch_rss(rss_url, rate_limit=rate_limit)
                    for entry in entries[:5]:
                        if entry.get("link"):
                            urls_to_check.append(entry["link"])
                except Exception as e:
                    logger.warning(f"RSS fetch failed for {rss_url}: {e}")

            # 2. Direct fallback URLs — cap at 2 per source to avoid over-fetching.
            for url in source.get("urls", [])[:2]:
                if url not in urls_to_check:
                    urls_to_check.append(url)

            logger.info(f"[{name}] Checking {len(urls_to_check)} URLs")

            # Process up to 7 URLs total, with max 3 concurrent HTTP requests.
            sem = asyncio.Semaphore(3)

            async def _process_with_sem(url: str):
                async with sem:
                    try:
                        return await self._process_url(
                            url=url,
                            source=source,
                            source_id=source_id,
                            run_id=run_id,
                        )
                    except Exception as e:
                        logger.error(f"Error processing {url}: {e}")
                        return None

            results = await asyncio.gather(
                *[_process_with_sem(url) for url in urls_to_check[:7]]
            )
            # Filter out None results (unchanged pages, fetch failures, LLM errors).
            for finding in results:
                if finding:
                    finding.save_to_db(self.db, run_id, source_id)
                    findings.append(finding)

        logger.info(f"Competitor agent produced {len(findings)} findings")
        return findings

    async def _process_url(
        self,
        url: str,
        source: dict,
        source_id: Optional[int],
        run_id: int,
    ) -> Optional[Finding]:
        """Fetch, deduplicate, extract text, and summarize a single URL.

        Returns a Finding if the page is new/changed and LLM extraction succeeds,
        otherwise returns None (caller skips None results silently).
        """
        rate_limit = source.get("rate_limit", 1.0)
        selectors = source.get("selectors", {})
        css_selector = selectors.get("content", "")  # optional CSS scope hint (unused here)

        # ---- Fetch HTML ----
        html = await fetch_url(url, rate_limit=rate_limit, check_robots_txt=settings.respect_robots_txt)
        if not html:
            logger.debug(f"Could not fetch {url}")
            return None

        # ---- Extract main text ----
        data = extract_text_and_metadata(html, url)
        text = data.get("text", "")
        if not text or len(text) < 100:
            return None  # too little content — likely a login wall or error page

        # ---- Change detection ----
        # Skip if content hash matches the last snapshot — avoids re-summarising identical pages.
        if not is_content_changed(self.db, url, text):
            logger.debug(f"No change detected: {url}")
            return None

        # ---- Persist snapshot ----
        save_snapshot(self.db, url, text, source_id)

        # ---- LLM summarization ----
        truncated = truncate_for_llm(text)  # trim to stay within LLM context window
        result = summarize_release(truncated, url, agent_type="competitor")
        if not result:
            logger.warning(f"Summarizer returned nothing for {url}")
            return None

        finding = self._finding_from_llm_output(result, url, text)

        # Prefer page metadata title when the LLM-generated title is shorter/weaker.
        if data.get("title") and len(data["title"]) > len(finding.title):
            finding.title = data["title"]
        if data.get("date") and not finding.date_detected:
            finding.date_detected = data["date"]

        return finding
