"""Agent 3: Research Publication Scout.

Tracks the latest AI research from arXiv and configured research lab blogs
(Google Research, DeepMind, Meta AI Research, etc.).

arXiv strategy:
  - Queries the public Atom/XML API by category (cs.CL, cs.LG, etc.)
  - Filters to papers published in the last 2 days
  - Scores papers by topic relevance using keyword boosting
  - Only unseen papers (change detection on abstract text) are summarized

Direct URL strategy:
  - Also processes any plain URLs configured per source (research lab blogs)
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

from sqlalchemy.orm import Session

from backend.agents.base import BaseAgent, Finding
from backend.config import settings
from backend.services.change_detector import is_content_changed, save_snapshot
from backend.services.extractor import truncate_for_llm
from backend.services.fetcher import fetch_url
from backend.services.summarizer import summarize_research

logger = logging.getLogger(__name__)

# arXiv public Atom query API
ARXIV_API = "https://export.arxiv.org/api/query"

# Keywords that add 0.05 to the LLM-provided relevance_score (capped at 1.0).
# Covers the highest-value topics for AI practitioners.
HIGH_RELEVANCE_KEYWORDS = [
    "benchmark", "evaluation", "eval", "leaderboard",
    "synthetic data", "data curation", "preference learning", "rlhf", "dpo",
    "agent", "tool use", "function calling", "memory",
    "multimodal", "vision-language", "video understanding",
    "safety", "alignment", "red-team", "jailbreak", "harmlessness",
    "reasoning", "chain-of-thought", "inference scaling",
]


class ResearchScout(BaseAgent):
    """Tracks latest AI research publications from arXiv and configured lab blogs.

    Scores each paper using LLM-provided relevance_score boosted by keyword matching.
    Only papers not yet seen by the system are sent to the LLM for summarization.
    """

    agent_type = "research"

    async def run(
        self,
        run_id: int,
        sources: list[dict],
        since_timestamp: Optional[datetime] = None,
    ) -> list[Finding]:
        findings: list[Finding] = []

        # Default lookback window: 2 days (catches weekend papers on Monday runs).
        if since_timestamp is None:
            since_timestamp = datetime.utcnow() - timedelta(days=2)

        for source in sources:
            if not source.get("enabled", True):
                continue

            source_id = source.get("id")
            source_type = source.get("type", "arxiv")

            try:
                # arXiv sources have arxiv_queries configured.
                if source_type == "arxiv" or source.get("arxiv_queries"):
                    arxiv_findings = await self._fetch_arxiv(
                        source, source_id, run_id, since_timestamp
                    )
                    findings.extend(arxiv_findings)

                # Also process any direct blog/page URLs configured for this source.
                for url in source.get("urls", []):
                    finding = await self._process_url(url, source, source_id, run_id)
                    if finding:
                        finding.save_to_db(self.db, run_id, source_id)
                        findings.append(finding)

            except Exception as e:
                logger.error(f"Research scout error for source {source.get('name')}: {e}")

        logger.info(f"Research scout produced {len(findings)} findings")
        return findings

    async def _fetch_arxiv(
        self,
        source: dict,
        source_id: Optional[int],
        run_id: int,
        since_timestamp: datetime,
    ) -> list[Finding]:
        """Query arXiv API and summarize papers published after since_timestamp."""
        findings = []
        queries = source.get("arxiv_queries", ["cat:cs.CL", "cat:cs.LG"])
        max_results = min(source.get("max_results", 20), 8)  # cap at 8 per query for speed

        # Only run the first configured query per source to keep latency reasonable.
        for query in queries[:1]:
            url = (
                f"{ARXIV_API}?search_query={quote(query)}"
                f"&sortBy=submittedDate&sortOrder=descending"
                f"&max_results={max_results}"
            )
            try:
                xml_text = await fetch_url(url, rate_limit=0.5, check_robots_txt=settings.respect_robots_txt)
                if not xml_text:
                    continue
                papers = self._parse_arxiv_xml(xml_text)

                for paper in papers:
                    pub_date = paper.get("published")
                    # Skip papers older than the lookback window.
                    if pub_date and pub_date < since_timestamp:
                        continue

                    finding = await self._summarize_paper(paper, source_id, run_id)
                    if finding:
                        finding.save_to_db(self.db, run_id, source_id)
                        findings.append(finding)

            except Exception as e:
                logger.error(f"arXiv fetch error for query '{query}': {e}")

        return findings

    def _parse_arxiv_xml(self, xml_text: str) -> list[dict]:
        """Parse arXiv Atom feed XML into a list of paper dicts.

        Returns: [{title, abstract, url, published (datetime), authors}]
        """
        import xml.etree.ElementTree as ET

        papers = []
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }
        try:
            root = ET.fromstring(xml_text)
            for entry in root.findall("atom:entry", ns):
                title = entry.findtext("atom:title", "", ns).strip().replace("\n", " ")
                abstract = entry.findtext("atom:summary", "", ns).strip()
                link_el = entry.find("atom:id", ns)
                arxiv_url = link_el.text.strip() if link_el is not None else ""

                # Parse ISO 8601 publish date, stripping timezone for naive comparison.
                pub_str = entry.findtext("atom:published", "", ns)
                pub_date = None
                if pub_str:
                    try:
                        pub_date = datetime.fromisoformat(pub_str.replace("Z", "+00:00")).replace(tzinfo=None)
                    except Exception:
                        pass

                authors = [
                    a.findtext("atom:name", "", ns)
                    for a in entry.findall("atom:author", ns)
                ]

                papers.append({
                    "title": title,
                    "abstract": abstract,
                    "url": arxiv_url,
                    "published": pub_date,
                    "authors": authors,
                })
        except Exception as e:
            logger.error(f"arXiv XML parse error: {e}")
        return papers

    async def _summarize_paper(
        self,
        paper: dict,
        source_id: Optional[int],
        run_id: int,
    ) -> Optional[Finding]:
        """Summarize a single paper via LLM, skipping if already seen.

        Uses title + abstract as the canonical text for change detection
        (full PDFs are not fetched for research papers).
        """
        url = paper.get("url", "")
        text = f"Title: {paper['title']}\n\nAbstract:\n{paper.get('abstract', '')}"

        # Skip if we've already processed this exact abstract.
        if not is_content_changed(self.db, url, text):
            return None

        save_snapshot(self.db, url, text, source_id)

        result = summarize_research(truncate_for_llm(text), url)
        if not result:
            return None

        # Combine LLM relevance_score with keyword boost for final impact ordering.
        relevance = float(result.get("relevance_score", 0.5))
        text_lower = text.lower()
        keyword_boost = sum(0.05 for kw in HIGH_RELEVANCE_KEYWORDS if kw in text_lower)
        relevance = min(relevance + keyword_boost, 1.0)

        finding = Finding(
            agent_type=self.agent_type,
            title=result.get("title") or paper["title"],
            source_url=url,
            publisher="arXiv",
            category="Research",
            summary_short=result.get("summary_short"),
            summary_long=result.get("summary_long"),
            why_it_matters=result.get("why_it_matters"),
            confidence=float(result.get("confidence", 0.8)),
            tags=result.get("tags", []),
            entities=result.get("entities", []),
        )
        finding.date_detected = paper.get("published") or datetime.utcnow()
        finding.compute_diff_hash(text)
        # For research papers, use topic relevance as the impact signal instead of
        # the standard composite formula (which is better suited for product news).
        finding.impact_score = relevance
        return finding

    async def _process_url(
        self,
        url: str,
        source: dict,
        source_id: Optional[int],
        run_id: int,
    ) -> Optional[Finding]:
        """Fetch and summarize a research lab blog page (non-arXiv source)."""
        from backend.services.extractor import extract_text_and_metadata
        html = await fetch_url(url, rate_limit=source.get("rate_limit", 1.0), check_robots_txt=settings.respect_robots_txt)
        if not html:
            return None
        data = extract_text_and_metadata(html, url)
        text = data.get("text", "")
        if not text or len(text) < 200:
            return None
        if not is_content_changed(self.db, url, text):
            return None
        save_snapshot(self.db, url, text, source_id)
        result = summarize_research(truncate_for_llm(text), url)
        if not result:
            return None
        finding = self._finding_from_llm_output(result, url, text)
        finding.category = "Research"  # force category even if LLM assigns something else
        return finding
