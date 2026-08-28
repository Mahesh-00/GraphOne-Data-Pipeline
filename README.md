# GraphOne AI Intelligence Platform & Data Pipeline

A production-ready, fault-tolerant, async AI data pipeline and portfolio dashboard tracking **Research Papers**, **Startups**, **Products**, **AI Jobs**, and **News Signals** across the global venture and artificial intelligence ecosystem.

---

## 📋 System Architecture

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

## 🚀 Quickstart: Setup & Installation

### Prerequisites
* **Python 3.10+**
* **Node.js 18+** & **npm**
* **Git**

---

### Step 1: Clone the Repository & Setup Virtual Environment

Open PowerShell or your terminal in the project root:

```powershell
# 1. Navigate to the project root directory
cd graphone-pipeline-startup-fix

# 2. Create Python virtual environment
python -m venv .venv

# 3. Activate the virtual environment
# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# On macOS/Linux:
# source .venv/bin/activate

# 4. Install Python dependencies
pip install -r requirements.txt
playwright install chromium

# 5. Install Frontend dependencies (in the web folder)
cd web
npm install
cd ..
```

---

### Step 2: Configure Environment Variables

Copy `.env.example` to create your local `.env` file:

```powershell
cp .env.example .env
```

Add your API keys to `.env` (Groq, Gemini, DeepSeek, GitHub, Google Sheets):
```env
GROQ_API_KEY=your_groq_api_key
GEMINI_API_KEY=your_gemini_api_key
DEEPSEEK_API_KEY=your_deepseek_api_key
GITHUB_API_TOKEN=your_github_token
DATABASE_URL=sqlite+aiosqlite:///./graphone_raw.db
```

---

### Step 3: Run Automated Tests

Verify that all 41 test suites pass:

```powershell
# Run from project root with .venv activated:
python -m pytest tests/ -v
```

---

## 🖥️ How to Start the Servers

You can run both the **FastAPI Backend** and the **Next.js Frontend Dashboard** side-by-side:

### Option A: Start the Next.js Frontend Dashboard (UI)

Open your terminal:

```powershell
# 1. Navigate to the web folder
cd web

# 2. Start Next.js development server
npm run dev
```

* **Live Dashboard UI**: [http://localhost:3000](http://localhost:3000)
* **Built-in API Docs Page**: [http://localhost:3000/docs](http://localhost:3000/docs)
* **Live Health Check**: [http://localhost:3000/api/health](http://localhost:3000/api/health)

---

### Option B: Start the FastAPI Backend Server (API)

Open a **separate terminal window**:

```powershell
# 1. From the project root with .venv activated:
cd graphone-pipeline-startup-fix
.\.venv\Scripts\Activate.ps1

# 2. Start the FastAPI server
uvicorn api.index:app --reload --port 8000
```

* **Backend Status**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
* **Swagger Interactive Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
* **Health Endpoint**: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

---

## ⚡ How to Run the Ingestion Pipeline

To scrape new data from AI sources and synchronize the Google Sheets tabs:

```powershell
# Run from project root with .venv activated:

# 1. Run ALL 5 Verticals + Export to Google Sheets:
python scripts/run_pipeline.py --vertical all --target 10 --export-sheets

# 2. Run a specific vertical:
python scripts/run_pipeline.py --vertical papers --target 10 --export-sheets
python scripts/run_pipeline.py --vertical startups --target 10 --export-sheets
python scripts/run_pipeline.py --vertical products --target 10 --export-sheets
python scripts/run_pipeline.py --vertical jobs --target 10 --export-sheets
python scripts/run_pipeline.py --vertical news --target 10 --export-sheets
```

---

## 📊 Database Inspection & Verification

Check the exact record counts in your local SQLite database:

```powershell
python check_db.py
```

---

## ☁️ Deployment Guide (Vercel & GitHub Actions)

### 1. Deploy to Vercel (Web Dashboard & Serverless API)
1. Push your repository to GitHub (`git add .`, `git commit -m "Deploy"`, `git push origin main`).
2. Log into [Vercel](https://vercel.com) &rarr; **Add New Project** &rarr; Select your repo.
3. Keep **Root Directory** as `./` (Vercel automatically uses [`vercel.json`](./vercel.json)).
4. Click **Deploy**.

### 2. Scheduled Continuous Crawling (GitHub Actions)
* The repository includes `.github/workflows/scheduled_pipeline.yml`.
* Runs automatically **every 6 hours** on GitHub Actions with full Playwright Chromium support, syncing fresh data directly to Google Sheets.

---

## 📁 Repository Structure

```text
graphone-pipeline-startup-fix/
│
├── src/                          # Core Python Engine
│   ├── config.py                 # Central configurations & sources
│   ├── scrapers/                 # Async crawlers (arXiv, YC, PH, WWR, TechCrunch)
│   ├── llm/                      # Multi-tier LLM orchestrator & chunker
│   ├── resolution/               # Deterministic entity resolver (4-stage matching)
│   ├── storage/                  # SQLite/PostgreSQL storage & sheets exporter
│   ├── pipeline/                 # Ingestion & 24h freshness filter
│   └── utils/                    # Logging & async pool
│
├── api/                          # FastAPI Backend
│   ├── index.py                  # Serverless API endpoints
│   └── requirements.txt          # API dependencies
│
├── web/                          # Next.js 14 Frontend Dashboard
│   ├── app/                      # Next.js App Router (page.tsx, layout.tsx, docs/)
│   ├── package.json              # Node dependencies
│   └── next.config.js            # Next.js configuration & API proxying
│
├── scripts/                      # Execution Runners
│   ├── run_pipeline.py           # CLI ingestion runner
│   └── schedule_worker.py        # Background interval worker
│
├── tests/                        # Pytest Test Suite (41 tests)
├── canonical_seed.json           # 50+ Canonical AI Entity Seeds
├── vercel.json                   # Vercel multi-route deployment config
├── ARCHITECTURE.md               # Technical architecture document
├── DEPLOYMENT.md                 # Deployment & scaling guide
├── requirements.txt              # Python requirements
└── README.md                     # Project documentation
```

---

## 🛠️ Common Troubleshooting

| Issue | Cause | Fix |
| :--- | :--- | :--- |
| `ModuleNotFoundError: No module named 'api'` | Running `uvicorn` from `.venv\Scripts` instead of root. | Run `cd ..\..` to return to the project root before running `uvicorn`. |
| `can't open file 'scripts/run_pipeline.py'` | Terminal is inside `web\` subfolder. | Run `cd ..` to return to project root. |
| `Playwright browser not found` | Chromium binary not installed. | Run `playwright install chromium`. |
