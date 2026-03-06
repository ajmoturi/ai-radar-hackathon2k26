"""Sources CRUD — manage crawl sources via API.

Endpoints:
  GET    /api/sources               — list all sources (optional ?agent_type= filter)
  POST   /api/sources               — create a new source
  GET    /api/sources/{id}          — get a single source
  PUT    /api/sources/{id}          — update a source
  DELETE /api/sources/{id}          — delete a source
  POST   /api/sources/seed-defaults — seed DB from default_sources.yaml (idempotent)
"""
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Source

router = APIRouter(prefix="/api/sources", tags=["sources"])


class SourceCreate(BaseModel):
    """Request body for creating a new crawl source."""
    name: str
    agent_type: str  # competitor|model_provider|research|hf_benchmark
    urls: list[str] = []        # direct page URLs to crawl
    rss_feeds: list[str] = []   # RSS/Atom feed URLs
    selectors: dict = {}        # CSS selector hints {content: "..."}
    keywords: list[str] = []    # keyword filters for model_provider agent
    rate_limit: float = 1.0     # max requests/second to this domain
    enabled: bool = True


class SourceUpdate(BaseModel):
    """Request body for partial updates — all fields optional."""
    name: Optional[str] = None
    urls: Optional[list[str]] = None
    rss_feeds: Optional[list[str]] = None
    selectors: Optional[dict] = None
    keywords: Optional[list[str]] = None
    rate_limit: Optional[float] = None
    enabled: Optional[bool] = None


class SourceResponse(BaseModel):
    """Pydantic schema for source API responses."""
    id: int
    name: str
    agent_type: str
    urls: list[str]
    rss_feeds: list[str]
    keywords: list[str]
    rate_limit: float
    enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


def _to_response(s: Source) -> dict:
    """Serialise a Source ORM object to a plain dict, unpacking JSON fields."""
    return {
        "id": s.id,
        "name": s.name,
        "agent_type": s.agent_type,
        "urls": json.loads(s.urls_json or "[]"),
        "rss_feeds": json.loads(s.rss_feeds_json or "[]"),
        "keywords": json.loads(s.keywords_json or "[]"),
        "rate_limit": s.rate_limit,
        "enabled": s.enabled,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


@router.get("")
def list_sources(
    agent_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Return all sources, optionally filtered by agent_type."""
    q = db.query(Source)
    if agent_type:
        q = q.filter(Source.agent_type == agent_type)
    return [_to_response(s) for s in q.all()]


@router.post("", status_code=201)
def create_source(body: SourceCreate, db: Session = Depends(get_db)):
    """Create a new crawl source. JSON list/dict fields are serialised before storage."""
    source = Source(
        name=body.name,
        agent_type=body.agent_type,
        urls_json=json.dumps(body.urls),
        rss_feeds_json=json.dumps(body.rss_feeds),
        selectors_json=json.dumps(body.selectors),
        keywords_json=json.dumps(body.keywords),
        rate_limit=body.rate_limit,
        enabled=body.enabled,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return _to_response(source)


@router.get("/{source_id}")
def get_source(source_id: int, db: Session = Depends(get_db)):
    """Return a single source by ID."""
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return _to_response(source)


@router.put("/{source_id}")
def update_source(source_id: int, body: SourceUpdate, db: Session = Depends(get_db)):
    """Partially update a source — only fields present in the request body are changed."""
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if body.name is not None:
        source.name = body.name
    if body.urls is not None:
        source.urls_json = json.dumps(body.urls)
    if body.rss_feeds is not None:
        source.rss_feeds_json = json.dumps(body.rss_feeds)
    if body.selectors is not None:
        source.selectors_json = json.dumps(body.selectors)
    if body.keywords is not None:
        source.keywords_json = json.dumps(body.keywords)
    if body.rate_limit is not None:
        source.rate_limit = body.rate_limit
    if body.enabled is not None:
        source.enabled = body.enabled
    source.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(source)
    return _to_response(source)


@router.delete("/{source_id}", status_code=204)
def delete_source(source_id: int, db: Session = Depends(get_db)):
    """Permanently delete a source. Use enabled=false to temporarily disable instead."""
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    db.delete(source)
    db.commit()


@router.post("/seed-defaults", status_code=201)
def seed_default_sources(db: Session = Depends(get_db)):
    """Seed the database with the 16 default sources from default_sources.yaml.

    Idempotent: skips sources that already exist (matched by name + agent_type).
    Returns the count of newly created sources.
    """
    import yaml
    from pathlib import Path

    yaml_path = Path(__file__).parent.parent / "config_store" / "default_sources.yaml"
    with open(yaml_path) as f:
        config = yaml.safe_load(f)

    # Map agent_type → YAML top-level key
    type_map = {
        "competitor": "competitors",
        "model_provider": "model_providers",
        "research": "research",
        "hf_benchmark": "hf_benchmarks",
    }

    created = 0
    for agent_type, yaml_key in type_map.items():
        for s in config.get(yaml_key, []):
            # Skip if this source already exists in the DB.
            existing = db.query(Source).filter(
                Source.name == s["name"],
                Source.agent_type == agent_type,
            ).first()
            if existing:
                continue
            source = Source(
                name=s["name"],
                agent_type=agent_type,
                urls_json=json.dumps(s.get("urls", [])),
                rss_feeds_json=json.dumps(s.get("rss_feeds", [])),
                selectors_json=json.dumps(s.get("selectors", {})),
                keywords_json=json.dumps(s.get("keywords", [])),
                rate_limit=s.get("rate_limit", 1.0),
                enabled=True,
            )
            db.add(source)
            created += 1

    db.commit()
    return {"seeded": created}
