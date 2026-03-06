# Frontier AI Radar

A daily multi-agent intelligence system that automatically tracks frontier AI developments — crawling competitor sites, model provider announcements, research papers, and benchmark leaderboards — then compiles everything into a PDF digest and emails it to your team.

## Features

- **4 specialized agents** run in parallel: competitor watcher, model provider watcher, research scout, HF benchmark tracker
- **Change detection** via SHA-256 content hashing — LLM is only called when a page actually changes, saving API costs
- **Structured LLM summarization** using Claude tool-use (or Groq / Azure OpenAI / any OpenAI-compatible API)
- **SOTA cross-validation** — model provider SOTA claims are automatically verified against HuggingFace leaderboard data
- **Two-stage deduplication** — exact hash/URL match + Jaccard title similarity to remove near-duplicates
- **PDF digest** rendered with WeasyPrint + Jinja2, with HTML fallback if GTK libs are unavailable
- **Email delivery** via SMTP (Gmail / any provider) or SendGrid
- **Web dashboard** — live run status, findings explorer, digest archive, analytics, and sources CRUD
- **Manual trigger** via the dashboard — no Prefect server required for on-demand runs

---

## Architecture

```
backend/
├── agents/
│   ├── base.py                   # Finding Pydantic schema + BaseAgent ABC
│   ├── competitor_watcher.py     # Crawls AI company blogs & RSS feeds (concurrency: 3)
│   ├── model_provider_watcher.py # Monitors model provider release notes + SOTA claims
│   ├── research_scout.py         # Pulls new arXiv papers (cs.CL, cs.LG) + direct URLs
│   ├── hf_benchmark_tracker.py   # Tracks HuggingFace trending models & leaderboards
│   └── digest_compiler.py        # Dedup → rank → PDF → email pipeline
├── services/
│   ├── summarizer.py             # Multi-provider LLM (Anthropic / Azure / OpenAI-compat)
│   ├── fetcher.py                # Rate-limited HTTP + Playwright fallback for JS pages
│   ├── extractor.py              # trafilatura article extraction + metadata parsing
│   ├── change_detector.py        # SHA-256 change detection + snapshot persistence
│   ├── email_sender.py           # SMTP / SendGrid email with HTML + text parts
│   └── pdf_renderer.py           # WeasyPrint + Jinja2 PDF generation
├── routers/
│   ├── sources.py                # GET/POST/PUT/DELETE /api/sources + seed endpoint
│   ├── runs.py                   # GET /api/runs + POST /api/runs/trigger
│   ├── findings.py               # GET /api/findings + stats endpoints
│   └── digests.py                # GET /api/digests + PDF download
├── flows/
│   └── daily_pipeline.py         # Prefect flow: 4 parallel agents + digest
├── models.py                     # SQLAlchemy ORM: Source, Snapshot, Run, Finding, Digest
├── config.py                     # Pydantic-settings: all env var bindings
├── database.py                   # SQLAlchemy engine + session factory
├── main.py                       # FastAPI app: CORS, routers, startup lifecycle
├── config_store/
│   └── default_sources.yaml      # 16 pre-configured crawl sources
└── templates/
    └── digest.html               # Jinja2 template for PDF digest

frontend/
├── app/
│   ├── page.tsx                  # Overview dashboard (stats + recent findings)
│   ├── sources/page.tsx          # Sources CRUD (add / edit / enable / delete)
│   ├── runs/page.tsx             # Pipeline run history + per-agent status
│   ├── runs/[id]/page.tsx        # Single run detail view
│   ├── findings/page.tsx         # Filterable findings explorer
│   ├── analytics/page.tsx        # Entity heatmap + SOTA watch leaderboard
│   └── digests/page.tsx          # Digest archive + PDF download
└── lib/api.ts                    # Typed API client (all endpoints + TypeScript types)
```

---

## Prerequisites

