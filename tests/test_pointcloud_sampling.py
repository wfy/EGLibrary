"""点云四档采样测试：参数化图元 + STL 三角面 + 档位 API 规则。"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import egrid.api as api_module
import egrid.render as render
from egrid.gim.parsers.stl import stl_triangles
from egrid.models import Geometry, ModelAsset, Primitive, PrimitiveType
from egrid.service import ModelService

SAMPLE_STL = Path(__file__).parent / "fixtures" / "sample.stl"

BOX = Primitive(name="箱体", type=PrimitiveType.BOX, params={"width": 10, "depth": 10, "height": 10})
CYL = Primitive(name="柱体", type=PrimitiveType.CYLINDER, params={"radius": 5, "height": 10})


def _box_model():
    return ModelAsset(name="x", geometry=Geometry(primitives=[BOX, CYL]))


def _stl_triangles():
    return list(stl_triangles(SAMPLE_STL.read_bytes()))


def test_stl_only_sampling_exact_count_and_label():
    model = ModelAsset(name="绝缘子串", geometry=Geometry(),
                       extra={"stl_parts": [{"path": "STL/a.stl"}]})
    tri = _stl_triangles()
    out = render.sample_model_pointcloud(
        model, count=2000, seed=42,
        stl_sources=[{"path": "STL/a.stl", "transform": [], "triangles": tri}])
    assert out.count == 2000
    assert len(out.points) == len(out.labels) == 2000
    assert all(l == "a" for l in out.labels)


def test_stl_transform_applied():
    tri = [[[0, 0, 0], [10, 0, 0], [0, 10, 0]]]
    m = [1, 0, 0, 100, 0, 1, 0, 200, 0, 0, 1, 300, 0, 0, 0, 1]
    model = ModelAsset(name="x", geometry=Geometry())
    out = render.sample_model_pointcloud(
        model, count=50, seed=1,
        stl_sources=[{"path": "STL/t.stl", "transform": m, "triangles": tri}])
    assert out.count == 50
    assert all(p[0] >= 100 and p[1] >= 200 and p[2] >= 300 for p in out.points)


def test_primitive_exact_count():
    out = render.sample_model_pointcloud(_box_model(), count=2000, seed=7)
    assert out.count == 2000


def test_mixed_primitives_and_stl():
    model = ModelAsset(name="x", geometry=Geometry(primitives=[BOX]))
    out = render.sample_model_pointcloud(
        model, count=1000, seed=3,
        stl_sources=[{"path": "STL/b.stl", "transform": [], "triangles": _stl_triangles()}])
    assert out.count == 1000
    assert "b" in out.labels and "箱体" in out.labels


def test_stl_area_proportional_allocation():
    """STL 预算按三角面总面积分配：大面积部件点数显著多于小面积部件。"""
    big = [[[0, 0, 0], [100, 0, 0], [0, 100, 0]]]      # 面积 5000
    small = [[[0, 0, 0], [10, 0, 0], [0, 10, 0]]]      # 面积 50
    model = ModelAsset(name="x", geometry=Geometry())
    out = render.sample_model_pointcloud(
        model, count=1000, seed=1,
        stl_sources=[
            {"path": "STL/big.stl", "transform": [], "triangles": big},
            {"path": "STL/small.stl", "transform": [], "triangles": small},
        ])
    n_big = sum(1 for l in out.labels if l == "big")
    n_small = sum(1 for l in out.labels if l == "small")
    assert out.count == 1000
    assert n_big > n_small * 10
    assert n_small >= 1


def test_degenerate_stl_sources_do_not_break_allocation():
    """退化/空三角面源不得破坏总数精确性。"""
    flat = [[[0, 0, 0], [1, 1, 0], [2, 2, 0]]]  # 共线，面积≈0
    model = ModelAsset(name="x", geometry=Geometry())
    out = render.sample_model_pointcloud(
        model, count=300, seed=2,
        stl_sources=[
            {"path": "STL/g.stl", "transform": [], "triangles": flat},
            {"path": "STL/h.stl", "transform": [], "triangles": _stl_triangles()},
        ])
    assert out.count == 300
    assert "h" in out.labels


def test_stl_sampling_spreads_over_surface():
    """采样须覆盖整个 STL 表面：等面积长条模型不得集中到少数三角面（累计面积二分回归）。"""
    tris = []
    for i in range(100):
        tris.append([[0, 0, i], [10, 0, i], [0, 10, i]])  # 100 个同面积面沿 z 均匀铺开
    model = ModelAsset(name="x", geometry=Geometry())
    out = render.sample_model_pointcloud(
        model, count=1000, seed=7,
        stl_sources=[{"path": "STL/bar.stl", "transform": [], "triangles": tris}])
    zs = [p[2] for p in out.points]
    assert min(zs) <= 5 and max(zs) >= 95          # 覆盖两端
    assert len(set(round(z, 1) for z in zs)) >= 50  # 分布在多个层面


def test_no_geometry_empty():
    out = render.sample_model_pointcloud(ModelAsset(name="x", geometry=Geometry()), count=100)
    assert out.count == 0
    assert out.points == [] and out.labels == []


def test_seed_reproducible():
    # STL 采样使用局部 RNG：同 seed 一致，不同 seed 不同
    src = {"path": "STL/a.stl", "transform": [], "triangles": _stl_triangles()}
    model = ModelAsset(name="x", geometry=Geometry())
    a = render.sample_model_pointcloud(model, count=500, seed=99, stl_sources=[src])
    b = render.sample_model_pointcloud(model, count=500, seed=99, stl_sources=[src])
    assert a.points == b.points
    c = render.sample_model_pointcloud(model, count=500, seed=98, stl_sources=[src])
    assert a.points != c.points


# ---------- 服务层：沿父链读取根模型 STL ----------

def test_service_sample_pointcloud_stl_via_parent(tmp_path):
    svc = ModelService(db_path=str(tmp_path / "s.db"), storage_dir=str(tmp_path / "files"))
    root = svc.create_model(ModelAsset(name="工程根", category="输电"))
    stl_rel = "STL/parts/a.stl"
    from egrid.models import GIMFileKind, ModelFile
    root.files.append(ModelFile(path=stl_rel, kind=GIMFileKind.STL))
    svc.update_model(root.id, {"files": [f.model_dump(mode="json") for f in root.files]})
    p = svc._file_path(root.id, stl_rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(SAMPLE_STL.read_bytes())

    child = svc.create_model(ModelAsset(
        name="绝缘子串-1", category="输电", parent_id=root.id, subcategory="绝缘子串",
        geometry=Geometry(), extra={"stl_parts": [{"path": stl_rel, "transform": []}]},
    ))
    out = svc.sample_pointcloud(child.id, count=500, seed=5)
    assert out.count == 500
    assert out.labels[0] == "a"


# ---------- API 档位规则 ----------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    svc = ModelService(db_path=str(tmp_path / "api.db"), storage_dir=str(tmp_path / "files"))
    monkeypatch.setattr(api_module, "service", svc)
    return TestClient(api_module.app)


def _seed_model(client):
    resp = client.post("/api/models", json={
        "name": "采样模型",
        "geometry": {
            "primitives": [
                {"name": "箱体", "type": "box", "params": {"width": 10, "depth": 10, "height": 10}},
                {"name": "柱体", "type": "cylinder", "params": {"radius": 5, "height": 10}},
            ],
        },
    })
    assert resp.status_code == 201
    return resp.json()["id"]


def test_api_default_medium(client):
    mid = _seed_model(client)
    resp = client.get(f"/api/models/{mid}/pointcloud")
    assert resp.status_code == 200
    assert resp.json()["count"] == 2000


def test_api_quality_levels(client):
    mid = _seed_model(client)
    for quality, expected in (("low", 500), ("medium", 2000), ("high", 5000)):
        resp = client.get(f"/api/models/{mid}/pointcloud?quality={quality}")
        assert resp.status_code == 200
        assert resp.json()["count"] == expected


def test_api_legacy_count_only(client):
    mid = _seed_model(client)
    resp = client.get(f"/api/models/{mid}/pointcloud?count=333")
    assert resp.status_code == 200
    assert resp.json()["count"] == 333


def test_api_custom_requires_count(client):
    mid = _seed_model(client)
    resp = client.get(f"/api/models/{mid}/pointcloud?quality=custom")
    assert resp.status_code == 422


def test_api_quality_conflicts_with_count(client):
    mid = _seed_model(client)
    resp = client.get(f"/api/models/{mid}/pointcloud?quality=high&count=100")
    assert resp.status_code == 422


def test_api_invalid_quality(client):
    mid = _seed_model(client)
    resp = client.get(f"/api/models/{mid}/pointcloud?quality=ultra")
    assert resp.status_code == 422