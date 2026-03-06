"""Digest Compiler — final stage of the pipeline.

Pipeline steps executed by compile():
  1. Dedup    — remove exact and near-duplicate findings
  2. Rank     — sort by impact_score descending
  3. Narrative — ask LLM to write exec_summary / what_changed / why_it_matters
  4. PDF      — render HTML template → WeasyPrint PDF
  5. Email    — send PDF + exec summary to configured recipients
  6. Persist  — save Digest record to DB

If the LLM narrative step fails, a simple bullet-list fallback is used so the
PDF and email still go out even when the LLM is unavailable.
"""
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend.agents.base import Finding
from backend.models import Digest, Run
from backend.services.change_detector import dedup_findings
from backend.services.email_sender import send_digest_email
from backend.services.pdf_renderer import render_digest_pdf
from backend.services.summarizer import generate_digest_narrative
from backend.config import settings

logger = logging.getLogger(__name__)

# Display order for digest sections (not currently enforced in compiler but used by PDF renderer).
CATEGORY_ORDER = [
    "Foundation Model Updates",
    "Competitor Releases",
    "Research Publications",
    "HF Benchmarks",
    "Other",
]


class DigestCompiler:
    """Orchestrates dedup, ranking, narrative generation, PDF rendering, and email delivery."""

    def __init__(self, db: Session):
        self.db = db

    def compile(
        self,
        run_id: int,
        findings: list[Finding],
        recipients: Optional[list[str]] = None,
        date: Optional[datetime] = None,
    ) -> Optional[str]:
        """Run the full digest pipeline and return the PDF file path (or None on failure).

        Steps: dedup → rank → LLM narrative → PDF → email → DB record.
        """
        if date is None:
            date = datetime.utcnow()

        if not findings:
            logger.warning("No findings to compile into digest")
            return None

        # ---- Step 1: Deduplicate ----
        # Convert Pydantic models to plain dicts for the dedup utility.
        findings_dicts = [f.model_dump() for f in findings]
        unique_dicts = dedup_findings(findings_dicts)
        logger.info(f"Deduped {len(findings)} → {len(unique_dicts)} findings")

        # ---- Step 2: Rank by impact score ----
        ranked = sorted(unique_dicts, key=lambda f: f.get("impact_score", 0), reverse=True)

        # ---- Step 3: Generate executive narrative via LLM ----
        # Feed the top 30 findings to the LLM — beyond that adds noise, not signal.
        top_for_narrative = ranked[:30]
        narrative_input = self._build_narrative_input(top_for_narrative)
        narrative = generate_digest_narrative(narrative_input)

        if narrative:
            exec_summary = narrative.get("exec_summary", "")
            what_changed = narrative.get("what_changed", "")
            why_it_matters = narrative.get("why_it_matters", "")
        else:
            # LLM unavailable — fall back to a simple top-7 bullet list.
            exec_summary = "\n".join(
                f"- {f.get('title', 'Untitled')} ({f.get('publisher', '')})"
                for f in ranked[:7]
            )
            what_changed = "Multiple AI updates detected today."
            why_it_matters = "Stay tuned for detailed analysis."

        # ---- Step 4: Render PDF ----
        pdf_path = render_digest_pdf(
            findings=ranked,
            exec_summary=exec_summary,
            what_changed=what_changed,
            why_it_matters=why_it_matters,
            run_id=run_id,
            date=date,
        )

        # ---- Step 5: Send email ----
        # Use configured recipients if not overridden by caller.
        if not recipients:
            recipients = settings.recipients_list

        email_sent = False
        if recipients:
            date_str = date.strftime("%B %d, %Y")
            email_sent = send_digest_email(
                recipients=recipients,
                date_str=date_str,
                exec_summary=exec_summary,
                pdf_path=pdf_path,
                run_id=run_id,
            )

        # ---- Step 6: Persist digest record ----
        digest = Digest(
            run_id=run_id,
            pdf_path=pdf_path,
            html_summary=exec_summary,
            recipients_json=json.dumps(recipients or []),
            email_sent=email_sent,
            email_sent_at=datetime.utcnow() if email_sent else None,
        )
        self.db.add(digest)
        self.db.commit()

        logger.info(f"Digest compiled: {pdf_path}, email_sent={email_sent}")
        return pdf_path

    def _build_narrative_input(self, findings: list[dict]) -> str:
        """Format ranked findings into a text block for LLM narrative generation.

        Each finding is represented as a short labelled block so the LLM can
        identify themes, group related updates, and write a coherent summary.
        """
        lines = []
        for f in findings:
            lines.append(
                f"[{f.get('category', 'Other')} | {f.get('publisher', '')}] "
                f"{f.get('title', 'Untitled')}\n"
                f"  Summary: {f.get('summary_short', '')}\n"
                f"  Why it matters: {f.get('why_it_matters', '')}\n"
            )
        return "\n".join(lines)
