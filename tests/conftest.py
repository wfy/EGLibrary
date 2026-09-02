from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import egrid.api as api_module
from egrid.service import ModelService

@pytest.fixture()
def client(tmp_path, monkeypatch):
    svc = ModelService(
        db_path=str(tmp_path / "api.db"),
        storage_dir=str(tmp_path / "files"),
    )
    monkeypatch.setattr(api_module, "service", svc)
    return TestClient(api_module.app)

