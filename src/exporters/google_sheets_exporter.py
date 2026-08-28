import json
import os
from pathlib import Path
from typing import Any

from src.config import GOOGLE_SHEETS_SPREADSHEET_ID, GOOGLE_SHEETS_SPREADSHEET_NAME
from src.storage.db import Storage
from src.utils.logging_config import get_logger, log_ctx

logger = get_logger(__name__)

try:  # pragma: no cover - optional dependency
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:  # pragma: no cover
    gspread = None
    Credentials = None


WORKSHEET_TITLES = {
    "RESEARCH_PAPER": "Research Papers",
    "STARTUP": "Startups",
    "PRODUCT": "Products",
    "JOB": "Jobs",
    "NEWS": "News",
}


def resolve_service_account_path() -> str | None:
    candidates = [
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip(),
        os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip(),
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip(),
        os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "").strip(),
    ]

    for candidate in candidates:
        if not candidate:
            continue
        if candidate.lstrip().startswith("{"):
            return None
        path = Path(candidate).expanduser()
        if path.exists():
            return str(path)

    repo_root = Path(__file__).resolve().parents[2]
    for candidate in ("google-service-account.json", "service-account.json", "credentials/service-account.json"):
        file_path = repo_root / candidate
        if file_path.exists():
            return str(file_path)

    return None


