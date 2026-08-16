import io
import zipfile

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


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_crud_api(client):
    resp = client.post("/api/models", json={"name": "隔离开关", "voltage_level": "220kV"})
    assert resp.status_code == 201
    model_id = resp.json()["id"]

    resp = client.get(f"/api/models/{model_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "隔离开关"

    resp = client.put(f"/api/models/{model_id}", json={"description": "修改"})
    assert resp.status_code == 200
    assert resp.json()["description"] == "修改"

    resp = client.get("/api/models", params={"voltage_level": "220kV"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = client.delete(f"/api/models/{model_id}")
    assert resp.status_code == 204


def test_import_export_api(client, tmp_path):
    pkg = tmp_path / "demo.gim"
    with zipfile.ZipFile(pkg, "w") as zf:
        zf.writestr("MOD/demo.mod", "parametric")
        zf.writestr("manifest.json", '{"name":"API演示"}')

    with open(pkg, "rb") as f:
        resp = client.post(
            "/api/models/import",
            files={"file": ("demo.gim", f, "application/zip")},
        )
    assert resp.status_code == 200
    model_id = resp.json()["created"][0]["id"]

    resp = client.get(f"/api/models/{model_id}/preview.svg")
    assert resp.status_code == 200
    assert "svg" in resp.text

    resp = client.get(f"/api/models/{model_id}/pointcloud", params={"count": 50})
    assert resp.status_code == 200
    assert resp.json()["count"] >= 0

    resp = client.get(f"/api/models/{model_id}/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
