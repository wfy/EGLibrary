"""多条件筛选（多选 OR / 跨维度 AND）与基本信息编辑测试。"""
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


def _seed(client):
    specs = [
        ("1号主变", "变电", "设备", "220kV"),
        ("2号主变", "变电", "设备", "110kV"),
        ("某耐张塔", "输电", "杆塔", "220kV"),
        ("某绝缘子串", "输电", "绝缘子串", "110kV"),
    ]
    ids = []
    for name, category, subcategory, voltage in specs:
        resp = client.post("/api/models", json={
            "name": name, "category": category, "subcategory": subcategory,
            "voltage_level": voltage,
        })
        assert resp.status_code == 201
        ids.append(resp.json()["id"])
    return ids


def test_multi_category_or_query(client):
    _seed(client)
    resp = client.get("/api/models", params=[
        ("category", "变电"), ("category", "输电"), ("limit", "100"),
    ])
    assert resp.status_code == 200
    names = {m["name"] for m in resp.json()}
    assert names == {"1号主变", "2号主变", "某耐张塔", "某绝缘子串"}


def test_multi_dimension_and_query(client):
    _seed(client)
    resp = client.get("/api/models", params=[
        ("category", "输电"), ("subcategory", "杆塔"), ("limit", "100"),
    ])
    assert resp.status_code == 200
    names = {m["name"] for m in resp.json()}
    assert names == {"某耐张塔"}


def test_single_category_string_backward_compat(client):
    _seed(client)
    resp = client.get("/api/models?category=变电&limit=100")
    assert resp.status_code == 200
    assert {m["name"] for m in resp.json()} == {"1号主变", "2号主变"}


def test_voltage_filter_normalized(client):
    _seed(client)
    # AC110kV 查询应命中归一化存储的 110kV
    resp = client.get("/api/models?voltage_level=AC110kV&limit=100")
    assert resp.status_code == 200
    assert {m["name"] for m in resp.json()} == {"2号主变", "某绝缘子串"}


def test_update_basic_info_persists(client):
    ids = _seed(client)
    resp = client.put(f"/api/models/{ids[0]}", json={
        "category": "输电", "subcategory": "杆塔", "voltage_level": "AC110kV",
    })
    assert resp.status_code == 200
    m = resp.json()
    assert m["category"] == "输电"
    assert m["subcategory"] == "杆塔"
    assert m["voltage_level"] == "110kV"
    got = client.get(f"/api/models/{ids[0]}").json()
    assert got["category"] == "输电"
    assert got["voltage_level"] == "110kV"


def test_filter_options_endpoint(client):
    _seed(client)
    resp = client.get("/api/filter-options")
    assert resp.status_code == 200
    data = resp.json()
    assert "变电" in data["categories"]
    assert "杆塔" in data["equipment_types"]
    assert data["voltage_levels"] == ["110kV", "220kV"]  # 数值排序