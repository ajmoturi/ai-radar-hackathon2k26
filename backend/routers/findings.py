"""Findings API — filterable explorer and analytics endpoints.

Endpoints:
  GET /api/findings              — paginated finding list with rich filter support
  GET /api/findings/stats/entities — entity-category cross-counts for Entity Heatmap
  GET /api/findings/stats/summary  — aggregate stats (by category, agent, publisher)
  GET /api/findings/{id}          — single finding with full evidence list
  GET /api/findings/{id}/diff     — unified text diff between the two latest snapshots
"""
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Finding

router = APIRouter(prefix="/api/findings", tags=["findings"])


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
        "confidence": f.confidence,
        "tags": json.loads(f.tags_json or "[]"),
        "entities": json.loads(f.entities_json or "[]"),
        "impact_score": f.impact_score,
    }


@router.get("")
def list_findings(
    agent_type: Optional[str] = None,   # filter by agent (competitor|model_provider|research|hf_benchmark)
    category: Optional[str] = None,    # filter by category (Models|APIs|Benchmarks|...)
    publisher: Optional[str] = None,   # partial-match publisher name
    entity: Optional[str] = None,      # partial-match entity name in entities_json
    since: Optional[str] = None,       # ISO 8601 date string lower bound
    run_id: Optional[int] = None,      # restrict to a specific run
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Return a paginated, filterable list of findings sorted by impact_score desc."""
    q = db.query(Finding)

    if agent_type:
        q = q.filter(Finding.agent_type == agent_type)
    if category:
        q = q.filter(Finding.category == category)
    if publisher:
        q = q.filter(Finding.publisher.ilike(f"%{publisher}%"))
    if entity:
        # entities_json is a JSON string — ILIKE gives a fast substring match.
        q = q.filter(Finding.entities_json.ilike(f"%{entity}%"))
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            q = q.filter(Finding.date_detected >= since_dt)
        except ValueError:
            pass  # ignore invalid date strings
    if run_id:
        q = q.filter(Finding.run_id == run_id)

    total = q.count()
    findings = (
        q.order_by(Finding.impact_score.desc(), Finding.date_detected.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"total": total, "findings": [_finding_to_dict(f) for f in findings]}


@router.get("/stats/entities")
def entity_heatmap(db: Session = Depends(get_db)):
    """Return entity vs category cross-counts for the Entity Heatmap visualization."""
    from collections import defaultdict
    findings = db.query(Finding).all()
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    all_categories: set[str] = set()
    for f in findings:
        cat = f.category or "Other"
        all_categories.add(cat)
        for ent in json.loads(f.entities_json or "[]"):
            ent = ent.strip()
            if ent and len(ent) <= 60:
                counts[ent][cat] += 1
    # Keep top 15 entities by total count
    ranked = sorted(counts.items(), key=lambda x: sum(x[1].values()), reverse=True)[:15]
    categories = sorted(all_categories)
    return {
        "entities": [{"entity": e, "counts": dict(c)} for e, c in ranked],
        "categories": categories,
    }


@router.get("/{finding_id}/diff")
def get_finding_diff(finding_id: int, db: Session = Depends(get_db)):
    """Return unified text diff between the two most recent snapshots for a finding's source URL."""
    import difflib
    from pathlib import Path
    from fastapi import HTTPException
    from backend.models import Snapshot

    f = db.query(Finding).filter(Finding.id == finding_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")

    snaps = (
        db.query(Snapshot)
        .filter(Snapshot.url == f.source_url)
        .order_by(Snapshot.fetched_at.desc())
        .limit(2)
        .all()
    )
    if len(snaps) < 2:
        return {"has_diff": False, "message": "No previous snapshot to diff against"}

    current_snap, prev_snap = snaps[0], snaps[1]
    try:
        curr_text = Path(current_snap.raw_text_path).read_text(encoding="utf-8") if current_snap.raw_text_path else ""
        prev_text = Path(prev_snap.raw_text_path).read_text(encoding="utf-8") if prev_snap.raw_text_path else ""
    except Exception:
        return {"has_diff": False, "message": "Snapshot files not readable"}

    diff_lines = list(difflib.unified_diff(
        prev_text.splitlines(),
        curr_text.splitlines(),
        fromfile=f"prev ({prev_snap.fetched_at.strftime('%Y-%m-%d')})",
        tofile=f"curr ({current_snap.fetched_at.strftime('%Y-%m-%d')})",
        lineterm="",
        n=3,
    ))
    return {
        "has_diff": len(diff_lines) > 0,
        "diff": diff_lines[:300],
        "prev_date": prev_snap.fetched_at.isoformat(),
        "curr_date": current_snap.fetched_at.isoformat(),
    }


@router.get("/{finding_id}")
def get_finding(finding_id: int, db: Session = Depends(get_db)):
    from fastapi import HTTPException
    f = db.query(Finding).filter(Finding.id == finding_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")
    return {
        **_finding_to_dict(f),
        "summary_long": f.summary_long,
        "evidence": json.loads(f.evidence_json or "[]"),
    }


@router.get("/stats/summary")
def findings_stats(db: Session = Depends(get_db)):
    """Return aggregate stats for the dashboard."""
    from sqlalchemy import func
    total = db.query(Finding).count()
    by_category = (
        db.query(Finding.category, func.count(Finding.id))
        .group_by(Finding.category)
        .all()
    )
    by_agent = (
        db.query(Finding.agent_type, func.count(Finding.id))
        .group_by(Finding.agent_type)
        .all()
    )
    top_publishers = (
        db.query(Finding.publisher, func.count(Finding.id))
        .filter(Finding.publisher.isnot(None))
        .group_by(Finding.publisher)
        .order_by(func.count(Finding.id).desc())
        .limit(10)
        .all()
    )
    return {
        "total": total,
        "by_category": dict(by_category),
        "by_agent": dict(by_agent),
        "top_publishers": dict(top_publishers),
    }
