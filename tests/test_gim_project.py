"""工程级 GIM（裸 7z 容器 + project.cbm 层级树）解析测试。

样例特征（句章-淞浦双回π入观中变 220kV 线路，4.4MB）：
- 无 GIMPKGT 头，直接 7z 流（厂商差异）
- 目录名 Cbm/Dev/Phm/Mod（大小写与单设备样例不同）
- project.cbm → F1System(2) → F2System(12) → F3System(100) → F4System(4136)
"""
from pathlib import Path

from egrid.gim import is_gim, parse_header
from egrid.gim.container import unpack_store

FIXTURE = Path(__file__).parent / "fixtures" / "line_juzhang.gim"


def _data():
    return FIXTURE.read_bytes()


def test_bare_7z_is_gim():
    assert is_gim(_data())


def test_parse_header_bare_7z():
    h = parse_header(_data())
    assert h.store_offset == 0
    assert h.kind in ("line", "unknown")


def test_unpack_store_project():
    data = _data()
    h = parse_header(data)
    files = unpack_store(data, h.store_offset)
    names = list(files)
    assert any(n.lower().endswith("project.cbm") for n in names)
    # 大小写不敏感目录：Cbm/Dev/Phm/Mod 均存在
    lowers = {n.lower() for n in names}
    assert any(n.startswith("cbm/") for n in lowers)
    assert any(n.startswith("mod/") for n in lowers)
    assert sum(1 for n in lowers if n.endswith(".cbm")) > 1000


def test_import_project_end_to_end(tmp_path):
    """工程级 GIM 经 service 导入：聚合落库 + 原包仅根存档。"""
    from egrid.service import ModelService

    svc = ModelService(
        db_path=str(tmp_path / "e2e.db"),
        storage_dir=str(tmp_path / "files"),
    )
    created = svc.import_gim_package(str(FIXTURE), voltage_level="220kV")
    # 开启绝缘子串逐串建模后：基础 373 + 串 4944 ≈ 5317，不得万级爆炸
    assert 300 <= len(created) <= 6000

    root = next(a for a in created if a.parent_id is None)
    assert root.source == "gim"
    assert root.files[0].size == FIXTURE.stat().st_size   # 原包存档在首位
    stl_files = [f for f in root.files if f.kind.value == "stl"]
    assert len(stl_files) == 46                            # STL 挂件全部落盘
    children = [a for a in created if a.parent_id]
    assert all(not a.files for a in children)  # 子模型不重复落盘
    assert all(a.source == "gim" for a in created)
    towers = [a for a in created if a.subcategory == "杆塔"]
    assert towers and towers[0].origin.get("BLHA")

    # 可检索：全量统计
    stats = svc.stats()
    assert stats["total"] == len(created)
