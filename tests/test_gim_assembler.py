"""GIM 组装器测试：容器 → ModelAsset（属性+几何）。"""
from pathlib import Path

from egrid.gim import parse_gim
from egrid.render import render_model_svg

FIXTURE = Path(__file__).parent / "fixtures" / "tower_2f4sdj.gim"


def test_parse_gim_end_to_end():
    data = FIXTURE.read_bytes()
    assets = parse_gim(data)
    assert len(assets) == 1
    asset = assets[0]

    assert asset.name == "2F4-SDJ"
    assert asset.voltage_level == "220kV"
    assert asset.code == "2F4-SDJ"
    assert "道亨" in asset.description or "GIM" in asset.description

    # 属性来自 dev/*.fam
    keys = {a.key: a for a in asset.attributes}
    assert "TOWERTYPE" in keys
    assert keys["TOWERTYPE"].value == "终端"
    assert keys["CONDUCTOR"].value == "LGJ-630/45"

    # 几何：杆塔线架 1132 根杆件 → LINE 图元
    assert len(asset.geometry.primitives) == 1132
    line_prims = [p for p in asset.geometry.primitives if p.type.value == "line"]
    assert len(line_prims) == 1132


def test_parse_gim_svg_renderable():
    data = FIXTURE.read_bytes()
    asset = parse_gim(data)[0]
    svg = render_model_svg(asset)
    assert "<line" in svg
