"""Digests API — archive and PDF download.

Endpoints:
  GET /api/digests              — paginated list of compiled digests, newest first
  GET /api/digests/{id}         — single digest metadata record
  GET /api/digests/{id}/download — stream the PDF file (or HTML fallback) to the browser

The digest archive lets users browse and re-download past daily intelligence
reports without re-running the pipeline.
"""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Digest

router = APIRouter(prefix="/api/digests", tags=["digests"])


def _digest_to_dict(d: Digest) -> dict:
    """Serialise a Digest ORM object to a plain dict for JSON responses.

    has_pdf is computed at runtime by checking whether the PDF file still
    exists on disk — the path is stored in the DB but the file could be
    deleted or moved after the fact.
    """
    return {
        "id": d.id,
        "run_id": d.run_id,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "pdf_path": d.pdf_path,
        "html_summary": d.html_summary,
        "recipients": json.loads(d.recipients_json or "[]"),  # list of email addresses
        "email_sent": d.email_sent,
        "email_sent_at": d.email_sent_at.isoformat() if d.email_sent_at else None,
        # Dynamically check disk — pdf_path may exist in DB even if file was removed.
        "has_pdf": bool(d.pdf_path and Path(d.pdf_path).exists()),
    }


@router.get("")
def list_digests(
    limit: int = 30,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Return a paginated list of digests sorted by creation time (newest first)."""
    digests = (
        db.query(Digest)
        .order_by(Digest.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    total = db.query(Digest).count()
    return {"total": total, "digests": [_digest_to_dict(d) for d in digests]}


@router.get("/{digest_id}")
def get_digest(digest_id: int, db: Session = Depends(get_db)):
    """Return metadata for a single digest by ID."""
    digest = db.query(Digest).filter(Digest.id == digest_id).first()
    if not digest:
        raise HTTPException(status_code=404, detail="Digest not found")
    return _digest_to_dict(digest)


@router.get("/{digest_id}/download")
def download_digest(digest_id: int, db: Session = Depends(get_db)):
    """Stream the PDF digest file to the browser as an attachment.

    If WeasyPrint failed during compilation, the PDF renderer saves an HTML
    fallback alongside the expected PDF path (same name, .html extension).
    This endpoint transparently serves the HTML fallback when the PDF is absent
    so users can still access the digest content.
    """
    digest = db.query(Digest).filter(Digest.id == digest_id).first()
    if not digest:
        raise HTTPException(status_code=404, detail="Digest not found")

    pdf_path = digest.pdf_path
    if not pdf_path or not Path(pdf_path).exists():
        # PDF missing — check for the WeasyPrint HTML fallback at the same location.
        html_path = (pdf_path or "").replace(".pdf", ".html")
        if html_path and Path(html_path).exists():
            return FileResponse(
                html_path,
                media_type="text/html",
                filename=Path(html_path).name,
            )
        raise HTTPException(status_code=404, detail="Digest file not found")

    # Serve the PDF with the correct MIME type so browsers open the viewer.
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=Path(pdf_path).name,
    )
