"""模型渲染与点云采样。

提供两类能力：
1. 将参数化矢量模型渲染为 SVG 二维预览图；
2. 将模型表面采样为带标签点云，用于合成训练数据。
"""
from __future__ import annotations

import math
import random
from typing import List, Sequence, Tuple

from .models import (
    Geometry,
    ModelAsset,
    PointCloudSample,
    Primitive,
    PrimitiveType,
)

# 国网 GIM 配色参考（简化）
MATERIAL_COLORS = {
    "default": "#888888",
    "conductor": "#C8102E",
    "insulator": "#8B5A2B",
    "steel": "#4A4A4A",
    "concrete": "#A9A9A9",
    "copper": "#B87333",
}


def _apply_transform(
    points: List[Tuple[float, float, float]],
    prim: Primitive,
) -> List[Tuple[float, float, float]]:
    px, py, pz = prim.position
    sx, sy, sz = prim.scale
    out = []
    for x, y, z in points:
        out.append((x * sx + px, y * sy + py, z * sz + pz))
    return out


def _sample_box(prim: Primitive, count: int) -> List[Tuple[float, float, float]]:
    w = float(prim.params.get("width", 100))
    d = float(prim.params.get("depth", 100))
    h = float(prim.params.get("height", 100))
    pts: List[Tuple[float, float, float]] = []
    half_w, half_d, half_h = w / 2, d / 2, h / 2
    # 六个面均匀采样
    faces = [
        ([(x, y, half_h) for x, y in _grid_2d(count // 6 + 1, w, d, -half_w, -half_d)]),
        ([(x, y, -half_h) for x, y in _grid_2d(count // 6 + 1, w, d, -half_w, -half_d)]),
        ([(x, half_d, z) for x, z in _grid_2d(count // 6 + 1, w, h, -half_w, -half_h)]),
        ([(x, -half_d, z) for x, z in _grid_2d(count // 6 + 1, w, h, -half_w, -half_h)]),
        ([(half_w, y, z) for y, z in _grid_2d(count // 6 + 1, d, h, -half_d, -half_h)]),
        ([(-half_w, y, z) for y, z in _grid_2d(count // 6 + 1, d, h, -half_d, -half_h)]),
    ]
    for face in faces:
        pts.extend(face)
    return pts[:count]


def _sample_cylinder(prim: Primitive, count: int) -> List[Tuple[float, float, float]]:
    r = float(prim.params.get("radius", 50))
    h = float(prim.params.get("height", 200))
    half_h = h / 2
    pts: List[Tuple[float, float, float]] = []
    side_n = max(8, count // 2)
    for i in range(side_n):
        a = 2 * math.pi * i / side_n
        for j in range(max(2, count // side_n + 1)):
            z = -half_h + h * j / max(1, count // side_n)
            pts.append((r * math.cos(a), r * math.sin(a), z))
    # 上下底面
    for z in (half_h, -half_h):
        for _ in range(max(1, count // 10)):
            rr = r * math.sqrt(random.random())
            a = random.uniform(0, 2 * math.pi)
            pts.append((rr * math.cos(a), rr * math.sin(a), z))
    return pts[:count]


def _sample_sphere(prim: Primitive, count: int) -> List[Tuple[float, float, float]]:
    r = float(prim.params.get("radius", 50))
    pts = []
    for _ in range(count):
        # 球面均匀分布
        u = random.random()
        v = random.random()
        theta = 2 * math.pi * u
        phi = math.acos(2 * v - 1)
        pts.append((r * math.sin(phi) * math.cos(theta), r * math.sin(phi) * math.sin(theta), r * math.cos(phi)))
    return pts


def _sample_cone(prim: Primitive, count: int) -> List[Tuple[float, float, float]]:
    r = float(prim.params.get("radius", 50))
    h = float(prim.params.get("height", 150))
    half_h = h / 2
    pts = []
    for _ in range(count):
        z = random.uniform(-half_h, half_h)
        rr = r * (1 - (z + half_h) / h)
        a = random.uniform(0, 2 * math.pi)
        pts.append((rr * math.cos(a), rr * math.sin(a), z))
    return pts


def _sample_torus(prim: Primitive, count: int) -> List[Tuple[float, float, float]]:
    R = float(prim.params.get("major_radius", 80))
    r = float(prim.params.get("minor_radius", 20))
    pts = []
    for _ in range(count):
        u = random.uniform(0, 2 * math.pi)
        v = random.uniform(0, 2 * math.pi)
        x = (R + r * math.cos(v)) * math.cos(u)
        y = (R + r * math.cos(v)) * math.sin(u)
        z = r * math.sin(v)
        pts.append((x, y, z))
    return pts


def _sample_line(prim: Primitive, count: int) -> List[Tuple[float, float, float]]:
    start = prim.params.get("start", [0, 0, 0])
    end = prim.params.get("end", [100, 0, 0])
    pts = []
    for i in range(count):
        t = i / max(1, count - 1)
        pts.append((
            start[0] + (end[0] - start[0]) * t,
            start[1] + (end[1] - start[1]) * t,
            start[2] + (end[2] - start[2]) * t,
        ))
    return pts


def _grid_2d(
    n: int, w: float, h: float, ox: float, oy: float
) -> List[Tuple[float, float]]:
    if n < 2:
        return [(ox, oy)]
    return [
        (ox + w * i / (n - 1), oy + h * j / (n - 1))
        for i in range(n)
        for j in range(n)
    ]


def _sample_primitive_points(prim: Primitive, count: int) -> List[Tuple[float, float, float]]:
    if count <= 0:
        return []
    if prim.type == PrimitiveType.BOX:
        pts = _sample_box(prim, count)
    elif prim.type == PrimitiveType.CYLINDER:
        pts = _sample_cylinder(prim, count)
    elif prim.type == PrimitiveType.SPHERE:
        pts = _sample_sphere(prim, count)
    elif prim.type == PrimitiveType.CONE:
        pts = _sample_cone(prim, count)
    elif prim.type == PrimitiveType.TORUS:
        pts = _sample_torus(prim, count)
    elif prim.type == PrimitiveType.LINE:
        pts = _sample_line(prim, count)
    elif prim.type == PrimitiveType.POLYGON:
        pts = _sample_box(prim, count)  # 简化：按平面矩形采样
    else:
        pts = [(0.0, 0.0, 0.0)]
    return _apply_transform(pts, prim)


def sample_model_pointcloud(
    model: ModelAsset,
    count: int = 1000,
    seed: Optional[int] = None,
) -> PointCloudSample:
    """将模型基本图元表面采样为带标签点云。"""
    if seed is not None:
        random.seed(seed)
    primitives = model.geometry.primitives
    if not primitives:
        return PointCloudSample(model_id=model.id, points=[], labels=[], count=0)

    # 按图元数量均分采样点数
    per = max(1, count // len(primitives))
    points: List[List[float]] = []
    labels: List[str] = []
    for prim in primitives:
        pts = _sample_primitive_points(prim, per)
        for p in pts:
            points.append([round(v, 3) for v in p])
            labels.append(prim.name or prim.type.value)
    # 截断到目标数量
    points = points[:count]
    labels = labels[:count]
    return PointCloudSample(model_id=model.id, points=points, labels=labels, count=len(points))


# ---------- SVG 预览 ----------
def _project_view(view: str, x: float, y: float, z: float) -> Tuple[float, float]:
    """多视角投影。GIM 规范 Z 轴为高度轴（Q/GDW 11809 附录B），SVG y 向下。

    - iso: 等轴测（默认）
    - front: 正视（x 向右，z 向上）
    - side: 侧视（y 向右，z 向上）
    - top: 俯视（x 向右，y 向下）
    """
    if view == "front":
        return x, -z
    if view == "side":
        return y, -z
    if view == "top":
        return x, y
    return (x - y) * 0.866, (x + y) * 0.5 - z


def _project(x: float, y: float, z: float) -> Tuple[float, float]:
    """等轴测投影（z-up）。"""
    return _project_view("iso", x, y, z)


def _primitive_bounds(prim: Primitive, view: str = "iso") -> List[Tuple[float, float]]:
    """图元的 2D 投影采样点（用于包围盒计算）。"""
    if prim.type == PrimitiveType.LINE:
        start = prim.params.get("start", [0, 0, 0])
        end = prim.params.get("end", [100, 0, 0])
        return [_project_view(view, *start), _project_view(view, *end)]
    if prim.type == PrimitiveType.BOX:
        w = float(prim.params.get("width", 100))
        d = float(prim.params.get("depth", 100))
        h = float(prim.params.get("height", 100))
        pts = [
            (x, y, z)
            for x in (-w / 2, w / 2)
            for y in (-d / 2, d / 2)
            for z in (-h / 2, h / 2)
        ]
        return [_project_view(view, px + prim.position[0], py + prim.position[1], pz + prim.position[2])
                for px, py, pz in pts]
    # 旋转体/球类：用位置 ± 最大特征尺寸近似
    if prim.type in (PrimitiveType.CYLINDER, PrimitiveType.CONE):
        r = float(prim.params.get("radius", 50))
        h = float(prim.params.get("height", 200)) / 2
        ext = max(r, h)
    elif prim.type == PrimitiveType.SPHERE:
        ext = float(prim.params.get("radius", 50))
    elif prim.type == PrimitiveType.TORUS:
        ext = float(prim.params.get("major_radius", 80)) + float(prim.params.get("minor_radius", 20))
    else:
        ext = 10.0
    cx, cy, cz = prim.position
    return [
        _project_view(view, cx - ext, cy - ext, cz - ext),
        _project_view(view, cx + ext, cy + ext, cz + ext),
    ]


def _fit_transform(primitives, width: int, height: int, view: str = "iso", pad: float = 24.0):
    """计算将图元包围盒适配进画布的 (tx, ty, scale)。"""
    pts = []
    for prim in primitives:
        pts.extend(_primitive_bounds(prim))
    if not pts:
        return 0.0, 0.0, 1.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    w, h = maxx - minx, maxy - miny
    scale = min((width - pad * 2) / w if w > 1e-6 else 1e3,
                (height - pad * 2) / h if h > 1e-6 else 1e3)
    scale = min(scale, 1e3)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    return -cx * scale, -cy * scale, scale


def _svg_primitive(prim: Primitive, view: str = "iso") -> str:
    """将单个图元投影为 SVG 元素（简化表示）。"""
    color = MATERIAL_COLORS.get(prim.material, prim.color)
    if prim.type == PrimitiveType.BOX:
        w = float(prim.params.get("width", 100))
        d = float(prim.params.get("depth", 100))
        h = float(prim.params.get("height", 100))
        corners = [
            (x, y, z)
            for x in (-w / 2, w / 2)
            for y in (-d / 2, d / 2)
            for z in (-h / 2, h / 2)
        ]
        # 简单绘制一个矩形代表盒子
        pts = [_project_view(view, x, y, z) for x, y, z in corners]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x, y = min(xs), min(ys)
        ww, hh = max(xs) - min(xs), max(ys) - min(ys)
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{ww:.1f}" height="{hh:.1f}" fill="{color}" fill-opacity="0.7" stroke="#222" stroke-width="1.5"/>'
    if prim.type == PrimitiveType.CYLINDER:
        r = float(prim.params.get("radius", 50))
        h = float(prim.params.get("height", 200))
        cx, cy = _project_view(view, prim.position[0], prim.position[1] - h / 2, prim.position[2])
        return f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{r:.1f}" ry="{r * 0.4:.1f}" fill="{color}" fill-opacity="0.7" stroke="#222" stroke-width="1.5"/>'
    if prim.type == PrimitiveType.SPHERE:
        r = float(prim.params.get("radius", 50))
        cx, cy = _project_view(view, *prim.position)
        return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{color}" fill-opacity="0.7" stroke="#222" stroke-width="1.5"/>'
    if prim.type == PrimitiveType.CONE:
        r = float(prim.params.get("radius", 50))
        h = float(prim.params.get("height", 150))
        cx, cy = _project_view(view, *prim.position)
        return f'<path d="M {cx-r:.1f} {cy+h/2:.1f} L {cx+r:.1f} {cy+h/2:.1f} L {cx:.1f} {cy-h/2:.1f} Z" fill="{color}" fill-opacity="0.7" stroke="#222" stroke-width="1.5"/>'
    if prim.type == PrimitiveType.LINE:
        start = prim.params.get("start", [0, 0, 0])
        end = prim.params.get("end", [100, 0, 0])
        x1, y1 = _project_view(view, *start)
        x2, y2 = _project_view(view, *end)
        return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="3"/>'
    # 默认
    cx, cy = _project_view(view, *prim.position)
    return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="10" fill="{color}"/>'


def render_model_svg(model: ModelAsset, width: int = 480, height: int = 360, view: str = "iso") -> str:
    """生成模型 SVG 预览（自动缩放适配画布）。"""
    tx, ty, scale = _fit_transform(model.geometry.primitives, width, height, view)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="{-width/2} {-height/2} {width} {height}">',
        f'<rect x="{-width/2}" y="{-height/2}" width="{width}" height="{height}" fill="#fafafa" stroke="#ccc"/>',
    ]
    if model.geometry.primitives:
        parts.append(f'<g transform="translate({tx:.2f},{ty:.2f}) scale({scale:.6f})">')
        for prim in model.geometry.primitives:
            parts.append(_svg_primitive(prim, view))
        parts.append("</g>")
    # 标题文字固定在画布角上，不参与缩放
    parts.append(
        f'<text x="{-width/2+12}" y="{-height/2+24}" font-size="16" font-family="sans-serif">{model.name}</text>'
    )
    parts.append(
        f'<text x="{-width/2+12}" y="{-height/2+44}" font-size="12" font-family="sans-serif" fill="#666">{model.code} · {model.voltage_level} · {model.stage.value}</text>'
    )
    if not model.geometry.primitives:
        # 空模型占位符：简化的电塔/闪电符号
        parts.append(
            '<path d="M 0 -80 L 20 -20 L 5 -20 L 15 60 L -15 -10 L 0 -10 L -20 -80 Z" '
            'fill="#f5c542" stroke="#333" stroke-width="2"/>'
        )
    parts.append("</svg>")
    return "\n".join(parts)
