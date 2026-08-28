# GraphOne AI Data Pipeline & Intelligence Platform

A production-ready, fault-tolerant, async AI data pipeline and portfolio dashboard tracking research papers, startups, products, jobs, and news across the artificial intelligence and venture ecosystem.

---

## 1. System Architecture

```text
                                  DATA SOURCES
                                       │
        ┌──────────────┬───────────────┼───────────────┬──────────────┐
        │              │               │               │              │
     Papers         Jobs           Startups        Products          News
     (arXiv)   (WWR, RemoteOK)   (YC, Techstars) (PH, TIAAFT)   (TechCrunch, VB)
        │              │               │               │              │
        └──────────────┴───────────────┼───────────────┴──────────────┘
                                       │
                                    Scrapers
                           (Async aiohttp / Playwright)
                                       │
                                       ▼
                               Pipeline / Ingestion
                        (LLM Extraction / Normalization)
                                       │
                                       ▼
                                Duplicate Check
                       (arXiv ID / URL Normalizer / Resolver)
                                       │
                                       ▼
                                 Data Storage
                                       │
                        ┌──────────────┴──────────────┐
                        │                             │
                     Database                   Google Sheets
            (SQLite / PostgreSQL)          (Multi-Tab Spreadsheets)
                        │                             │
                        └──────────────┬──────────────┘
                                       │
                                       ▼
                                  API Layer
                        (FastAPI / Next.js API Routes)
                                       │
                                       ▼
                                Next.js Dashboard
                         (Portfolio UI / Analytics / Live Data)
                                       │
                                       ▼
                               Vercel Deployment
```

---

## 2. Key Features

* **5 AI Verticals**:
  * **Papers**: arXiv Atom API with author extraction and automated GitHub star enrichment.
  * **Startups**: YCombinator & Techstars directory harvesters with entity normalization.
  * **Products**: Product Hunt API/crawlers and AI directory extraction with clean name filtering.
  * **Jobs**: Remote job scrapers for WeWorkRemotely, RemoteOK, AIJobsNet, and LinkedIn.
  * **News**: Full-text articles from TechCrunch, VentureBeat, and tech publications.
* **Fault-Tolerant Scraping**: Isolated per-source failure handling, SSL resilience, exponential backoff retries, and rate limiting.
* **Deduplication Engine**: Canonical arXiv IDs, normalized URL hashing, and fuzzy entity resolution (`rapidfuzz`).
* **Persistent Multi-Tier Database**: Zero-infra SQLite for local dev, automatic async PostgreSQL compatibility for production.
* **Google Sheets Integration**: Automatic spreadsheet creation, tab initialization, and incremental row updates.
* **Production REST API**: FastAPI backend delivering `/api/health`, `/api/stats`, and paginated vertical endpoints.
* **Modern Next.js Dashboard**: Dark/light mode UI with real-time KPI metrics, search filtering, and admin trigger modal.
* **Automated Scheduling**: GitHub Actions 6-hour cron workflow (`.github/workflows/scheduled_pipeline.yml`) and background worker script (`scripts/schedule_worker.py`).

---

## 3. Quickstart & Local Execution

### Step 3.1: Install Dependencies

```powershell
# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install Python dependencies
pip install -r requirements.txt
playwright install chromium
```

### Step 3.2: Configure Environment

Copy `.env.example` to `.env`:

```powershell
cp .env.example .env
```

### Step 3.3: Run Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

### Step 3.4: Execute Pipeline

```powershell
# Ingest single vertical (e.g. jobs)
python scripts/run_pipeline.py --vertical jobs --target 10

# Ingest and export to Google Sheets
python scripts/run_pipeline.py --vertical jobs --target 10 --export-sheets

# Ingest all verticals
python scripts/run_pipeline.py --vertical all --target 10
```

---

## 4. Production API Endpoints

FastAPI backend runs on `http://127.0.0.1:8000`:

```powershell
uvicorn api.index:app --reload --port 8000
```

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Health monitoring & database connectivity check |
| `GET` | `/api/stats` | Exact database record counts across all verticals |
| `GET` | `/api/jobs` | Paginated job records (`?limit=50&offset=0&search=ai`) |
| `GET` | `/api/papers` | Paginated research papers with arXiv IDs and GitHub stars |
| `GET` | `/api/startups` | Paginated startup records with canonical company names |
| `GET` | `/api/products` | Paginated AI products with clean name normalization |
| `GET` | `/api/news` | Paginated AI news articles |
| `POST` | `/api/pipeline/run` | Protected admin trigger (`Authorization: Bearer <secret>`) |

---

## 5. Next.js Dashboard

Run the Next.js frontend locally:

```powershell
cd web
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) to view the live dashboard.

To test production build:

```powershell
npm run build
```

---

## 6. Scheduled Pipeline Automation

### GitHub Actions (Recommended)

Workflow file: `.github/workflows/scheduled_pipeline.yml`

Runs automatically every 6 hours on GitHub Actions and supports manual dispatch runs with custom targets.

### Background Worker Script

To run on a VM / Docker container / background server:

```powershell
python scripts/schedule_worker.py --interval-hours 6 --vertical all --target 25 --export-sheets
```

---

## 7. Deployment Documentation

For complete production deployment instructions to Vercel and PostgreSQL, see [DEPLOYMENT.md](file:///c:/Users/TECH-GENIUSES/OneDrive/Desktop/project/graphone-pipeline-startup-fix/DEPLOYMENT.md).
