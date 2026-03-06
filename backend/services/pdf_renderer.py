"""PDF renderer: Jinja2 HTML template → WeasyPrint PDF.

Pipeline:
  1. Group findings into display sections by agent_type / category
  2. Format datetime objects to human-readable strings
  3. Render backend/templates/digest.html via Jinja2
  4. Convert rendered HTML → PDF using WeasyPrint

WeasyPrint on macOS requires Homebrew GTK libraries in the dynamic linker path:
  export DYLD_LIBRARY_PATH="/opt/homebrew/lib:${DYLD_LIBRARY_PATH}"
This is set in start.sh before launching uvicorn.

Fallback: if WeasyPrint fails (e.g. missing libs), the rendered HTML is saved
instead so the digest is not lost.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from backend.config import settings

logger = logging.getLogger(__name__)

# Jinja2 templates directory — resolved relative to this file's location.
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def render_digest_pdf(
    findings: list[dict],
    exec_summary: str,
    what_changed: str,
    why_it_matters: str,
    run_id: int,
    date: Optional[datetime] = None,
) -> Optional[str]:
    """Render the daily digest as a PDF and return the output file path.

    Groups findings into labelled sections, formats dates, renders the Jinja2
    template to HTML, then converts to PDF via WeasyPrint.
    Falls back to saving HTML if WeasyPrint is unavailable or fails.
    """
    if date is None:
        date = datetime.utcnow()

    date_str = date.strftime("%B %d, %Y")    # e.g. "March 06, 2026"
    date_file = date.strftime("%Y-%m-%d")    # used in the output filename

    # ---- Group findings into digest sections ----
    sections: dict[str, list[dict]] = {
        "Competitor Releases": [],
        "Foundation Model Updates": [],
        "Research Publications": [],
        "HF Benchmarks": [],
        "Other": [],
    }

    # Maps finding.category → display section name (fallback when agent_type is unknown).
    category_map = {
        "Models": "Foundation Model Updates",
        "APIs": "Foundation Model Updates",
        "Pricing": "Competitor Releases",
        "Benchmarks": "HF Benchmarks",
        "Safety": "Research Publications",
        "Tooling": "Competitor Releases",
        "Research": "Research Publications",
    }

    # Primary bucketing by agent_type — more reliable than LLM-assigned category.
    agent_category_map = {
        "competitor": "Competitor Releases",
        "model_provider": "Foundation Model Updates",
        "research": "Research Publications",
        "hf_benchmark": "HF Benchmarks",
    }

    for f in findings:
        agent_type = f.get("agent_type", "")
        section = agent_category_map.get(agent_type)
        if not section:
            # Fall back to category field when agent_type is missing or unrecognised.
            section = category_map.get(f.get("category", ""), "Other")
        sections[section].append(f)

    # ---- Format datetime objects for display ----
    # Jinja2 cannot call .strftime() on raw datetime objects passed from JSON.
    formatted_findings = []
    for f in findings:
        ff = dict(f)
        dt = f.get("date_detected")
        if isinstance(dt, datetime):
            ff["date_detected"] = dt.strftime("%Y-%m-%d %H:%M UTC")
        formatted_findings.append(ff)

    # Build per-section finding lists with formatted dates.
    formatted_sections = {}
    for sec, sec_findings in sections.items():
        if sec_findings:
            formatted_sec = []
            for f in sec_findings:
                ff = dict(f)
                dt = f.get("date_detected")
                if isinstance(dt, datetime):
                    ff["date_detected"] = dt.strftime("%Y-%m-%d %H:%M UTC")
                formatted_sec.append(ff)
            formatted_sections[sec] = formatted_sec

    # ---- Render Jinja2 template to HTML ----
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("digest.html")
    html = template.render(
        date=date_str,
        exec_summary=exec_summary,
        what_changed=what_changed,
        why_it_matters=why_it_matters,
        sections=formatted_sections,
        all_findings=formatted_findings,
        total_findings=len(findings),
        agent_count=len(set(f.get("agent_type", "") for f in findings)),
    )

    pdf_dir = Path(settings.pdf_dir)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = str(pdf_dir / f"digest_{date_file}_run{run_id}.pdf")

    # ---- Convert HTML → PDF via WeasyPrint ----
    try:
        from weasyprint import HTML
        # base_url=TEMPLATE_DIR resolves relative CSS/image paths in the template.
        HTML(string=html, base_url=str(TEMPLATE_DIR)).write_pdf(pdf_path)
        logger.info(f"PDF rendered: {pdf_path}")
        return pdf_path
    except Exception as e:
        logger.error(f"PDF render failed: {e}")
        # WeasyPrint unavailable — save raw HTML so the digest is not lost.
        html_path = pdf_path.replace(".pdf", ".html")
        Path(html_path).write_text(html, encoding="utf-8")
        logger.info(f"Saved HTML fallback: {html_path}")
        return html_path
