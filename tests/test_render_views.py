"""多视角投影测试（等轴测/正视/侧视/俯视）。"""
from egrid.models import Geometry, ModelAsset, Primitive, PrimitiveType
from egrid.render import _project_view, render_model_svg


def test_front_view_z_up():
    """正视：x 向右，z 向上（SVG y 向下）。"""
    px, py = _project_view("front", 100, 50, 200)
    assert px == 100
    assert py == -200


def test_side_view():
    """侧视：y 向右，z 向上。"""
    px, py = _project_view("side", 100, 50, 200)
    assert px == 50
    assert py == -200


def test_top_view():
    """俯视：x 向右，y 向下（平面图）。"""
    px, py = _project_view("top", 100, 50, 999)
    assert px == 100
    assert py == 50


def test_iso_matches_project():
    """iso 与默认 _project 一致（z-up 等轴测）。"""
    from egrid.render import _project
    assert _project_view("iso", 1, 2, 3) == _project(1, 2, 3)


def test_render_svg_with_view_param():
    prim = Primitive(name="线", type=PrimitiveType.LINE,
                     params={"start": [0, 0, 0], "end": [100, 0, 500]})
    asset = ModelAsset(name="V", geometry=Geometry(primitives=[prim]))
    for view in ("iso", "front", "side", "top"):
        svg = render_model_svg(asset, view=view)
        assert "<line" in svg
    # front 视图下塔身竖直：end(z=500) 投影 y 应小于 start(z=0)
    svg = render_model_svg(asset, view="front")
    y1 = float(svg.split('y1="')[1].split('"')[0])
    y2 = float(svg.split('y2="')[1].split('"')[0])
    assert y2 < y1
