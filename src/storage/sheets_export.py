"""Optional Google Sheets exporter.

This project is SQLite-first. Google Sheets is not required for normal pipeline
execution. The exporter remains available as an optional plugin but is disabled by
default to keep the main pipeline stable and credential-free.
"""
import json
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

try:  # pragma: no cover - optional dependency
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:  # pragma: no cover
    gspread = None
    Credentials = None

from src.config import (
    GOOGLE_SERVICE_ACCOUNT_FILE,
    GOOGLE_SERVICE_ACCOUNT_JSON,
    GOOGLE_SHEET_ID,
    GOOGLE_SHEETS_CREDENTIALS_PATH,
    GOOGLE_WORKSHEET_NAME,
    GRAPHONE_DB_PATH,
)
from src.utils.logging_config import get_logger, log_ctx

logger = get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

TAB_SCHEMAS = {
    "Startups": ["entityName", "employeeCount", "source_name", "source_url", "collected_at"],
    "Products": ["productName", "startupName", "pricingModel", "source_name", "source_url", "collected_at"],
    "Research Papers": [
        "title", "authors", "paper_url", "github_url", "github_stars", "published_date", "collected_at",
    ],
    "Jobs": ["company", "title", "date", "is_remote", "role_family", "source_url", "collected_at"],
    "News": ["title", "published_date", "source_name", "source_url", "collected_at"],
    "Entity Mapping Log": ["raw_name", "canonical_name", "method", "confidence"],
}


def _as_sheet_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(_as_sheet_value(v)) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, default=str)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    return str(value)


