"""Agent 4: Hugging Face Benchmark & Leaderboard Tracker.

Two data sources:
  1. HF public API (/api/models?sort=trending) — top 20 trending models
  2. HF leaderboard Spaces (Open LLM Leaderboard, Chatbot Arena, etc.)

Also handles SOTA claim cross-validation:
  verify_sota_claims() is called by the pipeline after Agent 2 runs.
  It checks whether model_provider SOTA claims are backed by HF trending data.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.agents.base import BaseAgent, Finding
from backend.config import settings
from backend.services.change_detector import is_content_changed, save_snapshot
from backend.services.extractor import extract_text_and_metadata, truncate_for_llm
from backend.services.fetcher import fetch_url
from backend.services.summarizer import summarize_benchmark

logger = logging.getLogger(__name__)

# HuggingFace REST API base
HF_API_BASE = "https://huggingface.co/api"

# Default leaderboard Space URLs to check on every run.
HF_LEADERBOARD_URLS = [
    "https://huggingface.co/spaces/HuggingFaceH4/open_llm_leaderboard",
    "https://huggingface.co/spaces/lmsys/chatbot-arena-leaderboard",
]


class HFBenchmarkTracker(BaseAgent):
    """Monitors Hugging Face leaderboards, trending models, and benchmark datasets.

    Provides two types of output:
      - Benchmark findings: trending model summaries + leaderboard snapshots
      - SOTA verification findings: cross-checks Agent 2 claims against HF data
    """

    agent_type = "hf_benchmark"

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

            # 1. Trending models snapshot from the HF public REST API.
            try:
                trending_findings = await self._fetch_trending_models(
                    source, source_id, run_id
                )
                findings.extend(trending_findings)
            except Exception as e:
                logger.error(f"HF trending fetch failed: {e}")

            # 2. Scrape leaderboard Space pages (source URLs + default list).
            for url in source.get("urls", []) + HF_LEADERBOARD_URLS:
                try:
                    finding = await self._process_leaderboard(url, source, source_id, run_id)
                    if finding:
                        finding.save_to_db(self.db, run_id, source_id)
                        findings.append(finding)
                except Exception as e:
                    logger.error(f"Leaderboard error {url}: {e}")

        logger.info(f"HF benchmark agent produced {len(findings)} findings")
        return findings

    async def _fetch_trending_models(
        self,
        source: dict,
        source_id: Optional[int],
        run_id: int,
    ) -> list[Finding]:
        """Fetch the top-20 trending models from HF API and summarize the snapshot.

        Returns an empty list if the snapshot is unchanged or the API is unavailable.
        """
        findings = []
        api_url = f"{HF_API_BASE}/models?sort=trending&limit=20&full=false"

        try:
            html = await fetch_url(api_url, rate_limit=0.5, check_robots_txt=settings.respect_robots_txt)
            if not html:
                return []

            models = json.loads(html)

            # Build a concise text summary of the top 20 trending models for the LLM.
            model_summaries = []
            for m in models[:20]:
                name = m.get("id", "")
                likes = m.get("likes", 0)
                downloads = m.get("downloads", 0)
                tags = m.get("tags", [])[:5]  # first 5 tags only
                model_summaries.append(
                    f"- {name} (likes: {likes}, downloads: {downloads}, tags: {', '.join(tags)})"
                )

            text = "Trending HuggingFace Models (today):\n" + "\n".join(model_summaries)
            url = api_url

            # Skip if trending list hasn't changed since last snapshot.
            if not is_content_changed(self.db, url, text):
                return []

            save_snapshot(self.db, url, text, source_id)

            result = summarize_benchmark(truncate_for_llm(text), url)
            if not result:
                return []

            finding = Finding(
                agent_type=self.agent_type,
                title=result.get("title", "HuggingFace Trending Models Update"),
                source_url="https://huggingface.co/models?sort=trending",
                publisher="HuggingFace",
                category="Benchmarks",
                summary_short=result.get("summary_short"),
                summary_long=result.get("summary_long"),
                why_it_matters=result.get("why_it_matters"),
                confidence=float(result.get("confidence", 0.8)),
                tags=result.get("tags", []),
                entities=result.get("entities", []),
            )
            finding.compute_diff_hash(text)
            finding.compute_impact_score()
            finding.save_to_db(self.db, run_id, source_id)
            findings.append(finding)

        except json.JSONDecodeError:
            # HF API returned HTML instead of JSON — usually means rate limiting.
            pass
        except Exception as e:
            logger.error(f"HF trending models error: {e}")

        return findings

    async def verify_sota_claims(
        self,
        claims: list[dict],
        run_id: int,
    ) -> list[Finding]:
        """Cross-validate SOTA claims from Agent 2 against HF trending data.

        For each claim (entity, benchmark, source_url), checks whether the entity
        appears in the HF trending model list and creates a verification finding.

        Args:
            claims: list of {entity, benchmark, source_url} dicts from Agent 2 findings
            run_id: current pipeline run id

        Returns:
            List of verification findings — one per claim checked.
        """
        findings: list[Finding] = []
        if not claims:
            return findings

        # Fetch current HF trending list once and reuse for all claims.
        trending_ids: set[str] = set()
        try:
            api_url = f"{HF_API_BASE}/models?sort=trending&limit=30&full=false"
            html = await fetch_url(api_url, rate_limit=0.5, check_robots_txt=False)
            if html:
                trending_models = json.loads(html)
                trending_ids = {m.get("id", "").lower() for m in trending_models}
        except Exception:
            pass  # proceed with empty set — all claims will return "not found"

        # Cap at 5 claims to avoid excessive processing.
        for claim in claims[:5]:
            entity = claim.get("entity", "")
            benchmark = claim.get("benchmark", "")
            if not entity:
                continue

            # Fuzzy match: check if entity name appears in any HF model ID.
            entity_lower = entity.lower().replace(" ", "-")
            on_leaderboard = any(entity_lower in mid for mid in trending_ids)
            status = "confirmed on HF trending" if on_leaderboard else "not found in HF trending models"

            finding = Finding(
                agent_type=self.agent_type,
                title=f"SOTA Claim Check: {entity}" + (f" on {benchmark}" if benchmark else ""),
                source_url=claim.get("source_url", "https://huggingface.co/models?sort=trending"),
                publisher="HuggingFace (verification)",
                category="Benchmarks",
                summary_short=f"Agent 2 claimed {entity} is SOTA{(' on ' + benchmark) if benchmark else ''}. Verification: {status}.",
                why_it_matters="Cross-validation of SOTA claims helps distinguish marketing from actual leaderboard performance.",
                confidence=0.6 if on_leaderboard else 0.4,
                tags=["sota-verification", "cross-validation"],
                entities=[entity] + ([benchmark] if benchmark else []),
            )
            finding.compute_diff_hash(f"sota-check-{entity}-{benchmark}")
            finding.compute_impact_score()
            finding.save_to_db(self.db, run_id, None)
            findings.append(finding)
            logger.info(f"SOTA claim check: {entity} → {status}")

        return findings

    async def _process_leaderboard(
        self,
        url: str,
        source: dict,
        source_id: Optional[int],
        run_id: int,
    ) -> Optional[Finding]:
        """Fetch and summarize a HF leaderboard Space page.

        Tries plain HTTP first; falls back to Playwright for JS-rendered pages.
        Returns None if content is unchanged or LLM extraction fails.
        """
        rate_limit = source.get("rate_limit", 0.5)

        # First attempt: plain HTTP (faster, no browser overhead).
        html = await fetch_url(url, rate_limit=rate_limit, use_playwright=False, check_robots_txt=settings.respect_robots_txt)
        # Leaderboard Spaces are JS-rendered; if response is too short, retry with Playwright.
        if not html or len(html) < 500:
            html = await fetch_url(url, rate_limit=rate_limit, use_playwright=True, check_robots_txt=settings.respect_robots_txt)
        if not html:
            return None

        data = extract_text_and_metadata(html, url)
        text = data.get("text", "")
        if not text or len(text) < 100:
            return None

        # Skip if leaderboard content hasn't changed since last run.
        if not is_content_changed(self.db, url, text):
            return None

        save_snapshot(self.db, url, text, source_id)

        result = summarize_benchmark(truncate_for_llm(text), url)
        if not result:
            return None

        finding = Finding(
            agent_type=self.agent_type,
            title=result.get("title") or data.get("title", "HF Leaderboard Update"),
            source_url=url,
            publisher="HuggingFace",
            category="Benchmarks",
            summary_short=result.get("summary_short"),
            summary_long=result.get("summary_long"),
            why_it_matters=result.get("why_it_matters"),
            confidence=float(result.get("confidence", 0.7)),
            tags=result.get("tags", []),
            entities=result.get("entities", []),
        )
        finding.compute_diff_hash(text)
        finding.compute_impact_score()
        return finding