class GoogleSheetsExporter:
    def __init__(self, spreadsheet_name: str | None = None, spreadsheet_id: str | None = None):
        self.spreadsheet_name = spreadsheet_name or GOOGLE_SHEETS_SPREADSHEET_NAME or "GraphOne Pipeline Results"
        self.spreadsheet_id = (spreadsheet_id or GOOGLE_SHEETS_SPREADSHEET_ID or "").strip()
        self.credentials_path = resolve_service_account_path()
        self.client = None
        self.spreadsheet = None

        if gspread is None or Credentials is None:
            raise RuntimeError("Google Sheets export requires the optional gspread/google-auth dependencies.")

        if not self.credentials_path:
            raise RuntimeError(
                "Google Sheets export requires GOOGLE_APPLICATION_CREDENTIALS to point to the service-account JSON file. "
                "If no credential file exists, place the JSON file in the project root or set the environment variable."
            )

        self.client_email = self._read_service_account_email()
        self._authenticate()
        self._ensure_spreadsheet_and_worksheet()

    def _read_service_account_email(self) -> str:
        try:
            with open(self.credentials_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return str(payload.get("client_email", "")).strip()
        except Exception:
            return ""

    def _authenticate(self) -> None:
        creds = Credentials.from_service_account_file(str(self.credentials_path), scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ])
        self.client = gspread.authorize(creds)
        log_ctx(logger, 20, "google_sheets_auth_successful", credential_source=self.credentials_path)

    def _ensure_spreadsheet_and_worksheet(self) -> None:
        if self.spreadsheet_id:
            self.spreadsheet = self.client.open_by_key(self.spreadsheet_id)
            log_ctx(logger, 20, "google_sheets_spreadsheet_ready", spreadsheet=self.spreadsheet_name, spreadsheet_id=self.spreadsheet_id)
            return

        try:
            self.spreadsheet = self.client.open(self.spreadsheet_name)
            log_ctx(logger, 20, "google_sheets_spreadsheet_ready", spreadsheet=self.spreadsheet_name)
        except gspread.SpreadsheetNotFound:
            self.spreadsheet = self.client.create(self.spreadsheet_name)
            log_ctx(logger, 20, "google_sheets_spreadsheet_created", spreadsheet=self.spreadsheet_name)
        except Exception as exc:
            if self.client_email:
                log_ctx(
                    logger,
                    30,
                    "google_sheets_manual_share_required",
                    spreadsheet=self.spreadsheet_name,
                    service_account=self.client_email,
                    message="Open the spreadsheet and share it with this service account, or create the spreadsheet with the service account owner.",
                    error=str(exc),
                )
            raise

    def _serialize_value(self, value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, (dict, list, tuple, set)):
            return json.dumps(value, default=str, sort_keys=True)
        if isinstance(value, (int, float, bool)):
            return value
        return str(value)

    def _normalize_row(self, record: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in record.items():
            if key.startswith("_"):
                continue
            if isinstance(value, dict):
                normalized[key] = json.dumps(value, default=str, sort_keys=True)
            else:
                normalized[key] = self._serialize_value(value)
        return normalized

    def _get_headers(self, rows: list[dict[str, Any]], record_type: str | None = None) -> list[str]:
        preferred_headers = {
            "STARTUP": ["entityName", "description", "employeeCount", "source_name", "source_url", "schemaVersion"],
            "PRODUCT": ["productName", "description", "pricingModel", "startupName", "source_name", "source_url", "schemaVersion"],
            "RESEARCH_PAPER": ["title", "abstract", "authors", "published_date", "arxiv_id", "primary_category", "categories", "github_repo_url", "github_stars", "source_url", "schemaVersion"],
            "JOB": ["title", "company", "location", "salary_range", "posted_at", "description", "source_name", "source_url", "schemaVersion"],
            "NEWS": ["title", "content_summary", "published_at", "source_name", "source_url", "schemaVersion"],
        }
        base_order = preferred_headers.get(record_type or "", [])
        headers = [h for h in base_order]
        seen = set(headers)
        for row in rows:
            for key in row.keys():
                if key not in seen and not key.startswith("_"):
                    seen.add(key)
                    headers.append(key)
        return headers

    def _sheet_name_for_record_type(self, record_type: str) -> str:
        return WORKSHEET_TITLES.get(record_type, "Jobs")

    async def export_records(self, record_type: str, worksheet_name: str | None = None, storage: Storage | None = None) -> int:
        import asyncio
        target_sheet = worksheet_name or self._sheet_name_for_record_type(record_type)
        log_ctx(logger, 20, "google_sheets_export_starting", worksheet=target_sheet)

        if storage is None:
            storage = Storage()

        try:
            records = await storage.fetch_all(record_type)
        except Exception as exc:
            log_ctx(logger, 40, "google_sheets_fetch_failed", worksheet=target_sheet, error=str(exc))
            raise

        if not records:
            log_ctx(logger, 20, "google_sheets_export_complete", worksheet=target_sheet, count=0)
            return 0

        normalized_rows = [self._normalize_row(r) for r in records]
        headers = self._get_headers(normalized_rows, record_type=record_type)
        if not headers:
            headers = ["source_url", "title", "company", "collected_at"]

        # Build full 2D matrix of complete database records
        all_data_rows = [
            [self._serialize_value(record.get(header, "")) for header in headers]
            for record in normalized_rows
        ]
        all_rows = [headers] + all_data_rows

        # Perform sheet update with retries against network/API blips
        last_exc = None
        for attempt in range(1, 4):
            try:
                try:
                    worksheet = self.spreadsheet.worksheet(target_sheet)
                except gspread.WorksheetNotFound:
                    worksheet = self.spreadsheet.add_worksheet(
                        title=target_sheet,
                        rows=max(1000, len(all_rows) + 50),
                        cols=max(20, len(headers) + 5),
                    )
                    log_ctx(logger, 20, "google_sheets_worksheet_created", worksheet=target_sheet)

                # Ensure sheet has enough rows and columns
                needed_rows = max(100, len(all_rows) + 20)
                needed_cols = max(20, len(headers) + 5)
                if worksheet.row_count < needed_rows or worksheet.col_count < needed_cols:
                    worksheet.resize(rows=max(worksheet.row_count, needed_rows), cols=max(worksheet.col_count, needed_cols))

                # Clear and overwrite worksheet with the full up-to-date database set
                worksheet.clear()
                worksheet.update("A1", all_rows, value_input_option="RAW")

                log_ctx(logger, 20, "google_sheets_export_successful", worksheet=target_sheet, count=len(normalized_rows))
                log_ctx(logger, 20, "google_sheets_export_complete", worksheet=target_sheet, count=len(normalized_rows))
                return len(normalized_rows)

            except Exception as exc:
                last_exc = exc
                log_ctx(
                    logger,
                    30,
                    "google_sheets_export_retry",
                    worksheet=target_sheet,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt < 3:
                    await asyncio.sleep(2 * attempt)

        log_ctx(logger, 40, "google_sheets_export_failed", worksheet=target_sheet, error=str(last_exc))
        raise last_exc

    async def export_entity_mapping_log(self, mapping_log: list[Any] | None = None) -> int:
        target_sheet = "Entity Mapping Log"
        log_ctx(logger, 20, "google_sheets_export_starting", worksheet=target_sheet)

        if not mapping_log:
            from src.resolution.resolver import EntityResolver
            resolver = EntityResolver()
            # Populate resolver with sample/known seed resolutions if log is empty
            for name in resolver.canonical_names[:25]:
                resolver.resolve(name, source_name="SeedDirectory")
            mapping_log = resolver.mapping_log

        headers = ["raw_name", "canonical_name", "method", "confidence", "source_name", "source_url"]

        try:
            worksheet = self.spreadsheet.worksheet(target_sheet)
        except gspread.WorksheetNotFound:
            worksheet = self.spreadsheet.add_worksheet(title=target_sheet, rows=max(1000, len(mapping_log) + 20), cols=max(10, len(headers)))
            log_ctx(logger, 20, "google_sheets_worksheet_ready", worksheet=target_sheet)
        else:
            log_ctx(logger, 20, "google_sheets_worksheet_ready", worksheet=target_sheet)

        rows: list[list[Any]] = []
        for item in mapping_log:
            if hasattr(item, "__dict__"):
                item_dict = item.__dict__
            elif isinstance(item, dict):
                item_dict = item
            else:
                continue
            rows.append([self._serialize_value(item_dict.get(h, "")) for h in headers])

        worksheet.clear()
        worksheet.append_row(headers, value_input_option="RAW")
        if rows:
            worksheet.append_rows(rows, value_input_option="RAW")

        log_ctx(logger, 20, "google_sheets_export_successful", worksheet=target_sheet, count=len(rows))
        log_ctx(logger, 20, "google_sheets_export_complete", worksheet=target_sheet, count=len(rows))
        return len(rows)
