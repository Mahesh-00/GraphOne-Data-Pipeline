# GraphOne Intelligence Platform — Deployment Guide

This guide details how to deploy the **GraphOne Platform** to **Vercel** and automate continuous data pipelines using **GitHub Actions**.

---

## 1. Quick Deploy to Vercel (Web Dashboard & FastAPI Backend)

The project includes [`vercel.json`](./vercel.json) pre-configured with:
- **FastAPI Backend Serverless Functions**: Handled via `@vercel/python` routing `/api/*` and `/docs`.
- **Next.js 14 Dashboard UI**: Handled via `@vercel/next` routing frontend pages.

### Step 1.1: Push Repository to GitHub
Ensure your repository is initialized and pushed to GitHub:
```powershell
git add .
git commit -m "feat: complete GraphOne data pipeline and Next.js dashboard"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo-name>.git
git push -u origin main
```

### Step 1.2: Import Project in Vercel
1. Log in to [Vercel](https://vercel.com) and click **Add New Project**.
2. Select your GitHub repository.
3. Keep the **Root Directory** as `./` (Vercel automatically detects [`vercel.json`](./vercel.json)).
4. Click **Deploy**.

Once deployed, your live production URLs will be active:
- **Web Dashboard**: `https://<your-project>.vercel.app`
- **FastAPI Health Check**: `https://<your-project>.vercel.app/api/health`
- **Interactive Swagger Docs**: `https://<your-project>.vercel.app/docs`

---

## 2. Automated Continuous Ingestion (GitHub Actions)

Because heavy web scraping and Playwright Chromium browsers require full system environments rather than ephemeral 10s serverless functions, continuous scraping is handled via **GitHub Actions Cron**.

### Workflow File: `.github/workflows/scheduled_pipeline.yml`

This workflow runs automatically **every 6 hours** and can also be triggered manually via GitHub UI:

1. In your GitHub repository, go to **Settings &rarr; Secrets and variables &rarr; Actions**.
2. Add your repository secrets:
   - `GROQ_API_KEY`: Your Groq API key.
   - `GEMINI_API_KEY`: Your Google Gemini API key.
   - `GITHUB_API_TOKEN`: Your GitHub personal access token (for star enrichment).
   - `GOOGLE_SERVICE_ACCOUNT_JSON`: Base64 or stringified JSON of your Google Service Account key.
   - `GOOGLE_SHEET_ID`: Your target Google Spreadsheet ID.

### Workflow Capabilities:
- Automatically installs Chromium and dependencies.
- Runs the ingestion pipeline across all 5 verticals (`Research Papers`, `Startups`, `Products`, `Jobs`, `News`).
- Performs deterministic entity resolution.
- Updates and synchronizes all **6 tabs** in your public Google Sheets spreadsheet.

---

## 3. Local Execution & Worker Mode

To run continuous ingestion locally or on a dedicated virtual machine / Docker container:

```powershell
# Run once with Google Sheets export:
python scripts/run_pipeline.py --vertical all --target 25 --export-sheets

# Run as a continuous background daemon (every 6 hours):
python scripts/schedule_worker.py --interval-hours 6 --vertical all --target 50 --export-sheets
```

