"""STL 部件集成测试：合成最小 GIM（裸 7z + STL 引用链，多实例矩阵走 extra.stl_parts）。"""
import struct

import py7zr
import pytest
from fastapi.testclient import TestClient

from egrid.gim.parsers.stl import parse_stl
import egrid.api as api_module
from egrid.service import ModelService


def _make_stl(tris):
    out = b"\x00" * 80 + struct.pack("<I", len(tris))
    for t in tris:
        out += struct.pack("<12fH", 0, 0, 1, *t[0], *t[1], *t[2], 0)
    return out


@pytest.fixture()
def gim_pkg(tmp_path):
    stl = _make_stl([[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                     [[1, 0, 0], [1, 1, 0], [0, 1, 0]]])
    files = {
        "Cbm/a.cbm": ("ENTITYNAME=Device\nOBJECTMODELPOINTER=b.dev\n"
                      "TRANSFORMMATRIX=1,0,0,0,0,1,0,0,0,0,1,0,100,200,300,1\n").encode(),
        "Dev/b.dev": ("DEVICETYPE=FITTINGS\nSYMBOLNAME=挂点金具\n"
                      "SOLIDMODELS.NUM=1\nSOLIDMODEL0=c.phm\n"
                      "TRANSFORMMATRIX0=1,0,0,0,0,1,0,0,0,0,1,0,10,20,30,1\n").encode(),
        "Phm/c.phm": "SOLIDMODELS.NUM=1\nSOLIDMODEL0=d.stl\n".encode(),
        "Stl/d.stl": stl,
    }
    pkg = tmp_path / "fittings.gim"
    with py7zr.SevenZipFile(pkg, "w") as z:
        for name, content in files.items():
            z.writestr(content, name)
    return pkg, files


def test_stl_stats_and_stream(gim_pkg):
    pkg, _ = gim_pkg
    from egrid.gim.container import unpack_store
    unpacked = unpack_store(pkg.read_bytes(), 0)
    info = parse_stl(unpacked["Stl/d.stl"])
    assert info["triangles"] == 2


def test_import_stl_reference(gim_pkg, tmp_path, monkeypatch):
    """STL 部件：组合矩阵入 extra.stl_parts（含单位归一 mm），文件唯一落盘，端点原始顶点。"""
    pkg, _ = gim_pkg
    svc = ModelService(db_path=str(tmp_path / "s.db"), storage_dir=str(tmp_path / "files"))
    monkeypatch.setattr(api_module, "service", svc)
    created = svc.import_gim_package(str(pkg))
    asset = created[0]

    stl_files = [f for f in asset.files if f.kind.value == "stl"]
    assert len(stl_files) == 1

    client = TestClient(api_module.app)
    resp = client.get(f"/api/models/{asset.id}/stl/Stl/d.stl")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    # 端点返回原始顶点（实例变换由前端应用）
    assert data["triangles"][0][0] == [0.0, 0.0, 0.0]


def test_stl_transform_chain(gim_pkg, tmp_path, monkeypatch):
    """组合矩阵 M_cbm·M_dev：大平移链（判 mm）不缩放。"""
    pkg, _ = gim_pkg
    svc = ModelService(db_path=str(tmp_path / "t.db"), storage_dir=str(tmp_path / "files"))
    created = svc.import_gim_package(str(pkg))
    parts = created[0].extra["stl_parts"]
    assert len(parts) == 1
    m = parts[0]["transform"]
    # 组合平移 (110,220,330) → 转置到 3/7/11 → ×1000 归一 mm
    assert m[3] == pytest.approx(110000.0)
    assert m[7] == pytest.approx(220000.0)
    assert m[11] == pytest.approx(330000.0)


def test_stl_transform_unit_heuristic(gim_pkg, tmp_path, monkeypatch):
    """矩阵平移为米、STL 为 mm：|平移|<10 时自动 ×1000 统一单位。"""
    stl = _make_stl([[[0, 0, 0], [1, 0, 0], [0, 1, 0]]])
    files = {
        "Cbm/a.cbm": "ENTITYNAME=Device\nOBJECTMODELPOINTER=top.dev\n".encode(),
        "Dev/top.dev": ("DEVICETYPE=INSULATOR\nSYMBOLNAME=串\n"
                        "SOLIDMODELS.NUM=1\nSOLIDMODEL0=p.phm\n"
                        "TRANSFORMMATRIX0=1,0,0,0,0,1,0,0,0,0,1,0,0,0,1.5,1\n").encode(),
        "Phm/p.phm": "SOLIDMODELS.NUM=1\nSOLIDMODEL0=s.stl\n".encode(),
        "Stl/s.stl": stl,
    }
    pkg = tmp_path / "unit.gim"
    with py7zr.SevenZipFile(pkg, "w") as z:
        for name, content in files.items():
            z.writestr(content, name)

    svc = ModelService(db_path=str(tmp_path / "u.db"), storage_dir=str(tmp_path / "files"))
    created = svc.import_gim_package(str(pkg))
    part = created[0].extra["stl_parts"][0]
    assert part["transform"][11] == pytest.approx(1500.0)


def test_nested_dev_chain(gim_pkg, tmp_path, monkeypatch):
    """dev→dev 嵌套引用（绝缘子串结构）：子 dev 各带叠放矩阵，STL 应递归收集。"""
    stl = _make_stl([[[0, 0, 0], [1, 0, 0], [0, 1, 0]]])
    files = {
        "Cbm/a.cbm": "ENTITYNAME=Device\nOBJECTMODELPOINTER=top.dev\n".encode(),
        "Dev/top.dev": ("DEVICETYPE=STRING\nSYMBOLNAME=绝缘子串\n"
                        "SOLIDMODELS.NUM=1\nSOLIDMODEL0=sub.dev\n"
                        "TRANSFORMMATRIX0=1,0,0,0,0,1,0,0,0,0,1,0,0,0,10,1\n").encode(),
        "Dev/sub.dev": ("DEVICETYPE=INSULATOR\nSYMBOLNAME=子件\n"
                        "SOLIDMODELS.NUM=1\nSOLIDMODEL0=p.phm\n"
                        "TRANSFORMMATRIX0=1,0,0,0,0,1,0,0,0,0,1,0,5,0,0,1\n").encode(),
        "Phm/p.phm": "SOLIDMODELS.NUM=1\nSOLIDMODEL0=s.stl\n".encode(),
        "Stl/s.stl": stl,
    }
    pkg = tmp_path / "nested.gim"
    with py7zr.SevenZipFile(pkg, "w") as z:
        for name, content in files.items():
            z.writestr(content, name)

    svc = ModelService(db_path=str(tmp_path / "n.db"), storage_dir=str(tmp_path / "files"))
    created = svc.import_gim_package(str(pkg))
    parts = created[0].extra["stl_parts"]
    assert len(parts) == 1
    m = parts[0]["transform"]
    # 组合平移 x=5, z=10 → 转置 → ×1000
    assert m[3] == pytest.approx(5000.0)
    assert m[11] == pytest.approx(10000.0)