class SheetsExporter:
    def __init__(
        self,
        credentials_path: str = GOOGLE_SHEETS_CREDENTIALS_PATH or GOOGLE_SERVICE_ACCOUNT_FILE,
        sheet_id: str = GOOGLE_SHEET_ID,
        worksheet_name: str = GOOGLE_WORKSHEET_NAME,
        db_path: str = GRAPHONE_DB_PATH,
    ):
        if gspread is None or Credentials is None:
            raise RuntimeError(
                "Google Sheets export is optional and disabled by default. Install gspread and google-auth to enable it. "
                "The main SQLite pipeline does not require Google credentials."
            )

        self.credentials_path = credentials_path or ""
        self.sheet_id = sheet_id or os.getenv("GOOGLE_SHEET_ID", "")
        self.worksheet_name = worksheet_name or os.getenv("GOOGLE_WORKSHEET_NAME", "GraphOne Data")
        self.db_path = db_path or GRAPHONE_DB_PATH
        self.client = None
        self.spreadsheet = None
        self.worksheet = None

        self._authenticate()
        self._select_or_create_spreadsheet()
        self._select_or_create_worksheet()

    def _get_credentials_source(self) -> str:
        env_json = (os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "") or "").strip()
        if env_json:
            return env_json

        env_file = (os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "") or self.credentials_path or "").strip()
        if env_file:
            return env_file

        legacy_path = (os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "") or "").strip()
        if legacy_path:
            return legacy_path

        raise RuntimeError(
            "Google Sheets export is optional and disabled by default. Configure GOOGLE_SERVICE_ACCOUNT_FILE or "
            "GOOGLE_SERVICE_ACCOUNT_JSON to enable it. The main SQLite pipeline does not require Google Sheets."
        )

    def _authenticate(self) -> None:
        source = self._get_credentials_source()
        if source.lstrip().startswith("{"):
            creds = Credentials.from_service_account_info(json.loads(source), scopes=SCOPES)
        else:
            path = Path(source).expanduser()
            if not path.exists():
                raise FileNotFoundError(
                    f"Google service account file not found: {path}. Configure GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_SERVICE_ACCOUNT_JSON."
                )
            creds = Credentials.from_service_account_file(str(path), scopes=SCOPES)

        self.client = gspread.authorize(creds)
        log_ctx(logger, 20, "google_sheets_auth_successful", credential_source="service_account")

    def _select_or_create_spreadsheet(self) -> None:
        if self.sheet_id:
            self.spreadsheet = self.client.open_by_key(self.sheet_id)
            log_ctx(logger, 20, "spreadsheet_selected", sheet_id=self.sheet_id)
            return

        self.spreadsheet = self.client.create(self.worksheet_name)
        self.sheet_id = self.spreadsheet.id
        log_ctx(logger, 20, "spreadsheet_created", sheet_id=self.sheet_id, worksheet_name=self.worksheet_name)

    def _select_or_create_worksheet(self) -> None:
        try:
            self.worksheet = self.spreadsheet.worksheet(self.worksheet_name)
            log_ctx(logger, 20, "worksheet_selected", worksheet_name=self.worksheet_name)
        except gspread.WorksheetNotFound:
            self.worksheet = self.spreadsheet.add_worksheet(title=self.worksheet_name, rows=1000, cols=50)
            log_ctx(logger, 20, "worksheet_created", worksheet_name=self.worksheet_name)

    def _get_or_create_tab(self, tab_name: str, headers: list[str]):
        try:
            ws = self.spreadsheet.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=max(len(headers), 10))
            ws.append_row(headers)
        return ws

    def _flatten_record(self, row: dict[str, Any]) -> dict[str, Any]:
        flattened: dict[str, Any] = {}
        for key, value in row.items():
            if key == "payload_json" and isinstance(value, str):
                try:
                    payload = json.loads(value)
                except (TypeError, json.JSONDecodeError):
                    payload = {}
                if isinstance(payload, dict):
                    for k, v in payload.items():
                        flattened[k] = v
                    continue
            flattened[key] = value
        return flattened

    def _load_sqlite_records(self) -> list[dict[str, Any]]:
        db_path = Path(self.db_path).expanduser()
        if not db_path.exists():
            raise FileNotFoundError(f"SQLite database not found at {db_path}. Run the pipeline first.")

        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, record_type, schema_version, source_name, source_url,
                       raw_document_id, payload_json, llm_provider_used, collected_at
                FROM structured_records
                ORDER BY id ASC
                """
            ).fetchall()

        records: list[dict[str, Any]] = []
        for row in rows:
            raw = dict(row)
            payload = {}
            if raw.get("payload_json"):
                try:
                    payload = json.loads(raw["payload_json"])
                except (TypeError, json.JSONDecodeError):
                    payload = {}

            merged = {
                "id": raw.get("id"),
                "record_type": raw.get("record_type"),
                "schema_version": raw.get("schema_version"),
                "source_name": raw.get("source_name"),
                "source_url": raw.get("source_url"),
                "raw_document_id": raw.get("raw_document_id"),
                "llm_provider_used": raw.get("llm_provider_used"),
                "collected_at": raw.get("collected_at"),
            }
            if isinstance(payload, dict):
                for key, value in payload.items():
                    merged[str(key)] = value
            records.append(merged)
        return records

    def export_structured_records(self, records: Iterable[dict[str, Any]] | None = None) -> int:
        if records is None:
            records = self._load_sqlite_records()

        records = list(records)
        header_keys: list[str] = []
        seen: set[str] = set()
        for record in records:
            flattened = self._flatten_record(record)
            for key in flattened:
                if key not in seen:
                    seen.add(key)
                    header_keys.append(str(key))

        base_headers = [
            "id",
            "record_type",
            "schema_version",
            "source_name",
            "source_url",
            "raw_document_id",
            "llm_provider_used",
            "collected_at",
        ]
        headers = [h for h in base_headers if h in seen] + [h for h in header_keys if h not in base_headers]
        if not headers:
            headers = ["id", "record_type", "source_name", "source_url", "collected_at"]

        self.worksheet.clear()
        self.worksheet.append_row(headers, value_input_option="RAW")

        rows: list[list[Any]] = []
        for record in records:
            flattened = self._flatten_record(record)
            row: list[Any] = []
            for header in headers:
                value = flattened.get(header, "")
                row.append(_as_sheet_value(value))
            rows.append(row)

        if rows:
            self.worksheet.append_rows(rows, value_input_option="RAW")

        row_count = len(rows)
        log_ctx(logger, 20, "number_of_records_exported", row_count=row_count)
        log_ctx(logger, 20, "export_completed_successfully", worksheet_name=self.worksheet_name, sheet_id=self.sheet_id)
        return row_count

    def write_tab(self, tab_name: str, records: list[dict[str, Any]]) -> None:
        headers = TAB_SCHEMAS[tab_name]
        ws = self._get_or_create_tab(tab_name, headers)
        rows: list[list[Any]] = []
        for rec in records:
            row: list[Any] = []
            for h in headers:
                val = rec.get(h, "")
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val)
                row.append(_as_sheet_value(val))
            rows.append(row)

        ws.clear()
        ws.append_row(headers, value_input_option="RAW")
        if rows:
            ws.append_rows(rows, value_input_option="RAW")
        log_ctx(logger, 20, "sheet_tab_written", tab=tab_name, row_count=len(rows))

    def export_all(self, data_by_tab: dict[str, list[dict[str, Any]]]) -> None:
        for tab_name in TAB_SCHEMAS:
            self.write_tab(tab_name, data_by_tab.get(tab_name, []))

    def export_sqlite_records(self) -> int:
        return self.export_structured_records(self._load_sqlite_records())
