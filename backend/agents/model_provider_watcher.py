"""Agent 2: Foundation Model Provider Watcher.

Monitors Anthropic, OpenAI, Google, AWS, Azure, and other model providers
for model launches, API updates, pricing changes, and benchmark claims.

Signal filtering: pages without HIGH_SIGNAL_KEYWORDS are skipped before
being sent to the LLM, saving API calls on marketing noise.

SOTA claims extracted here are cross-validated later by HFBenchmarkTracker
(Agent 4) in the SOTA claim verification step.
"""
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


class ModelProviderWatcher(BaseAgent):
    """Monitors foundation model providers for model launches, API updates,
    pricing changes, and benchmark claims.

    Uses keyword pre-filtering to skip low-signal pages before LLM summarization.
    """

    agent_type = "model_provider"

    # Pages must contain at least one of these keywords to be worth LLM summarization.
    # Catches model releases, API changes, pricing, safety news, and capability updates.
    HIGH_SIGNAL_KEYWORDS = [
        "new model", "release", "launch", "ga ", "generally available",
        "pricing", "context window", "api update", "deprecat",
        "benchmark", "sota", "state of the art", "fine-tun",
        "safety", "alignment", "function calling", "tool use",
        "multimodal", "vision", "audio", "video",
    ]

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

            # Collect URLs from RSS feeds first (most recent 5 entries per feed).
            for rss_url in source.get("rss_feeds", []):
                try:
                    entries = await fetch_rss(rss_url, rate_limit=rate_limit)
                    for entry in entries[:5]:
                        link = entry.get("link", "")
                        if link:
                            urls_to_check.append(link)
                except Exception as e:
                    logger.warning(f"RSS failed {rss_url}: {e}")

            # Add direct fallback URLs (max 2 per source).
            for url in source.get("urls", [])[:2]:
                if url not in urls_to_check:
                    urls_to_check.append(url)

            logger.info(f"[{name}] Checking {len(urls_to_check)} URLs")

            # Process sequentially (model provider pages are fewer and often rate-limited).
            for url in urls_to_check[:7]:
                try:
                    finding = await self._process_url(url, source, source_id, run_id)
                    if finding:
                        finding.save_to_db(self.db, run_id, source_id)
                        findings.append(finding)
                except Exception as e:
                    logger.error(f"Error processing {url}: {e}")

        logger.info(f"Model provider agent produced {len(findings)} findings")
        return findings

    async def _process_url(
        self,
        url: str,
        source: dict,
        source_id: Optional[int],
        run_id: int,
    ) -> Optional[Finding]:
        """Fetch, filter by keywords, deduplicate, and summarize a model provider page.

        Returns None if: fetch fails, content too short, no high-signal keywords,
        content unchanged since last snapshot, or LLM returns nothing.
        """
        rate_limit = source.get("rate_limit", 1.0)

        html = await fetch_url(url, rate_limit=rate_limit, check_robots_txt=settings.respect_robots_txt)
        if not html:
            return None

        data = extract_text_and_metadata(html, url)
        text = data.get("text", "")
        if not text or len(text) < 100:
            return None

        # ---- Keyword pre-filter ----
        # Skip pages that don't mention any high-value signals — avoids wasting LLM calls.
        text_lower = text.lower()
        has_signal = any(kw in text_lower for kw in self.HIGH_SIGNAL_KEYWORDS)
        if not has_signal:
            return None

        # ---- Change detection ----
        if not is_content_changed(self.db, url, text):
            return None

        save_snapshot(self.db, url, text, source_id)

        truncated = truncate_for_llm(text)
        result = summarize_release(truncated, url, agent_type="model_provider")
        if not result:
            return None

        finding = self._finding_from_llm_output(result, url, text)

        # Prefer richer page metadata title when available.
        if data.get("title") and len(data["title"]) > len(finding.title):
            finding.title = data["title"]
        if data.get("date"):
            finding.date_detected = data["date"]

        # Always include the provider name as an entity for entity heatmap / filtering.
        provider_name = source.get("name", "")
        if provider_name and provider_name not in finding.entities:
            finding.entities.append(provider_name)

        return finding
