"""Prefect flow: orchestrates all 4 agents + digest compiler.

This is the primary scheduled entry point for the Frontier AI Radar pipeline.
It runs once per day (configured via Prefect deployment schedule) and can also
be triggered manually via the /api/runs/trigger REST endpoint.

Pipeline overview:
  1. Create a Run record in the DB (status = "running")
  2. Submit all 4 agent tasks to Prefect's task runner in parallel
  3. Await results with raise_on_failure=False (partial failure is tolerated)
  4. Compile digest: dedup → rank → PDF → email
  5. Finalize Run record (status = completed | partial | failed)

Parallel execution:
  Prefect submits agent tasks concurrently via .submit() and collects results
  with .result(). Each agent task opens its own DB session (SessionLocal) to
  avoid cross-thread session sharing issues.

Source loading priority:
  DB sources (enabled=True) → YAML defaults (config_store/default_sources.yaml)
  The DB takes precedence so UI-managed sources are always used when available.
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from prefect import flow, task, get_run_logger

from backend.database import SessionLocal, init_db
from backend.models import Run
from backend.config import settings

logger = logging.getLogger(__name__)


def _load_sources_from_db_or_yaml(db, agent_type: str) -> list[dict]:
    """Load enabled sources for a given agent type from DB, fall back to YAML defaults.

    Each returned dict has the same keys regardless of source (DB or YAML):
    id, name, agent_type, urls, rss_feeds, selectors, keywords, rate_limit, enabled.
    """
    from backend.models import Source
    import json as _json

    # Query DB for enabled sources of this agent type.
    sources = db.query(Source).filter(
        Source.agent_type == agent_type,
        Source.enabled == True,
    ).all()

    if sources:
        # Deserialise JSON-encoded list/dict columns back into Python objects.
        return [
            {
                "id": s.id,
                "name": s.name,
                "agent_type": s.agent_type,
                "urls": _json.loads(s.urls_json or "[]"),
                "rss_feeds": _json.loads(s.rss_feeds_json or "[]"),
                "selectors": _json.loads(s.selectors_json or "{}"),
                "keywords": _json.loads(s.keywords_json or "[]"),
                "rate_limit": s.rate_limit,
                "enabled": s.enabled,
            }
            for s in sources
        ]

    # No DB sources found — fall back to the bundled YAML configuration.
    return _load_yaml_sources(agent_type)


def _load_yaml_sources(agent_type: str) -> list[dict]:
    """Parse default_sources.yaml and return sources for the given agent_type.

    The YAML uses top-level keys (competitors, model_providers, research,
    hf_benchmarks) that map to agent_type values.  Any extra YAML keys not in
    the standard schema are forwarded as-is via the splat at the end of each
    dict — this allows YAML-specific fields (e.g. hf_space_id) to pass through.
    """
    import yaml
    from pathlib import Path

    yaml_path = Path(__file__).parent.parent / "config_store" / "default_sources.yaml"
    if not yaml_path.exists():
        return []

    with open(yaml_path) as f:
        config = yaml.safe_load(f)

    # Map agent_type value → top-level YAML key.
    type_map = {
        "competitor": "competitors",
        "model_provider": "model_providers",
        "research": "research",
        "hf_benchmark": "hf_benchmarks",
    }
    key = type_map.get(agent_type, agent_type)
    sources = config.get(key, [])

    # Normalise each YAML entry into the standard source dict shape.
    normalized = []
    for s in sources:
        normalized.append({
            "id": None,           # YAML sources have no DB id
            "name": s.get("name", ""),
            "agent_type": agent_type,
            "urls": s.get("urls", []),
            "rss_feeds": s.get("rss_feeds", []),
            "selectors": s.get("selectors", {}),
            "keywords": s.get("keywords", []),
            "rate_limit": s.get("rate_limit", 1.0),
            "enabled": True,
            # Forward any extra YAML-specific keys (e.g. hf_space_id, arxiv_categories).
            **{k: v for k, v in s.items() if k not in (
                "name", "agent_type", "urls", "rss_feeds", "selectors",
                "keywords", "rate_limit", "enabled"
            )},
        })
    return normalized


# ---- Prefect agent tasks ----
# Each task is decorated with retries=2 so transient network errors (rate limits,
# timeouts) are automatically retried before being marked as failed.
# Each task opens its own DB session because SQLAlchemy sessions are not
# thread-safe and Prefect may run tasks in separate threads.

@task(name="run-competitor-agent", retries=2, retry_delay_seconds=30)
async def run_competitor_agent(run_id: int) -> list[dict]:
    """Prefect task wrapper for CompetitorWatcher.

    Returns serialised finding dicts (model_dump) so results can be passed
    across Prefect task boundaries (must be JSON-serialisable).
    """
    log = get_run_logger()
    log.info("Starting Competitor Watcher agent")
    db = SessionLocal()
    try:
        from backend.agents.competitor_watcher import CompetitorWatcher
        sources = _load_sources_from_db_or_yaml(db, "competitor")
        agent = CompetitorWatcher(db)
        findings = await agent.run(run_id, sources)
        log.info(f"Competitor agent: {len(findings)} findings")
        # Serialise Pydantic Finding objects to dicts for cross-task transport.
        return [f.model_dump() for f in findings]
    except Exception as e:
        log.error(f"Competitor agent failed: {e}")
        return []
    finally:
        db.close()


@task(name="run-model-provider-agent", retries=2, retry_delay_seconds=30)
async def run_model_provider_agent(run_id: int) -> list[dict]:
    """Prefect task wrapper for ModelProviderWatcher."""
    log = get_run_logger()
    log.info("Starting Model Provider Watcher agent")
    db = SessionLocal()
    try:
        from backend.agents.model_provider_watcher import ModelProviderWatcher
        sources = _load_sources_from_db_or_yaml(db, "model_provider")
        agent = ModelProviderWatcher(db)
        findings = await agent.run(run_id, sources)
        log.info(f"Model provider agent: {len(findings)} findings")
        return [f.model_dump() for f in findings]
    except Exception as e:
        log.error(f"Model provider agent failed: {e}")
        return []
    finally:
        db.close()


@task(name="run-research-agent", retries=2, retry_delay_seconds=30)
async def run_research_agent(run_id: int) -> list[dict]:
    """Prefect task wrapper for ResearchScout (arXiv + direct URL crawling)."""
    log = get_run_logger()
    log.info("Starting Research Scout agent")
    db = SessionLocal()
    try:
        from backend.agents.research_scout import ResearchScout
        sources = _load_sources_from_db_or_yaml(db, "research")
        agent = ResearchScout(db)
        findings = await agent.run(run_id, sources)
        log.info(f"Research agent: {len(findings)} findings")
        return [f.model_dump() for f in findings]
    except Exception as e:
        log.error(f"Research agent failed: {e}")
        return []
    finally:
        db.close()


@task(name="run-hf-benchmark-agent", retries=2, retry_delay_seconds=30)
async def run_hf_benchmark_agent(run_id: int) -> list[dict]:
    """Prefect task wrapper for HFBenchmarkTracker (HF Hub API + leaderboard pages)."""
    log = get_run_logger()
    log.info("Starting HF Benchmark Tracker agent")
    db = SessionLocal()
    try:
        from backend.agents.hf_benchmark_tracker import HFBenchmarkTracker
        sources = _load_sources_from_db_or_yaml(db, "hf_benchmark")
        agent = HFBenchmarkTracker(db)
        findings = await agent.run(run_id, sources)
        log.info(f"HF benchmark agent: {len(findings)} findings")
        return [f.model_dump() for f in findings]
    except Exception as e:
        log.error(f"HF benchmark agent failed: {e}")
        return []
    finally:
        db.close()


@task(name="compile-digest")
def compile_digest(run_id: int, all_findings_dicts: list[dict]) -> Optional[str]:
    """Prefect task: dedup, rank, generate PDF, and send email digest.

    Accepts findings as plain dicts (from cross-task transport) and
    re-hydrates them into Finding Pydantic objects before passing to
    DigestCompiler.  Returns the path to the generated PDF (or HTML fallback),
    or None if compilation failed entirely.
    """
    log = get_run_logger()
    log.info(f"Compiling digest from {len(all_findings_dicts)} findings")
    db = SessionLocal()
    try:
        from backend.agents.digest_compiler import DigestCompiler
        from backend.agents.base import Finding
        # Re-hydrate plain dicts → Pydantic Finding objects for type safety.
        findings = [Finding(**f) for f in all_findings_dicts if f]
        compiler = DigestCompiler(db)
        pdf_path = compiler.compile(run_id=run_id, findings=findings)
        log.info(f"Digest compiled: {pdf_path}")
        return pdf_path
    except Exception as e:
        log.error(f"Digest compilation failed: {e}")
        return None
    finally:
        db.close()


# ---- Run lifecycle helpers ----

def _create_run(triggered_by: str = "scheduler") -> int:
    """Insert a new Run record with status 'running' and return its DB id.

    Called synchronously before agents start so the UI can show the run
    immediately while it is still in progress.
    """
    db = SessionLocal()
    try:
        run = Run(triggered_by=triggered_by, agent_statuses_json="{}")
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


def _finalize_run(run_id: int, agent_statuses: dict, pdf_path: Optional[str]):
    """Update the Run record after all tasks complete.

    Status logic:
      - All agents succeeded + PDF produced  → "completed"
      - Some agents failed  but PDF produced → "partial"
      - PDF not produced (all agents failed) → "failed"
    """
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == run_id).first()
        if run:
            run.finished_at = datetime.utcnow()
            failed = [k for k, v in agent_statuses.items() if v == "failed"]
            if pdf_path:
                # At least some findings made it through — mark partial if any agent failed.
                run.status = "partial" if failed else "completed"
            else:
                # No digest produced — treat the whole run as failed.
                run.status = "failed"
            run.agent_statuses_json = json.dumps(agent_statuses)
            db.commit()
    finally:
        db.close()


# ---- Main Prefect flow ----

@flow(
    name="frontier-ai-radar-daily",
    description="Daily multi-agent AI intelligence pipeline",
)
async def daily_pipeline(triggered_by: str = "scheduler"):
    """Main Prefect flow: runs all 4 agents in parallel, then compiles the digest.

    Agents are submitted concurrently via Prefect's task runner (.submit()).
    Results are collected with raise_on_failure=False so a single failing agent
    does not abort the entire pipeline — the digest is compiled from whatever
    findings are available.

    The flow is also callable directly (python -m backend.flows.daily_pipeline)
    for ad-hoc runs without a running Prefect server.
    """
    log = get_run_logger()
    log.info(f"Starting daily pipeline (triggered_by={triggered_by})")

    # Ensure DB schema exists before any agent touches it.
    init_db()
    run_id = _create_run(triggered_by)
    log.info(f"Created run #{run_id}")

    # Submit all 4 agents to run concurrently — Prefect schedules them in parallel.
    competitor_task = run_competitor_agent.submit(run_id)
    model_task = run_model_provider_agent.submit(run_id)
    research_task = run_research_agent.submit(run_id)
    hf_task = run_hf_benchmark_agent.submit(run_id)

    # Await results; raise_on_failure=False means a task exception returns None
    # instead of propagating and killing the flow.
    competitor_findings = competitor_task.result(raise_on_failure=False) or []
    model_findings = model_task.result(raise_on_failure=False) or []
    research_findings = research_task.result(raise_on_failure=False) or []
    hf_findings = hf_task.result(raise_on_failure=False) or []

    # Determine per-agent status: empty result list → "failed" (either the task
    # raised an exception or the agent genuinely found nothing).
    agent_statuses = {
        "competitor": "completed" if competitor_findings else "failed",
        "model_provider": "completed" if model_findings else "failed",
        "research": "completed" if research_findings else "failed",
        "hf_benchmark": "completed" if hf_findings else "failed",
    }

    # Merge all agent findings into a single flat list for the digest compiler.
    all_findings = competitor_findings + model_findings + research_findings + hf_findings
    log.info(f"Total findings before dedup: {len(all_findings)}")

    # Compile digest (dedup → rank → PDF → email) and update run record.
    pdf_path = compile_digest(run_id, all_findings)
    _finalize_run(run_id, agent_statuses, pdf_path)

    log.info(f"Pipeline complete. Run #{run_id} | PDF: {pdf_path}")
    return run_id


if __name__ == "__main__":
    # Direct execution: python -m backend.flows.daily_pipeline
    # Useful for one-off runs or local testing without a Prefect server.
    asyncio.run(daily_pipeline(triggered_by="manual"))
