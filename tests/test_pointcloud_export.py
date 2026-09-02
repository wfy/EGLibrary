"""AI 训练点云导出测试（LAS 1.2 / TXT / 噪声增强 / 语义分类）。"""
import struct
from pathlib import Path
from egrid.service import ModelService
from egrid.storage import ModelRepository
from egrid.exporters import classify_label, augment_pointcloud

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_classify_semantic_label():
    cid1, cname1, rgb1 = classify_label("FXBW-110")
    assert cid1 == 2  # insulator
    assert "绝缘子" in cname1

    cid2, cname2, _ = classify_label("TowerLeg")
    assert cid2 == 1  # tower

    cid3, cname3, _ = classify_label("Wire_Conductor")
    assert cid3 == 4  # conductor


def test_augment_pointcloud():
    pts = [[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]]
    # 无扰动
    out0 = augment_pointcloud(pts, noise=0.0, augment=False, seed=42)
    assert out0 == pts

    # 高斯噪声
    out_noise = augment_pointcloud(pts, noise=0.05, augment=False, seed=42)
    assert len(out_noise) == len(pts)
    assert out_noise[0] != pts[0]

    # 旋转增强
    out_rot = augment_pointcloud(pts, noise=0.0, augment=True, seed=42)
    assert len(out_rot) == len(pts)
    assert out_rot[1] != pts[1]


def test_export_pointcloud_dataset(tmp_path):
    repo = ModelRepository(str(tmp_path / "test.db"))
    service = ModelService(repo, storage_dir=str(tmp_path / "models"))
    fixture = FIXTURE_DIR / "tower_2f4sdj.gim"
    imported = service.import_gim_package(str(fixture))
    model_id = imported[0].id

    # 1. 导出 TXT
    txt_data, txt_name, txt_mime = service.export_pointcloud_dataset(
        model_id, fmt="txt", count=500, noise=0.01, augment=True, seed=123
    )
    assert txt_name.endswith(".txt")
    txt_str = txt_data.decode("utf-8")
    assert txt_str.startswith("# X Y Z R G B Classification Label")
    lines = [l for l in txt_str.splitlines() if l and not l.startswith("#")]
    assert len(lines) == 500

    # 2. 导出 LAS 1.2
    las_data, las_name, las_mime = service.export_pointcloud_dataset(
        model_id, fmt="las", count=500, noise=0.0, augment=False, seed=123
    )
    assert las_name.endswith(".las")
    assert las_data[:4] == b"LASF"
    assert len(las_data) == 227 + 500 * 26  # Header 227 + 500 * 26 bytes
    count_in_header = struct.unpack_from("<I", las_data, 107)[0]
    assert count_in_header == 500


def test_export_pointcloud_api(client):
    payload = (FIXTURE_DIR / "tower_2f4sdj.gim").read_bytes()
    imp_res = client.post("/api/models/import", files={"file": ("tower.gim", payload, "application/octet-stream")})
    assert imp_res.status_code == 200
    m_id = imp_res.json()["created"][0]["id"]

    res_las = client.get(f"/api/models/{m_id}/export/pointcloud?format=las&quality=low")
    assert res_las.status_code == 200
    assert res_las.headers["content-type"] == "application/octet-stream"
    assert res_las.content[:4] == b"LASF"

    res_txt = client.get(f"/api/models/{m_id}/export/pointcloud?format=txt&quality=low&noise=0.02&augment=true")
    assert res_txt.status_code == 200
    assert "text/plain" in res_txt.headers["content-type"]
    assert "# X Y Z" in res_txt.text