- **Python 3.11+**
- **Node.js 18+** and **npm**
- An LLM API key — pick one:
  - **Anthropic** — get one at [console.anthropic.com](https://console.anthropic.com) (default)
  - **Groq** (free tier) — [console.groq.com](https://console.groq.com)
  - **Azure OpenAI**, **OpenAI**, or any OpenAI-compatible endpoint
- (Optional) SMTP credentials or SendGrid key for email delivery

> **WeasyPrint system libraries** (pango, cairo, libffi, gdk-pixbuf) are installed automatically by `start.sh` on macOS and Linux. Windows users need to install [GTK3 Runtime](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer) manually for PDF generation.

---

## Setup

### 1. Clone the repository

**macOS / Linux / Windows (WSL2 or Git Bash):**
```bash
git clone https://github.com/navneetcentific/hackathon_frontier_ai_radar.git
cd hackathon_frontier_ai_radar
```

**Windows (PowerShell or CMD):**
```powershell
git clone https://github.com/navneetcentific/hackathon_frontier_ai_radar.git
cd hackathon_frontier_ai_radar
```

---

### 2. Create Python virtual environment

**macOS / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
```

**Windows PowerShell:**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**Windows CMD:**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

---

### 3. Install Python dependencies

**All platforms (run after activating virtual environment):**
```bash
pip install -e ".[dev]"
```

---

### 4. Install Playwright browser (for JS-heavy sites)

**All platforms:**
```bash
playwright install chromium
```

---

### 5. Configure environment variables

**macOS / Linux:**
```bash
cp .env.example .env
```

**Windows PowerShell:**
```powershell
Copy-Item .env.example .env
```

**Windows CMD:**
```cmd
copy .env.example .env
```

Edit `.env` and set at minimum one LLM provider key:

```env
# ---- LLM Provider (choose one) ----

# Option A: Anthropic Claude (default)
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Option B: Groq (free tier, fast)
LLM_PROVIDER=openai
OPENAI_API_KEY=gsk_...
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_MODEL=llama-3.3-70b-versatile

# Option C: Azure OpenAI
LLM_PROVIDER=azure_openai
AZURE_OPENAI_KEY=...
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=gpt-4o

# Option D: OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

# ---- Email delivery (optional) ----
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASS=your_app_password      # Use a Gmail App Password (see below)
EMAIL_FROM=your_email@gmail.com
EMAIL_RECIPIENTS=you@example.com,colleague@example.com

# SendGrid alternative (overrides SMTP when set)
# SENDGRID_API_KEY=SG....

# ---- Storage (defaults work out of the box) ----
DATABASE_URL=sqlite:///./data/radar.db
DATA_DIR=./data
PDF_DIR=./data/pdfs
SNAPSHOTS_DIR=./data/snapshots

# ---- Scheduling ----
RUN_SCHEDULE=30 6 * * *
RUN_TIMEZONE=America/Los_Angeles

# ---- Frontend deep-links in emails ----
FRONTEND_URL=http://localhost:3000
```

---

### 6. Install frontend dependencies

**All platforms:**
```bash
cd frontend
npm install
cd ..
```

---

### 7. Initialize the database and seed sources

**Recommended — API endpoint (works on all platforms, start backend first):**
```bash
curl -X POST http://localhost:8000/api/sources/seed-defaults
```

**macOS / Linux (alternative):**
```bash
python -c "from backend.database import init_db, SessionLocal; from backend.routers.sources import seed_default_sources; init_db(); seed_default_sources(SessionLocal()); print('Done — 16 sources seeded.')"
```

**Windows PowerShell / CMD (alternative):**
```powershell
python -c "from backend.database import init_db, SessionLocal; from backend.routers.sources import seed_default_sources; init_db(); seed_default_sources(SessionLocal()); print('Done — 16 sources seeded.')"
```

---

## Running the App

### macOS / Linux — Combined (recommended)

```bash
chmod +x start.sh
./start.sh
```

`start.sh` automatically:
- Installs WeasyPrint system libraries (pango, cairo, libffi, gdk-pixbuf) if missing
- Installs Python dependencies if needed
- Sets `DYLD_LIBRARY_PATH` for WeasyPrint on macOS
- Starts backend (`:8000`) and frontend (`:3000`) together

---

### Windows — WSL2 (recommended for Windows)

Install [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install), open a WSL terminal, then:
```bash
./start.sh
```

---

### Windows — Manual (two terminals, no WSL required)

**Terminal 1 — Backend (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 1 — Backend (CMD):**
```cmd
.venv\Scripts\activate.bat
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Frontend (PowerShell or CMD):**
```powershell
cd frontend
npm run dev
```

> **PDF on Windows:** Install [GTK3 Runtime for Windows](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer) to enable PDF generation. Without it, digests are saved as `.html` files.

---

### macOS / Linux — Manual (two terminals)

**Terminal 1 — Backend:**
```bash
source .venv/bin/activate
export DYLD_LIBRARY_PATH="/opt/homebrew/lib:${DYLD_LIBRARY_PATH:-}"  # macOS only
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
```

---

| Service   | URL                        |
|-----------|----------------------------|
| Dashboard | http://localhost:3000      |
| API       | http://localhost:8000      |
| API docs  | http://localhost:8000/docs |

---

## Running the Pipeline

### Via dashboard (works on all platforms, no Prefect server required)

Click **"Trigger Run"** on the dashboard at `http://localhost:3000`. The run is created immediately and agents execute as a FastAPI background task.

### Manually (CLI)

**macOS / Linux:**
```bash
source .venv/bin/activate
python -m backend.flows.daily_pipeline
```

**Windows PowerShell:**
```powershell
.venv\Scripts\Activate.ps1
python -m backend.flows.daily_pipeline
```

**Windows CMD:**
```cmd
.venv\Scripts\activate.bat
python -m backend.flows.daily_pipeline
```

### Scheduled via Prefect

**All platforms:**
```bash
prefect server start
```

Then in a separate terminal:
```bash
python -m backend.flows.daily_pipeline --deploy
```

The default schedule runs at **6:30 AM Pacific** every day (configured via `RUN_SCHEDULE` in `.env`).

---

## Dashboard Pages

| Page | URL | Description |
|------|-----|-------------|
| Overview | `/` | Recent findings, run stats, quick-trigger button |
| Sources | `/sources` | Add, edit, enable/disable, or delete crawl sources |
| Runs | `/runs` | Pipeline run history with per-agent status and logs |
| Findings | `/findings` | Filterable/searchable findings explorer |
| Analytics | `/analytics` | Entity heatmap + SOTA Watch leaderboard |
| Digests | `/digests` | Browse and download past PDF digests |

---

## API Endpoints

### Sources — `/api/sources`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/sources` | List all sources (filter: `?agent_type=`) |
| POST | `/api/sources` | Create a new source |
| GET | `/api/sources/{id}` | Get a single source |
| PUT | `/api/sources/{id}` | Update a source |
| DELETE | `/api/sources/{id}` | Delete a source |
| POST | `/api/sources/seed-defaults` | Seed DB from `default_sources.yaml` (idempotent) |

### Runs — `/api/runs`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/runs` | Paginated run list |
| GET | `/api/runs/{id}` | Single run with digest info |
| POST | `/api/runs/trigger` | Manually trigger a pipeline run |
| GET | `/api/runs/{id}/findings` | Findings for a specific run |

### Findings — `/api/findings`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/findings` | Paginated, filterable list (sort by impact_score) |
| GET | `/api/findings/stats/summary` | Aggregate counts by category, agent, publisher |
| GET | `/api/findings/stats/entities` | Entity × category cross-counts for heatmap |
| GET | `/api/findings/{id}` | Single finding with full evidence list |
| GET | `/api/findings/{id}/diff` | Unified text diff between two latest page snapshots |

### Digests — `/api/digests`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/digests` | Paginated digest archive |
| GET | `/api/digests/{id}` | Single digest metadata |
| GET | `/api/digests/{id}/download` | Stream PDF (or HTML fallback) to browser |

### Health — `/api/health`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Basic liveness check |
| GET | `/api/health/llm` | Test LLM provider connectivity |

---

## What It Tracks

The 16 pre-seeded sources cover:

| Agent | Sources |
|-------|---------|
| Competitors | OpenAI blog, Google DeepMind, Anthropic news, Meta AI, Mistral, Cohere |
| Model Providers | AWS Bedrock, Azure AI, Hugging Face blog |
| Research | arXiv cs.CL, cs.LG, cs.AI |
| Benchmarks | HuggingFace Open LLM Leaderboard, trending models |

Add or edit sources anytime via the dashboard at `http://localhost:3000/sources`.

---

## Impact Scoring

Every finding is assigned an `impact_score` (0.0–1.0) using this formula:

```
impact_score = 0.35 × relevance
             + 0.25 × novelty
             + 0.20 × credibility
             + 0.20 × actionability
```

Findings are ranked by impact score in the digest and the findings explorer.

---

## Change Detection

Pages are only summarized when their content changes:

1. Each page fetch computes a SHA-256 hash of the normalized text.
2. The hash is compared against the last stored snapshot for that URL.
3. If unchanged, the page is skipped (no LLM call, no Finding created).
4. If changed, a new snapshot is saved to disk and the diff is available at `/api/findings/{id}/diff`.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend API | FastAPI + SQLAlchemy (SQLite) |
| Orchestration | Prefect 3.x |
| LLM | Claude claude-sonnet-4-6 (Anthropic) / Groq / Azure OpenAI / OpenAI |
| Web crawling | httpx + trafilatura + Playwright (JS fallback) |
| Content extraction | trafilatura + BeautifulSoup + pdfminer |
| PDF generation | WeasyPrint + Jinja2 (HTML fallback if WeasyPrint unavailable) |
| Frontend | Next.js 15 (App Router) + Tailwind CSS + SWR |

---

## Environment Variables Reference

### LLM Provider

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `anthropic` | Provider: `anthropic` \| `azure_openai` \| `openai` |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Claude model ID |
| `OPENAI_API_KEY` | — | OpenAI / Groq / compatible key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Override for Groq, Ollama, Gemini, etc. |
| `OPENAI_MODEL` | `gpt-4o` | Model name for OpenAI-compatible provider |
| `AZURE_OPENAI_KEY` | — | Azure OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | — | Azure resource endpoint URL |
| `AZURE_OPENAI_DEPLOYMENT` | `gpt-4o` | Azure deployment name |
| `AZURE_OPENAI_API_VERSION` | `2024-08-01-preview` | Azure API version |

### Crawling

| Variable | Default | Description |
|----------|---------|-------------|
| `RESPECT_ROBOTS_TXT` | `false` | Check robots.txt before crawling each domain |

### Email

| Variable | Default | Description |
|----------|---------|-------------|
| `SMTP_HOST` | `smtp.gmail.com` | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP port (STARTTLS) |
| `SMTP_USER` | — | SMTP login email |
| `SMTP_PASS` | — | SMTP password or app password |
| `EMAIL_FROM` | — | Sender address |
| `EMAIL_RECIPIENTS` | — | Comma-separated recipient list |
| `SENDGRID_API_KEY` | — | When set, overrides SMTP with SendGrid |

### Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./data/radar.db` | SQLAlchemy database URL |
| `DATA_DIR` | `./data` | Root data directory |
| `PDF_DIR` | `./data/pdfs` | Directory for generated PDF digests |
| `SNAPSHOTS_DIR` | `./data/snapshots` | Directory for page snapshot text files |

### Scheduling & Infrastructure

| Variable | Default | Description |
|----------|---------|-------------|
| `RUN_SCHEDULE` | `30 6 * * *` | Cron expression for Prefect schedule |
| `RUN_TIMEZONE` | `America/Los_Angeles` | Timezone for the cron schedule |
| `PREFECT_API_URL` | — | Prefect server URL (leave empty for local executor) |
| `FRONTEND_URL` | `http://localhost:3000` | Used to build dashboard deep-links in emails |

---

## Gmail App Password Setup

If using Gmail for SMTP:

1. Enable 2-Factor Authentication on your Google account
2. Go to **Google Account → Security → App Passwords**
3. Generate a password for "Mail"
4. Use that 16-character password as `SMTP_PASS`

---

## Platform Command Reference

| Task | macOS / Linux | Windows PowerShell | Windows CMD |
|------|--------------|-------------------|-------------|
| Create venv | `python -m venv .venv` | `python -m venv .venv` | `python -m venv .venv` |
| Activate venv | `source .venv/bin/activate` | `.venv\Scripts\Activate.ps1` | `.venv\Scripts\activate.bat` |
| Install deps | `pip install -e ".[dev]"` | `pip install -e ".[dev]"` | `pip install -e ".[dev]"` |
| Copy .env | `cp .env.example .env` | `Copy-Item .env.example .env` | `copy .env.example .env` |
| Start backend | `python -m uvicorn backend.main:app --reload` | `python -m uvicorn backend.main:app --reload` | `python -m uvicorn backend.main:app --reload` |
| Start frontend | `npm run dev` | `npm run dev` | `npm run dev` |
| Run pipeline | `python -m backend.flows.daily_pipeline` | `python -m backend.flows.daily_pipeline` | `python -m backend.flows.daily_pipeline` |
| Seed sources | `curl -X POST http://localhost:8000/api/sources/seed-defaults` | `curl -X POST http://localhost:8000/api/sources/seed-defaults` | `curl -X POST http://localhost:8000/api/sources/seed-defaults` |

---

## Project Structure (full)

```
frontier_ai_radar/
├── backend/
│   ├── agents/
│   │   ├── base.py
│   │   ├── competitor_watcher.py
│   │   ├── model_provider_watcher.py
│   │   ├── research_scout.py
│   │   ├── hf_benchmark_tracker.py
│   │   └── digest_compiler.py
│   ├── services/
│   │   ├── summarizer.py
│   │   ├── fetcher.py
│   │   ├── extractor.py
│   │   ├── change_detector.py
│   │   ├── email_sender.py
│   │   └── pdf_renderer.py
│   ├── routers/
│   │   ├── sources.py
│   │   ├── runs.py
│   │   ├── findings.py
│   │   └── digests.py
│   ├── flows/
│   │   └── daily_pipeline.py
│   ├── config_store/
│   │   └── default_sources.yaml
│   ├── templates/
│   │   └── digest.html
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   └── main.py
├── frontend/
│   ├── app/
│   │   ├── page.tsx
│   │   ├── sources/page.tsx
│   │   ├── runs/page.tsx
│   │   ├── runs/[id]/page.tsx
│   │   ├── findings/page.tsx
│   │   ├── analytics/page.tsx
│   │   └── digests/page.tsx
│   ├── lib/
│   │   └── api.ts
│   └── package.json
├── start.sh
├── pyproject.toml
├── .env.example
├── README.md
├── TECHNICAL_DOCS.md          # Full technical documentation
└── architecture.html          # Visual architecture diagram (open in browser)
```
