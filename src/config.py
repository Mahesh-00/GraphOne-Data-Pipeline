"""
Central configuration for the GraphOne / FrontierAtlas ingestion pipeline.

All tunables live here so scaling from a demo run (hundreds of records) to
production (500k+ records) is a config change, not a code change.
"""

import os
from dataclasses import dataclass
from typing import List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Concurrency / scale knobs
# ---------------------------------------------------------------------------

MAX_CONCURRENT_REQUESTS = int(
    os.getenv("MAX_CONCURRENT_REQUESTS", "25")
)

MAX_CONCURRENT_LLM_CALLS = int(
    os.getenv("MAX_CONCURRENT_LLM_CALLS", "10")
)

REQUEST_TIMEOUT_SECONDS = int(
    os.getenv("REQUEST_TIMEOUT_SECONDS", "30")
)


# ---------------------------------------------------------------------------
# Retry / backoff
# ---------------------------------------------------------------------------

MAX_RETRIES = int(
    os.getenv("MAX_RETRIES", "5")
)

BASE_BACKOFF_SECONDS = float(
    os.getenv("BASE_BACKOFF_SECONDS", "1.0")
)

MAX_BACKOFF_SECONDS = float(
    os.getenv("MAX_BACKOFF_SECONDS", "60.0")
)


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------

FRESHNESS_WINDOW_HOURS = int(
    os.getenv("FRESHNESS_WINDOW_HOURS", "24")
)


# ---------------------------------------------------------------------------
# LLM fallback chain
# Tried in order; first success wins
# ---------------------------------------------------------------------------

LLM_PROVIDER_CHAIN = [
    "groq_llama3",
    "gemini_flash",
    "deepseek",
]

LLM_API_KEYS = {
    "gemini_flash": os.getenv(
        "GEMINI_API_KEY",
        ""
    ),
    "groq_llama3": os.getenv(
        "GROQ_API_KEY",
        ""
    ),
    "deepseek": os.getenv(
        "DEEPSEEK_API_KEY",
        ""
    ),
}


LLM_ENDPOINTS = {
    "gemini_flash": (
        "https://generativelanguage.googleapis.com/"
        "v1beta/models/gemini-3.6-flash:generateContent"
    ),
    "groq_llama3": (
        "https://api.groq.com/openai/v1/chat/completions"
    ),
    "deepseek": (
        "https://api.deepseek.com/chat/completions"
    ),
}

# Max input tokens we'll allow per provider before
# chunking kicks in.
#
# Deliberately conservative to leave room for
# prompt + output tokens.

LLM_MAX_INPUT_TOKENS = {
    "gemini_flash": 900_000,
    "groq_llama3": 6_000,
    "deepseek": 60_000,
}


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

GITHUB_API_TOKEN = os.getenv(
    "GITHUB_API_TOKEN",
    ""
)

GITHUB_API_BASE = "https://api.github.com"


# ---------------------------------------------------------------------------
# Product Hunt
# ---------------------------------------------------------------------------

PRODUCTHUNT_API_TOKEN = os.getenv(
    "PRODUCTHUNT_API_TOKEN",
    ""
)

PRODUCTHUNT_API_BASE = "https://api.producthunt.com/v2/api"


# ---------------------------------------------------------------------------
# Source configuration
# ---------------------------------------------------------------------------

@dataclass
class SourceConfig:
    name: str
    base_url: str
    kind: str
    requires_js: bool = False
    pagination_param: str = "page"
    list_selector: str | None = None
    name_selector: str | None = None
    link_selector: str | None = None

    # Maximum requests per second for this source.
    #
    # Example:
    #   1.0  -> approximately 1 request/second
    #   0.25 -> approximately 1 request/4 seconds
    rate_limit_rps: float = 2.0


# ---------------------------------------------------------------------------
# Startup sources
# ---------------------------------------------------------------------------

STARTUP_SOURCES: List[SourceConfig] = [
    # YC is a valid public source when the page loads; the directory is JS-rendered
    # and the legacy selector assumption was the main cause of the startup failure.
    # Keep it as a primary source, but do not rely on it exclusively.
    SourceConfig(
        name="YCombinator",
        base_url="https://www.ycombinator.com/companies",
        kind="startup_directory",
        requires_js=True,
        rate_limit_rps=0.5,
    ),
    SourceConfig(
        name="TechstarsPortfolio",
        base_url="https://www.techstars.com/portfolio",
        kind="startup_directory",
        requires_js=False,
        rate_limit_rps=0.5,
    ),
]


# ---------------------------------------------------------------------------
# Product sources
# ---------------------------------------------------------------------------

