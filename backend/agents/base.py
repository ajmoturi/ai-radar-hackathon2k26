"""Base agent interface and shared Finding schema.

All intelligence agents inherit from BaseAgent and produce Finding objects.
Findings are Pydantic models that carry structured LLM output and are
persisted to the DB via save_to_db().
"""
import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.models import Finding as FindingModel
from backend.services.fetcher import compute_hash


class Finding(BaseModel):
    """Structured intelligence finding produced by any agent.

    Agents fill this model from LLM tool-use output, then call save_to_db()
    to persist it.  impact_score drives ranking in the digest.
    """
    agent_type: str                  # which agent produced this (e.g. "competitor")
    title: str
    date_detected: datetime = Field(default_factory=datetime.utcnow)
    source_url: str
    publisher: Optional[str] = None
    category: Optional[str] = None  # Models|APIs|Pricing|Benchmarks|Safety|Tooling|Research|Other
    summary_short: Optional[str] = None  # ≤ 60-word one-liner
    summary_long: Optional[str] = None   # bullet-point detail block
    why_it_matters: Optional[str] = None
    evidence: list[str] = Field(default_factory=list)  # direct quotes from source
    confidence: float = 0.5          # LLM-provided 0–1 confidence
    tags: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)  # company/model/dataset names
    diff_hash: Optional[str] = None  # SHA-256 of source text (used for dedup)
    impact_score: float = 0.0        # computed composite score for ranking

    def compute_diff_hash(self, text: str) -> "Finding":
        """Set diff_hash from source text — used for deduplication across runs."""
        self.diff_hash = compute_hash(text)
        return self

    def compute_impact_score(self) -> "Finding":
        """Compute a composite 0–1 impact score used to rank findings in the digest.

        Formula: 0.35 * relevance + 0.25 * novelty + 0.20 * credibility + 0.20 * actionability
        All inputs are heuristic — agents only surface new content so novelty defaults high.
        """
        relevance = self.confidence
        novelty = 0.8  # agents only surface content that passed change detection → inherently new
        credibility = min(self.confidence + 0.2, 1.0)  # credibility slightly higher than raw confidence
        # Actionable categories (things you can act on today) score higher.
        actionable_categories = {"APIs", "Pricing", "Models", "Benchmarks"}
        actionability = 0.8 if self.category in actionable_categories else 0.5
        self.impact_score = (
            0.35 * relevance + 0.25 * novelty + 0.20 * credibility + 0.20 * actionability
        )
        return self

    def save_to_db(self, db: Session, run_id: int, source_id: Optional[int] = None) -> FindingModel:
        """Persist this finding to the database and return the ORM record."""
        record = FindingModel(
            run_id=run_id,
            source_id=source_id,
            agent_type=self.agent_type,
            title=self.title,
            date_detected=self.date_detected,
            source_url=self.source_url,
            publisher=self.publisher,
            category=self.category,
            summary_short=self.summary_short,
            summary_long=self.summary_long,
            why_it_matters=self.why_it_matters,
            evidence_json=json.dumps(self.evidence),
            confidence=self.confidence,
            tags_json=json.dumps(self.tags),
            entities_json=json.dumps(self.entities),
            diff_hash=self.diff_hash,
            impact_score=self.impact_score,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record


class BaseAgent(ABC):
    """Abstract base class for all intelligence agents.

    Subclasses must implement run() which returns a list of Finding objects.
    The shared helper _finding_from_llm_output() converts raw LLM dicts into
    typed Finding instances with hashes and impact scores already computed.
    """

    agent_type: str = "base"

    def __init__(self, db: Session):
        self.db = db  # SQLAlchemy session for DB reads/writes during this run

    @abstractmethod
    async def run(
        self,
        run_id: int,
        sources: list[dict],
        since_timestamp: Optional[datetime] = None,
    ) -> list[Finding]:
        """Execute the agent and return all new findings for this run."""
        ...

    def _finding_from_llm_output(
        self,
        llm_result: dict,
        source_url: str,
        text_for_hash: str,
    ) -> Finding:
        """Convert a raw LLM tool-use response dict into a typed Finding.

        Automatically computes diff_hash (for dedup) and impact_score (for ranking).
        """
        finding = Finding(
            agent_type=self.agent_type,
            title=llm_result.get("title", "Untitled"),
            source_url=source_url,
            publisher=llm_result.get("publisher"),
            category=llm_result.get("category", "Other"),
            summary_short=llm_result.get("summary_short"),
            summary_long=llm_result.get("summary_long"),
            why_it_matters=llm_result.get("why_it_matters"),
            evidence=llm_result.get("evidence", []),
            confidence=float(llm_result.get("confidence", 0.5)),
            tags=llm_result.get("tags", []),
            entities=llm_result.get("entities", []),
        )
        finding.compute_diff_hash(text_for_hash)
        finding.compute_impact_score()
        return finding
