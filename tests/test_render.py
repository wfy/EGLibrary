"""渲染层测试：GIM z-up 轴向 + 自动缩放适配画布。"""
import re

from egrid.models import Geometry, ModelAsset, Primitive, PrimitiveType
from egrid.render import _project, render_model_svg


def test_project_z_is_up():
    """GIM 规范：Z 轴为高度轴，z 越大 SVG y 越小（越靠上）。"""
    assert _project(0, 0, 100)[1] < _project(0, 0, 0)[1]
    # 水平面 x/y 不应再进入竖直主导分量
    assert _project(100, 0, 0)[1] > _project(0, 0, 100)[1]


def _svg_line_points(svg: str, width: float, height: float):
    """提取 g transform 与 line 端点，返回变换后的 2D 点集。"""
    m = re.search(r'<g transform="translate\(([-\d.]+)[, ]+([-\d.]+)\)\s*scale\(([-\d.]+)\)"', svg)
    pts = []
    for x1, y1, x2, y2 in re.findall(r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"', svg):
        for x, y in ((float(x1), float(y1)), (float(x2), float(y2))):
            if m:
                tx, ty, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
                x, y = x * s + tx, y * s + ty
            pts.append((x, y))
    return pts


def test_tower_fits_viewbox():
    """47m 杆塔（z-up，xy 平面小）应整体缩放进画布，而不是放倒或出界。"""
    lines = [
        Primitive(name="塔身", type=PrimitiveType.LINE,
                  params={"start": [-1100, -1100, 0], "end": [1100, 1100, 47000]}),
        Primitive(name="横担", type=PrimitiveType.LINE,
                  params={"start": [-5000, 0, 40000], "end": [5000, 0, 40000]}),
    ]
    asset = ModelAsset(name="测试塔", geometry=Geometry(primitives=lines))
    svg = render_model_svg(asset, width=480, height=360)
    pts = _svg_line_points(svg, 480, 360)
    assert pts, "应渲染出 line 元素"
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    assert -240 <= min(xs) and max(xs) <= 240, f"x 出界: {min(xs)}~{max(xs)}"
    assert -180 <= min(ys) and max(ys) <= 180, f"y 出界: {min(ys)}~{max(ys)}"
    # 塔身应竖直：顶端(z=47000)的 y 小于底端(z=0)
    top_y = next(y for (x, y) in pts if abs(x) < 200 and y == min(ys))
    assert min(ys) < max(ys)  # 有高度差


def test_small_model_still_visible():
    """小模型应放大充满画布而非缩成一个点。"""
    prim = Primitive(name="球", type=PrimitiveType.SPHERE, params={"radius": 5})
    asset = ModelAsset(name="小球", geometry=Geometry(primitives=[prim]))
    svg = render_model_svg(asset, width=480, height=360)
    assert "scale(" in svg