PRODUCT_SOURCES: List[SourceConfig] = [
    SourceConfig(
        name="ProductHunt",
        base_url=(
            "https://www.producthunt.com/"
            "topics/artificial-intelligence"
        ),
        kind="product_directory",
        requires_js=True,
        list_selector="a[href*='/topics/'], a[href*='/posts/'], a[href*='/products/']",
        name_selector="a",
        link_selector="a",
    ),

    SourceConfig(
        name="ThereIsAnAIForThat",
        base_url="https://theresanaiforthat.com",
        kind="product_directory",
        requires_js=False,
        list_selector="a[href*='/ai/']",
        name_selector="a[href*='/ai/']",
        link_selector="a[href*='/ai/']",
    ),
]


# ---------------------------------------------------------------------------
# Paper sources
# ---------------------------------------------------------------------------

PAPER_SOURCES: List[SourceConfig] = [

    SourceConfig(
        name="Arxiv",
        base_url="https://export.arxiv.org/api/query",
        kind="paper_index",
        requires_js=False,

        # IMPORTANT:
        # arXiv is rate-limited more conservatively.
        #
        # 0.25 requests/second means approximately
        # one request every 4 seconds.
        rate_limit_rps=0.25,
    ),

    SourceConfig(
        name="PapersWithCode",
        base_url=(
            "https://paperswithcode.com/"
            "api/v1/papers/"
        ),
        kind="paper_index",
    ),
]


# ---------------------------------------------------------------------------
# News sources
# ---------------------------------------------------------------------------

NEWS_SOURCES: List[SourceConfig] = [

    SourceConfig(
        name="TechCrunchAI",
        base_url=(
            "https://techcrunch.com/"
            "category/artificial-intelligence/"
        ),
        kind="news",
        requires_js=False,
    ),

    SourceConfig(
        name="VentureBeatAI",
        base_url=(
            "https://venturebeat.com/"
            "category/ai/"
        ),
        kind="news",
        requires_js=False,
    ),

    SourceConfig(
        name="TheVergeAI",
        base_url=(
            "https://www.theverge.com/"
            "ai-artificial-intelligence"
        ),
        kind="news",
        requires_js=True,
    ),

    SourceConfig(
        name="MITTechReviewAI",
        base_url=(
            "https://www.technologyreview.com/"
            "topic/artificial-intelligence/"
        ),
        kind="news",
        requires_js=False,
    ),

    SourceConfig(
        name="ArsTechnicaAI",
        base_url="https://arstechnica.com/ai/",
        kind="news",
        requires_js=False,
    ),
]


# ---------------------------------------------------------------------------
# Job sources
# ---------------------------------------------------------------------------

JOB_SOURCES: List[SourceConfig] = [

    SourceConfig(
        name="WeWorkRemotelyAI",
        base_url=(
            "https://weworkremotely.com/"
            "categories/remote-programming-jobs"
        ),
        kind="jobs",
        requires_js=False,
    ),

    SourceConfig(
        name="RemoteOK-AI",
        base_url="https://remoteok.com/remote-ai-jobs",
        kind="jobs",
        requires_js=False,
    ),

    SourceConfig(
        name="LinkedInJobsAI",
        base_url=(
            "https://www.linkedin.com/jobs/"
            "search?keywords=artificial%20intelligence"
        ),
        kind="jobs",
        requires_js=True,
    ),

    SourceConfig(
        name="AIJobsNet",
        base_url="https://ai-jobs.net",
        kind="jobs",
        requires_js=False,
    ),

    SourceConfig(
        name="WellfoundAI",
        base_url=(
            "https://wellfound.com/"
            "role/r/artificial-intelligence"
        ),
        kind="jobs",
        requires_js=True,
    ),
]


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./graphone_raw.db"
)

GRAPHONE_DB_PATH = os.getenv(
    "GRAPHONE_DB_PATH",
    "./graphone_raw.db",
)

# Optional Google Sheets export support.
# This project is SQLite-first and does not require Google credentials for the
# normal data-collection pipeline.
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "",
)

GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    "",
)

GOOGLE_SHEETS_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_SHEETS_CREDENTIALS_PATH",
    "",
)

GOOGLE_SHEET_ID = os.getenv(
    "GOOGLE_SHEET_ID",
    "",
)

GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv(
    "GOOGLE_SHEETS_SPREADSHEET_ID",
    GOOGLE_SHEET_ID,
)

GOOGLE_WORKSHEET_NAME = os.getenv(
    "GOOGLE_WORKSHEET_NAME",
    "GraphOne Data",
)

GOOGLE_SHEETS_SPREADSHEET_NAME = os.getenv(
    "GOOGLE_SHEETS_SPREADSHEET_NAME",
    "GraphOne Pipeline Results",
)