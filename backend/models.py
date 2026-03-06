"""SQLAlchemy ORM models for Frontier AI Radar.

Tables:
  sources   — crawl targets (URLs, RSS feeds, keywords) per agent type
  snapshots — content hashes used for change detection
  runs      — one record per pipeline execution
  findings  — structured intel extracted by agents
  digests   — compiled PDF/email records linked to a run
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base


class Source(Base):
    """A crawl source: a website, RSS feed, or API endpoint monitored by one agent."""
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    agent_type = Column(String, nullable=False)  # competitor|model_provider|research|hf_benchmark
    urls_json = Column(Text, default="[]")        # JSON list of direct page URLs to crawl
    rss_feeds_json = Column(Text, default="[]")   # JSON list of RSS/Atom feed URLs
    selectors_json = Column(Text, default="{}")   # JSON CSS selectors for content scoping
    keywords_json = Column(Text, default="[]")    # JSON list of keyword filters
    rate_limit = Column(Float, default=1.0)        # max requests per second to this domain
    enabled = Column(Boolean, default=True)        # set False to pause without deleting
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    snapshots = relationship("Snapshot", back_populates="source")
    findings = relationship("Finding", back_populates="source")


class Snapshot(Base):
    """Content fingerprint for a URL — used to detect page changes between runs."""
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True)  # nullable for ad-hoc URLs
    url = Column(String, nullable=False, index=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    content_hash = Column(String, nullable=False, index=True)  # SHA-256 of normalised text
    raw_text_path = Column(String, nullable=True)              # path to saved text file on disk

    source = relationship("Source", back_populates="snapshots")


class Run(Base):
    """One pipeline execution — tracks agent outcomes and links to findings/digests."""
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, default="running")         # running|completed|failed|partial
    agent_statuses_json = Column(Text, default="{}")   # JSON {agent_type: "completed"|"failed"|"timeout"}
    agent_logs_json = Column(Text, default="{}")        # JSON {agent_type: [{msg, status}]}
    triggered_by = Column(String, default="scheduler") # "scheduler" or "manual"

    findings = relationship("Finding", back_populates="run")
    digests = relationship("Digest", back_populates="run")


class Finding(Base):
    """One structured intelligence finding produced by an agent for a single run."""
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True)
    agent_type = Column(String, nullable=False)    # which agent produced this finding
    title = Column(String, nullable=False)
    date_detected = Column(DateTime, default=datetime.utcnow)
    source_url = Column(String, nullable=False)
    publisher = Column(String, nullable=True)
    category = Column(String, nullable=True)       # Models|APIs|Pricing|Benchmarks|Safety|Tooling|Research
    summary_short = Column(Text, nullable=True)    # ≤ 60-word single sentence
    summary_long = Column(Text, nullable=True)     # bullet-point detail block
    why_it_matters = Column(Text, nullable=True)
    evidence_json = Column(Text, default="[]")     # JSON list of direct quotes from source
    confidence = Column(Float, default=0.5)        # 0.0–1.0: how certain the LLM is
    tags_json = Column(Text, default="[]")         # JSON list of searchable tags
    entities_json = Column(Text, default="[]")     # JSON list of company/model/dataset names
    diff_hash = Column(String, nullable=True, index=True)  # SHA-256 of source text (dedup key)
    impact_score = Column(Float, default=0.0)      # composite 0–1 score for ranking
    created_at = Column(DateTime, default=datetime.utcnow)

    run = relationship("Run", back_populates="findings")
    source = relationship("Source", back_populates="findings")


class Digest(Base):
    """Daily digest record — links a run to its PDF output and email delivery status."""
    __tablename__ = "digests"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    pdf_path = Column(String, nullable=True)       # absolute path to the rendered PDF file
    html_summary = Column(Text, nullable=True)     # exec summary HTML (also used in email body)
    recipients_json = Column(Text, default="[]")   # JSON list of email addresses the digest was sent to
    email_sent = Column(Boolean, default=False)
    email_sent_at = Column(DateTime, nullable=True)

    run = relationship("Run", back_populates="digests")
