"""Change detection: content fingerprinting, snapshot persistence, and finding dedup.

Three responsibilities:
  1. Fingerprinting — SHA-256 hashing of normalised page text (via fetcher.compute_hash)
  2. Snapshot management — is_content_changed() + save_snapshot() gate LLM calls
  3. Deduplication — dedup_findings() removes exact and near-duplicate findings before
     the digest is compiled, using both exact hash/URL matching and Jaccard title similarity
"""
from typing import Optional
from sqlalchemy.orm import Session
from backend.models import Snapshot
from backend.services.fetcher import compute_hash
from backend.config import settings
from pathlib import Path
import json


def get_last_snapshot_hash(db: Session, url: str) -> Optional[str]:
    """Return the content_hash of the most recent snapshot for a URL, or None if unseen."""
    snap = (
        db.query(Snapshot)
        .filter(Snapshot.url == url)
        .order_by(Snapshot.fetched_at.desc())
        .first()
    )
    return snap.content_hash if snap else None


def is_content_changed(db: Session, url: str, new_text: str) -> bool:
    """Return True if the page content has changed since the last snapshot.

    Computes the SHA-256 hash of new_text and compares it to the stored hash.
    Returns True (changed) if no previous snapshot exists for this URL.
    """
    new_hash = compute_hash(new_text)
    last_hash = get_last_snapshot_hash(db, url)
    return last_hash != new_hash


def save_snapshot(
    db: Session,
    url: str,
    text: str,
    source_id: Optional[int] = None,
) -> Snapshot:
    """Persist a content snapshot for a URL to the database and disk.

    Writes the raw text to a file in the snapshots directory (for diff viewing)
    and creates a Snapshot record in the DB.
    """
    content_hash = compute_hash(text)

    # Write raw text to disk so the frontend diff view can read it.
    snap_dir = Path(settings.snapshots_dir)
    snap_dir.mkdir(parents=True, exist_ok=True)
    # Build a filesystem-safe filename from the URL + first 8 chars of hash.
    safe_name = url.replace("://", "_").replace("/", "_")[:100]
    text_path = str(snap_dir / f"{safe_name}_{content_hash[:8]}.txt")
    Path(text_path).write_text(text, encoding="utf-8")

    snap = Snapshot(
        source_id=source_id,
        url=url,
        content_hash=content_hash,
        raw_text_path=text_path,
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


def _title_tokens(title: str) -> set[str]:
    """Tokenise a title for Jaccard similarity: lowercase, strip stop words, min length 3."""
    stop = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "is", "with"}
    return {w for w in title.lower().split() if len(w) > 2 and w not in stop}


def _jaccard(a: set, b: set) -> float:
    """Compute Jaccard similarity between two sets.  Returns 0.0 if either set is empty."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedup_findings(findings: list[dict], title_similarity_threshold: float = 0.6) -> list[dict]:
    """Remove duplicate findings before digest compilation.

    Two-stage deduplication:
      1. Exact match on diff_hash or source_url — O(1) set lookup
      2. Semantic title dedup via Jaccard similarity ≥ threshold — catches
         the same story reported by multiple sources

    When duplicates are found, the finding with the higher impact_score is kept.
    """
    seen_hashes: set[str] = set()
    seen_urls: set[str] = set()
    unique: list[dict] = []
    unique_title_tokens: list[set] = []

    for f in findings:
        # ---- Stage 1: Exact dedup ----
        key = f.get("diff_hash") or f.get("source_url", "")
        if key and key in seen_hashes:
            continue
        url = f.get("source_url", "")
        if url and url in seen_urls:
            continue

        # ---- Stage 2: Semantic title dedup ----
        tokens = _title_tokens(f.get("title", ""))
        duplicate_idx = None
        for i, existing_tokens in enumerate(unique_title_tokens):
            if _jaccard(tokens, existing_tokens) >= title_similarity_threshold:
                duplicate_idx = i
                break

        if duplicate_idx is not None:
            # Duplicate found — keep whichever has a higher impact score.
            existing = unique[duplicate_idx]
            if f.get("impact_score", 0) > existing.get("impact_score", 0):
                unique[duplicate_idx] = f
                unique_title_tokens[duplicate_idx] = tokens
            continue

        seen_hashes.add(key)
        if url:
            seen_urls.add(url)
        unique.append(f)
        unique_title_tokens.append(tokens)

    return unique
