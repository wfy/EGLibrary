"""工程级 GIM 聚合组装测试（聚合式导入，防模型爆炸）。"""
from pathlib import Path

import pytest

from egrid.gim import parse_header
from egrid.gim.assembler import assemble_gim
from egrid.gim.container import unpack_store
from egrid.gim.parsers.mod import sagcurve_wire

FIXTURE = Path(__file__).parent / "fixtures" / "line_juzhang.gim"


@pytest.fixture(scope="module")
def project_assets():
    data = FIXTURE.read_bytes()
    header = parse_header(data)
    files = unpack_store(data, header.store_offset)
    return assemble_gim(files, header)


def test_project_aggregation_count(project_assets):
    # 根1 + F1(2) + F2(12) + F3(100) + 塔组(258) ≈ 373，聚合后不得爆炸
    assert 300 <= len(project_assets) <= 450


def test_project_root(project_assets):
    root = next(a for a in project_assets if a.parent_id is None)
    assert root.name
    assert root.level == 1
    # 工程级属性（来自 F1 fam，实测 key 为 DESIGNVOLTAGE 等）
    assert any(a.key in ("VOLTAGE", "VOLTAGECLASS", "DESIGNVOLTAGE") for a in root.attributes)


def test_hierarchy_assets(project_assets):
    f1 = [a for a in project_assets if a.description and "F1SYSTEM" in a.description.upper()]
    f3 = [a for a in project_assets if a.description and "F3SYSTEM" in a.description.upper()]
    assert len(f1) == 2
    assert len(f3) == 100


def test_tower_assets_with_geometry(project_assets):
    towers = [a for a in project_assets if a.subcategory == "杆塔"]
    # 双线段（π 接）各 ~129 基
    assert 200 <= len(towers) <= 300
    with_geo = [a for a in towers if a.geometry.primitives]
    assert len(with_geo) > 100
    # 塔带经纬度溯源
    some = with_geo[0]
    assert some.origin.get("BLHA")


def test_wire_aggregated_into_f3(project_assets):
    f3 = [a for a in project_assets if a.description and "F3SYSTEM" in a.description.upper()]
    with_stats = [a for a in f3 if any("导线档数" in x.key for x in a.attributes)]
    assert len(with_stats) > 50
    # 全档展开：每个 F3 都有弧垂曲线，段数 ≈ 档数 × 24
    with_sag = [a for a in f3 if a.geometry.primitives]
    assert len(with_sag) == len(f3)
    sample = max(with_sag, key=lambda a: len(a.geometry.primitives))
    n_wires = next(int(x.value) for x in sample.attributes if x.key == "导线档数")
    assert len(sample.geometry.primitives) >= min(n_wires, 5) * 24 * 0.8


def test_sagcurve_wire():
    # 悬链线：档距 L=0.004°经度差（cos30° ≈ 385.6m）、两端同高、K=0.0004
    import math
    L = 0.004 * 111320.0 * math.cos(math.radians(30.0))
    f = 0.0004 * L * L / 4.0
    segs = sagcurve_wire(
        (30.0, 121.0, 100.0, 0.0),
        (30.0, 121.004, 100.0, 0.0),
        kvalue=0.0004,
        samples=24,
    )
    assert len(segs) == 24
    xs = [p["start"][0] for p in segs]
    zs = [p["start"][2] for p in segs]
    assert max(zs) <= 100.0
    assert abs(min(zs) - (100.0 - f)) < 0.1  # 最低点 = 弧垂
    assert min(xs) < max(xs)
