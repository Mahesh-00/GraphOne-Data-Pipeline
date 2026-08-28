import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.exporters.google_sheets_exporter import resolve_service_account_path


def test_resolve_service_account_path_prefers_google_application_credentials(monkeypatch, tmp_path):
    credential_file = tmp_path / "service-account.json"
    credential_file.write_text('{"type": "service_account"}', encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(credential_file))
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)

    assert resolve_service_account_path() == str(credential_file)


def test_resolve_service_account_path_falls_back_to_repo_file(monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)

    repo_root = Path(__file__).resolve().parent.parent
    project_file = repo_root / "google-service-account.json"
    if project_file.exists():
        assert resolve_service_account_path() == str(project_file)
    else:
        assert resolve_service_account_path() is None
