"""Runs API — pipeline run history and manual trigger.

Endpoints:
  GET  /api/runs              — paginated run list
  GET  /api/runs/{id}         — single run with digest info
  POST /api/runs/trigger      — manually start a pipeline run
  GET  /api/runs/{id}/findings — findings for a specific run

The /trigger endpoint creates the Run record immediately (so the UI can show
"running" status) then executes the full pipeline in a FastAPI background task.
This avoids the Prefect server dependency for on-demand runs.
"""
import asyncio
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Run, Finding

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _run_to_dict(run: Run) -> dict:
    """Serialise a Run ORM object to a plain dict for JSON responses."""
    return {
        "id": run.id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "status": run.status,
        "triggered_by": run.triggered_by,
        "agent_statuses": json.loads(run.agent_statuses_json or "{}"),
        "agent_logs": json.loads(run.agent_logs_json or "{}"),
        "finding_count": len(run.findings) if run.findings else 0,
    }


@router.get("")
def list_runs(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Return a paginated list of runs, most recent first."""
    runs = (
        db.query(Run)
        .order_by(Run.started_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    total = db.query(Run).count()
    return {"total": total, "runs": [_run_to_dict(r) for r in runs]}


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    """Return a single run including its latest digest metadata (if any)."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    result = _run_to_dict(run)

    # Attach digest info (last digest for this run) when available.
    if run.digests:
        digest = run.digests[-1]
        result["digest"] = {
            "id": digest.id,
            "pdf_path": digest.pdf_path,
            "email_sent": digest.email_sent,
            "created_at": digest.created_at.isoformat(),
        }
    return result


@router.post("/trigger", status_code=202)
def trigger_run(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Manually trigger a full pipeline run.

    Creates the Run record synchronously (so the UI sees it immediately at status
    "running"), then kicks off the pipeline as a FastAPI background task.
    Returns run_id so the client can poll /api/runs/{run_id} for live status.
    """
    # Create run record synchronously so UI can poll for status immediately.
    run = Run(triggered_by="manual", status="running", agent_statuses_json="{}")
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id
    background_tasks.add_task(_run_pipeline_background, run_id)
    return {"message": "Pipeline triggered", "status": "running", "run_id": run_id}


def _run_pipeline_background(run_id: int):
    """Execute the full agent pipeline in a FastAPI background thread.

    Mirrors the Prefect daily_pipeline flow but runs directly without a Prefect
    server.  Each agent runs sequentially with a 10-minute timeout; the digest
    is compiled from whatever findings are available even if some agents fail.

    Updates agent_statuses_json and agent_logs_json live so the UI can show
    per-agent progress while the pipeline is still running.
    """
    import asyncio
    import logging
    import json
    from datetime import datetime

    logger = logging.getLogger(__name__)
    db = None
    try:
        from backend.flows.daily_pipeline import (
            _load_sources_from_db_or_yaml,
        )
        from backend.database import SessionLocal
        from backend.models import Run as RunModel

        db = SessionLocal()

        # Inner async function — needed because agents use async/await.
        async def _run():
            from backend.agents.competitor_watcher import CompetitorWatcher
            from backend.agents.model_provider_watcher import ModelProviderWatcher
            from backend.agents.research_scout import ResearchScout
            from backend.agents.hf_benchmark_tracker import HFBenchmarkTracker
            from backend.agents.digest_compiler import DigestCompiler
            from backend.agents.base import Finding

            def _extract_sota_claims(findings) -> list[dict]:
                """Scan model_provider findings for SOTA keyword claims.

                Returns a list of {entity, benchmark, source_url} dicts for
                cross-validation by HFBenchmarkTracker.verify_sota_claims().
                """
                claims = []
                sota_keywords = ["sota", "state of the art", "state-of-the-art", "best-in-class", "outperforms", "leading"]
                for f in findings:
                    if f.agent_type != "model_provider":
                        continue
                    text = f"{f.title} {f.summary_short or ''} {f.summary_long or ''}".lower()
                    if any(kw in text for kw in sota_keywords):
                        for entity in (f.entities or []):
                            claims.append({
                                "entity": entity,
                                "benchmark": f.category or "",
                                "source_url": f.source_url,
                            })
                return claims[:10]  # cap to avoid excessive verification calls

            agent_statuses = {}
            agent_logs = {}
            all_findings = []

            # Agents run in sequence so DB connections and LLM rate limits are respected.
            agents = [
                ("competitor", CompetitorWatcher),
                ("model_provider", ModelProviderWatcher),
                ("research", ResearchScout),
                ("hf_benchmark", HFBenchmarkTracker),
            ]

            for agent_type, AgentClass in agents:
                agent_logs[agent_type] = []
                try:
                    sources = _load_sources_from_db_or_yaml(db, agent_type)
                    agent = AgentClass(db)
                    agent_logs[agent_type].append({"msg": f"Starting — {len(sources)} sources configured", "status": "info"})
                    # 10-minute hard timeout per agent — prevents a single slow source
                    # from blocking the entire pipeline.
                    findings = await asyncio.wait_for(
                        agent.run(run_id, sources),
                        timeout=600,
                    )
                    all_findings.extend(findings)
                    agent_statuses[agent_type] = "completed"
                    agent_logs[agent_type].append({"msg": f"Completed — {len(findings)} findings", "status": "success"})
                    logger.info(f"Agent {agent_type}: {len(findings)} findings")
                    # Flush status + logs to DB after each agent so the UI shows live progress.
                    run_record = db.query(RunModel).filter(RunModel.id == run_id).first()
                    if run_record:
                        run_record.agent_statuses_json = json.dumps(agent_statuses)
                        run_record.agent_logs_json = json.dumps(agent_logs)
                        db.commit()
                except asyncio.TimeoutError:
                    logger.error(f"Agent {agent_type} timed out after 10 minutes")
                    agent_statuses[agent_type] = "timeout"
                    agent_logs[agent_type].append({"msg": "Timed out after 10 minutes", "status": "error"})
                except Exception as e:
                    logger.error(f"Agent {agent_type} failed: {e}", exc_info=True)
                    agent_statuses[agent_type] = "failed"
                    agent_logs[agent_type].append({"msg": f"Error: {str(e)}", "status": "error"})

            # ---- SOTA claim cross-validation (Agent 4 verifies Agent 2 claims) ----
            try:
                sota_claims = _extract_sota_claims(all_findings)
                if sota_claims:
                    hf_agent = HFBenchmarkTracker(db)
                    verification_findings = await asyncio.wait_for(
                        hf_agent.verify_sota_claims(sota_claims, run_id),
                        timeout=60,  # shorter timeout — just one API call
                    )
                    all_findings.extend(verification_findings)
                    agent_logs.setdefault("hf_benchmark", []).append({
                        "msg": f"SOTA verification: checked {len(sota_claims)} claims, {len(verification_findings)} results",
                        "status": "info",
                    })
            except Exception as e:
                logger.warning(f"SOTA claim verification failed: {e}")

            # ---- Compile digest: dedup → rank → PDF → email ----
            compiler = DigestCompiler(db)
            compiler.compile(run_id=run_id, findings=all_findings)

            # ---- Finalize run record ----
            run_record = db.query(RunModel).filter(RunModel.id == run_id).first()
            if run_record:
                run_record.finished_at = datetime.utcnow()
                failed = [k for k, v in agent_statuses.items() if v in ("failed", "timeout")]
                run_record.status = "partial" if failed else "completed"
                run_record.agent_statuses_json = json.dumps(agent_statuses)
                run_record.agent_logs_json = json.dumps(agent_logs)
                db.commit()

        asyncio.run(_run())

    except Exception as e:
        logger.error(f"Pipeline run {run_id} failed: {e}", exc_info=True)
        if db:
            try:
                from backend.models import Run as RunModel
                run_record = db.query(RunModel).filter(RunModel.id == run_id).first()
                if run_record:
                    run_record.status = "failed"
                    run_record.finished_at = datetime.utcnow()
                    db.commit()
            except Exception:
                pass
    finally:
        if db:
            db.close()


@router.get("/{run_id}/findings")
def get_run_findings(
    run_id: int,
    agent_type: Optional[str] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Return all findings for a run, optionally filtered by agent_type or category."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    q = db.query(Finding).filter(Finding.run_id == run_id)
    if agent_type:
        q = q.filter(Finding.agent_type == agent_type)
    if category:
        q = q.filter(Finding.category == category)

    findings = q.order_by(Finding.impact_score.desc()).all()
    return [_finding_to_dict(f) for f in findings]


def _finding_to_dict(f: Finding) -> dict:
    """Serialise a Finding ORM object to a plain dict for JSON responses."""
    return {
        "id": f.id,
        "run_id": f.run_id,
        "agent_type": f.agent_type,
        "title": f.title,
        "date_detected": f.date_detected.isoformat() if f.date_detected else None,
        "source_url": f.source_url,
        "publisher": f.publisher,
        "category": f.category,
        "summary_short": f.summary_short,
        "summary_long": f.summary_long,
        "why_it_matters": f.why_it_matters,
        "evidence": json.loads(f.evidence_json or "[]"),
        "confidence": f.confidence,
        "tags": json.loads(f.tags_json or "[]"),
        "entities": json.loads(f.entities_json or "[]"),
        "impact_score": f.impact_score,
    }
