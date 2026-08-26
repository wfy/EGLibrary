"""STL 挂件集成测试：合成最小 GIM 包（裸 7z + STL 引用链）。"""
import io
import struct
import zipfile

import pytest
from fastapi.testclient import TestClient

from egrid.gim.container import unpack_store
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
        "Cbm/a.cbm": "ENTITYNAME = Device\nOBJECTMODELPOINTER = b.dev\n".encode(),
        "Dev/b.dev": ("DEVICETYPE = FITTINGS\nSYMBOLNAME = 挂点金具\n"
                      "SOLIDMODELS.NUM = 1\nSOLIDMODEL0 = c.phm\n").encode(),
        "Phm/c.phm": "SOLIDMODELS.NUM = 1\nSOLIDMODEL0 = d.stl\n".encode(),
        "Stl/d.stl": stl,
    }
    pkg = tmp_path / "fittings.gim"
    # 裸 7z：用 py7zr 打包
    import py7zr
    with py7zr.SevenZipFile(pkg, "w") as z:
        for name, content in files.items():
            z.writestr(content, name)
    return pkg, files


def test_stl_stats_and_stream(gim_pkg):
    pkg, files = gim_pkg
    unpacked = unpack_store(pkg.read_bytes(), 0)
    assert "Stl/d.stl" in unpacked
    info = parse_stl(unpacked["Stl/d.stl"])
    assert info["triangles"] == 2


def test_import_stl_reference(gim_pkg, tmp_path, monkeypatch):
    pkg, _ = gim_pkg
    svc = ModelService(
        db_path=str(tmp_path / "s.db"),
        storage_dir=str(tmp_path / "files"),
    )
    monkeypatch.setattr(api_module, "service", svc)
    created = svc.import_gim_package(str(pkg))
    assert len(created) == 1
    asset = created[0]
    # STL 统计入属性
    assert any(a.key == "STL挂件" and "2" in a.value for a in asset.attributes)
    # STL 文件落盘挂根模型
    stl_files = [f for f in asset.files if f.kind.value == "stl"]
    assert len(stl_files) == 1

    client = TestClient(api_module.app)
    resp = client.get(f"/api/models/{asset.id}/stl/Stl/d.stl")
    assert resp.status_code == 200
    tris = resp.json()["triangles"]
    assert len(tris) == 2
    assert tris[0][0] == [0.0, 0.0, 0.0]
