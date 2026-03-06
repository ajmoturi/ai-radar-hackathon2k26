"""FastAPI application entry point.

Responsibilities:
  - Create the FastAPI app with CORS middleware.
  - Register all API routers (sources, runs, findings, digests).
  - Run DB migrations and clean up orphaned run records on startup.
  - Expose /api/health and /api/health/llm check endpoints.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import init_db
from backend.routers import sources, runs, digests, findings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle hook registered with FastAPI."""
    # Ensure all DB tables exist (idempotent).
    init_db()
    # Any run left in "running" state means the server crashed mid-pipeline;
    # mark them failed so the UI doesn't show them as stuck forever.
    _cleanup_orphaned_runs()
    yield


def _cleanup_orphaned_runs():
    """Mark stale 'running' runs as failed on startup.

    Background tasks are lost when the process restarts, so any run that was
    still 'running' at shutdown will never complete — mark it failed instead.
    """
    import json
    from datetime import datetime
    from backend.database import SessionLocal
    from backend.models import Run

    db = SessionLocal()
    try:
        stale = db.query(Run).filter(Run.status == "running").all()
        for run in stale:
            run.status = "failed"
            run.finished_at = datetime.utcnow()
            run.agent_statuses_json = json.dumps({"note": "orphaned - server restarted"})
        if stale:
            db.commit()
    finally:
        db.close()


app = FastAPI(
    title="Frontier AI Radar API",
    description="Daily multi-agent AI intelligence system",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow the Next.js dev server (localhost:3000) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register feature routers — each owns its own URL prefix.
app.include_router(sources.router)
app.include_router(runs.router)
app.include_router(digests.router)
app.include_router(findings.router)


@app.get("/api/health")
def health_check():
    """Simple liveness probe — returns 200 when the server is up."""
    return {"status": "ok", "service": "Frontier AI Radar"}


@app.get("/api/health/llm")
def llm_health():
    """Connectivity check for the active LLM provider.

    Sends a minimal API call and returns {ok, provider, error?}.
    Useful for diagnosing API key / credits issues from the frontend.
    """
    from backend.config import settings

    provider = settings.llm_provider

    if provider == "openai":
        # Covers Groq, Ollama, Gemini, or any OpenAI-compatible endpoint.
        if not settings.openai_api_key:
            return {"ok": False, "provider": provider, "error": "OPENAI_API_KEY is not set in .env"}
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
            client.chat.completions.create(
                model=settings.openai_model,
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return {"ok": True, "provider": provider, "model": settings.openai_model, "base_url": settings.openai_base_url}
        except Exception as e:
            return {"ok": False, "provider": provider, "error": str(e)}

    elif provider == "azure_openai":
        if not settings.azure_openai_key:
            return {"ok": False, "provider": provider, "error": "AZURE_OPENAI_KEY is not set in .env"}
        if not settings.azure_openai_endpoint:
            return {"ok": False, "provider": provider, "error": "AZURE_OPENAI_ENDPOINT is not set in .env"}
        try:
            from openai import AzureOpenAI
            client = AzureOpenAI(
                api_key=settings.azure_openai_key,
                azure_endpoint=settings.azure_openai_endpoint,
                api_version=settings.azure_openai_api_version,
            )
            client.chat.completions.create(
                model=settings.azure_openai_deployment,
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return {"ok": True, "provider": provider}
        except Exception as e:
            return {"ok": False, "provider": provider, "error": str(e)}

    else:  # anthropic (default)
        import anthropic
        if not settings.anthropic_api_key:
            return {"ok": False, "provider": provider, "error": "ANTHROPIC_API_KEY is not set in .env"}
        try:
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return {"ok": True, "provider": provider}
        except anthropic.AuthenticationError:
            return {"ok": False, "provider": provider, "error": "Invalid API key — check ANTHROPIC_API_KEY in .env"}
        except anthropic.BadRequestError as e:
            msg = str(e)
            if "credit balance" in msg.lower():
                return {"ok": False, "provider": provider, "error": "Insufficient Anthropic credits — top up at console.anthropic.com/settings/billing"}
            return {"ok": False, "provider": provider, "error": f"API error: {msg}"}
        except Exception as e:
            return {"ok": False, "provider": provider, "error": str(e)}


@app.get("/api/stats")
def global_stats():
    """Return aggregate counts for the dashboard header cards."""
    from backend.database import SessionLocal
    from backend.models import Run, Finding, Digest
    from sqlalchemy import func

    db = SessionLocal()
    try:
        total_runs = db.query(Run).count()
        total_findings = db.query(Finding).count()
        total_digests = db.query(Digest).count()

        last_run = db.query(Run).order_by(Run.started_at.desc()).first()
        last_digest = db.query(Digest).order_by(Digest.created_at.desc()).first()

        # Count findings created since midnight today (UTC).
        from datetime import datetime, date
        today_start = datetime.combine(date.today(), datetime.min.time())
        today_findings = db.query(Finding).filter(Finding.date_detected >= today_start).count()

        return {
            "total_runs": total_runs,
            "total_findings": total_findings,
            "total_digests": total_digests,
            "today_findings": today_findings,
            "last_run": {
                "id": last_run.id,
                "status": last_run.status,
                "started_at": last_run.started_at.isoformat(),
                "finished_at": last_run.finished_at.isoformat() if last_run.finished_at else None,
            } if last_run else None,
            "last_digest": {
                "id": last_digest.id,
                "created_at": last_digest.created_at.isoformat(),
                "email_sent": last_digest.email_sent,
            } if last_digest else None,
        }
    finally:
        db.close()
