"""3D 网格导出测试（OBJ / STL）。"""
from pathlib import Path
from egrid.service import ModelService
from egrid.storage import ModelRepository

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_export_mesh_obj_and_stl(tmp_path):
    repo = ModelRepository(str(tmp_path / "test.db"))
    service = ModelService(repo, storage_dir=str(tmp_path / "models"))

    fixture = FIXTURE_DIR / "tower_2f4sdj.gim"
    imported = service.import_gim_package(str(fixture))
    model_id = imported[0].id

    # 1. 测试 OBJ 导出
    obj_data, obj_name, obj_mime = service.export_mesh(model_id, fmt="obj")
    assert obj_mime.startswith("text/plain")
    assert obj_name.endswith(".obj")
    obj_str = obj_data.decode("utf-8")
    assert "# EGLibrary OBJ Export" in obj_str
    assert "v " in obj_str
    assert "l " in obj_str or "f " in obj_str

    # 2. 测试 STL 导出
    stl_data, stl_name, stl_mime = service.export_mesh(model_id, fmt="stl")
    assert stl_mime == "application/octet-stream"
    assert stl_name.endswith(".stl")
    assert len(stl_data) >= 84
    assert stl_data[:9] == b"EGLibrary"


def test_export_mesh_api(client):
    payload = (FIXTURE_DIR / "tower_2f4sdj.gim").read_bytes()
    imp_res = client.post("/api/models/import", files={"file": ("tower.gim", payload, "application/octet-stream")})
    assert imp_res.status_code == 200
    m_id = imp_res.json()["created"][0]["id"]

    res_obj = client.get(f"/api/models/{m_id}/export/mesh?format=obj")
    assert res_obj.status_code == 200
    assert "text/plain" in res_obj.headers["content-type"]
    assert "v " in res_obj.text

    res_stl = client.get(f"/api/models/{m_id}/export/mesh?format=stl")
    assert res_stl.status_code == 200
    assert res_stl.headers["content-type"] == "application/octet-stream"
    assert len(res_stl.content) >= 84
