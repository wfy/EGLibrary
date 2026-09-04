"""模型几何与 AI 训练点云多格式导出器。

支持导出：
1. 三维几何：Wavefront OBJ (.obj)、二进制合并 STL (.stl)
2. AI 训练点云：ASPRS LAS 1.2 (.las)、文本点云 (.txt / XYZ-RGB-Label)
3. 点云训练数据增强：高斯噪声注入、3D 空间随机姿态扰动
"""
from __future__ import annotations

import math
import random
import struct
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from .models import ModelAsset, Primitive, PrimitiveType

SEMANTIC_CLASSES = {
    "unclassified": {"id": 0, "name": "未分类", "rgb": (180, 180, 180)},
    "tower": {"id": 1, "name": "杆塔主体", "rgb": (80, 120, 160)},
    "insulator": {"id": 2, "name": "绝缘子串", "rgb": (210, 140, 50)},
    "fitting": {"id": 3, "name": "金具附件", "rgb": (230, 200, 70)},
    "conductor": {"id": 4, "name": "导地线", "rgb": (200, 40, 40)},
    "substation": {"id": 5, "name": "变电设备", "rgb": (50, 170, 120)},
}


def classify_label(label: str) -> Tuple[int, str, Tuple[int, int, int]]:
    """根据采样标签推断电力语义标签 ID、名称和 RGB 颜色。"""
    lbl = (label or "").lower()
    if any(k in lbl for k in ["fxbw", "xp-", "xp_", "insu", "string", "复合", "绝缘子", "1md11y"]):
        c = SEMANTIC_CLASSES["insulator"]
    elif any(k in lbl for k in ["wire", "conductor", "导线", "地线", "cable"]):
        c = SEMANTIC_CLASSES["conductor"]
    elif any(k in lbl for k in ["fitting", "clamp", "金具", "防振锤", "线夹", "挂环", "u-bolt"]):
        c = SEMANTIC_CLASSES["fitting"]
    elif any(k in lbl for k in ["byq", "transformer", "bushing", "变压器", "套管", "开关", "disconnector"]):
        c = SEMANTIC_CLASSES["substation"]
    elif any(k in lbl for k in ["tower", "leg", "body", "pole", "杆塔", "塔身", "塔腿", "line", "sdj"]):
        c = SEMANTIC_CLASSES["tower"]
    else:
        c = SEMANTIC_CLASSES["tower"]
    return c["id"], c["name"], c["rgb"]


def augment_pointcloud(
    points: Sequence[Sequence[float]],
    noise: float = 0.0,
    augment: bool = False,
    seed: Optional[int] = None,
) -> List[List[float]]:
    """对点云坐标注入高斯噪声或随机 3D 旋转扰动。"""
    rng = random.Random(seed) if seed is not None else random
    out = [[p[0], p[1], p[2]] for p in points]

    # 随机旋转增强（围绕 Z 轴随机偏航，围绕 X/Y 轴 ±5° 小幅俯仰倾斜）
    if augment:
        yaw = rng.uniform(0, 2 * math.pi)
        pitch = rng.uniform(-5 * math.pi / 180, 5 * math.pi / 180)
        roll = rng.uniform(-5 * math.pi / 180, 5 * math.pi / 180)

        cy, sy = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        cr, sr = math.cos(roll), math.sin(roll)

        r00 = cy * cp
        r01 = cy * sp * sr - sy * cr
        r02 = cy * sp * cr + sy * sr

        r10 = sy * cp
        r11 = sy * sp * sr + cy * cr
        r12 = sy * sp * cr - cy * sr

        r20 = -sp
        r21 = cp * sr
        r22 = cp * cr

        for i, (x, y, z) in enumerate(out):
            nx = r00 * x + r01 * y + r02 * z
            ny = r10 * x + r11 * y + r12 * z
            nz = r20 * x + r21 * y + r22 * z
            out[i] = [nx, ny, nz]

    # 高斯测距噪声注入
    if noise > 0:
        for i, (x, y, z) in enumerate(out):
            out[i] = [
                x + rng.gauss(0, noise),
                y + rng.gauss(0, noise),
                z + rng.gauss(0, noise),
            ]

    return [[round(v, 4) for v in p] for p in out]


def export_txt_pointcloud(
    points: Sequence[Sequence[float]],
    labels: Sequence[str],
    delimiter: str = " ",
) -> str:
    """生成带语义分类的标准文本点云 (X Y Z R G B Classification Label)。"""
    lines = ["# X Y Z R G B Classification Label"]
    for pt, label in zip(points, labels):
        cid, cname, rgb = classify_label(label)
        line = delimiter.join([
            f"{pt[0]:.4f}",
            f"{pt[1]:.4f}",
            f"{pt[2]:.4f}",
            str(rgb[0]),
            str(rgb[1]),
            str(rgb[2]),
            str(cid),
            cname,
        ])
        lines.append(line)
    return "\n".join(lines) + "\n"


def export_las_bytes(
    points: Sequence[Sequence[float]],
    labels: Sequence[str],
    scale: Tuple[float, float, float] = (0.001, 0.001, 0.001),
) -> bytes:
    """生成标准 ASPRS LAS 1.2 (Point Format 2, 带 RGB 与 Classification) 二进制数据。"""
    n_points = len(points)
    if n_points == 0:
        min_x = max_x = min_y = max_y = min_z = max_z = 0.0
    else:
        min_x = min(p[0] for p in points)
        max_x = max(p[0] for p in points)
        min_y = min(p[1] for p in points)
        max_y = max(p[1] for p in points)
        min_z = min(p[2] for p in points)
        max_z = max(p[2] for p in points)

    offset_x = math.floor(min_x)
    offset_y = math.floor(min_y)
    offset_z = math.floor(min_z)

    sx, sy, sz = scale
    header_size = 227
    offset_to_point_data = header_size
    point_record_len = 26  # Format 2 = 26 bytes

    now = datetime.now()
    day_of_year = now.timetuple().tm_yday
    year = now.year

    header = bytearray(header_size)
    header[0:4] = b"LASF"
    header[24] = 1
    header[25] = 2
    sys_id = b"EGLibrary".ljust(32, b"\x00")
    header[26:58] = sys_id
    gen_sw = b"EGLibrary PointCloud Generator"[:32].ljust(32, b"\x00")
    header[58:90] = gen_sw
    struct.pack_into("<HH", header, 90, day_of_year, year)
    struct.pack_into("<HI", header, 94, header_size, offset_to_point_data)
    struct.pack_into("<I", header, 100, 0)
    header[104] = 2
    struct.pack_into("<H", header, 105, point_record_len)
    struct.pack_into("<I", header, 107, n_points)
    struct.pack_into("<5I", header, 111, n_points, 0, 0, 0, 0)
    struct.pack_into("<3d", header, 131, sx, sy, sz)
    struct.pack_into("<3d", header, 155, offset_x, offset_y, offset_z)
    struct.pack_into("<6d", header, 179, max_x, min_x, max_y, min_y, max_z, min_z)

    body = bytearray(n_points * point_record_len)
    for i, (pt, label) in enumerate(zip(points, labels)):
        ix = int(round((pt[0] - offset_x) / sx))
        iy = int(round((pt[1] - offset_y) / sy))
        iz = int(round((pt[2] - offset_z) / sz))
        intensity = 1000
        return_byte = 0x09
        cid, _, rgb = classify_label(label)
        scan_angle = 0
        user_data = 0
        point_source_id = 1
        r16 = min(65535, rgb[0] * 256)
        g16 = min(65535, rgb[1] * 256)
        b16 = min(65535, rgb[2] * 256)

        pos = i * point_record_len
        struct.pack_into(
            "<iiiHBBbBHHHH",
            body,
            pos,
            ix, iy, iz,
            intensity,
            return_byte,
            cid,
            scan_angle,
            user_data,
            point_source_id,
            r16, g16, b16,
        )

    return bytes(header) + bytes(body)


def export_obj_mesh(
    model: ModelAsset,
    stl_sources: Optional[List[dict]] = None,
) -> str:
    """生成标准 Wavefront OBJ 几何文件（包含线框元素与 STL 面片）。"""
    lines = [
        "# EGLibrary OBJ Export",
        f"# Model: {model.name} ({model.id})",
        f"# Export Time: {datetime.now().isoformat()}",
        "o RootModel",
    ]

    v_offset = 1
    # 1. 导出线框图元
    for prim in model.geometry.primitives:
        if prim.type == PrimitiveType.LINE:
            p1 = prim.params.get("start", [0, 0, 0])
            p2 = prim.params.get("end", [100, 0, 0])
            lines.append(f"v {p1[0]:.4f} {p1[1]:.4f} {p1[2]:.4f}")
            lines.append(f"v {p2[0]:.4f} {p2[1]:.4f} {p2[2]:.4f}")
            lines.append(f"l {v_offset} {v_offset + 1}")
            v_offset += 2

    for prim in model.geometry.primitives:
        if prim.type in (PrimitiveType.BOX, PrimitiveType.CYLINDER, PrimitiveType.CONE, PrimitiveType.SPHERE, PrimitiveType.TORUS):
            for norm, p1, p2, p3 in primitive_to_triangles(prim):
                lines.append(f"v {p1[0]:.4f} {p1[1]:.4f} {p1[2]:.4f}")
                lines.append(f"v {p2[0]:.4f} {p2[1]:.4f} {p2[2]:.4f}")
                lines.append(f"v {p3[0]:.4f} {p3[1]:.4f} {p3[2]:.4f}")
                lines.append(f"vn {norm[0]:.4f} {norm[1]:.4f} {norm[2]:.4f}")
                lines.append(f"f {v_offset} {v_offset+1} {v_offset+2}")
                v_offset += 3

    # 2. 导出 STL 部件三角形
    stl_sources = stl_sources or []
    for src in stl_sources:
        part_name = Path(src.get("path", "part")).stem
        lines.append(f"o {part_name}")
        triangles = src.get("triangles") or []
        m = src.get("transform") or []

        for tri in triangles:
            p1, p2, p3 = tri[0], tri[1], tri[2]
            if m and len(m) >= 12:
                p1 = [m[0]*p1[0] + m[1]*p1[1] + m[2]*p1[2] + m[3],
                      m[4]*p1[0] + m[5]*p1[1] + m[6]*p1[2] + m[7],
                      m[8]*p1[0] + m[9]*p1[1] + m[10]*p1[2] + m[11]]
                p2 = [m[0]*p2[0] + m[1]*p2[1] + m[2]*p2[2] + m[3],
                      m[4]*p2[0] + m[5]*p2[1] + m[6]*p2[2] + m[7],
                      m[8]*p2[0] + m[9]*p2[1] + m[10]*p2[2] + m[11]]
                p3 = [m[0]*p3[0] + m[1]*p3[1] + m[2]*p3[2] + m[3],
                      m[4]*p3[0] + m[5]*p3[1] + m[6]*p3[2] + m[7],
                      m[8]*p3[0] + m[9]*p3[1] + m[10]*p3[2] + m[11]]

            ux, uy, uz = p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]
            vx, vy, vz = p3[0] - p1[0], p3[1] - p1[1], p3[2] - p1[2]
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            n_len = math.sqrt(nx * nx + ny * ny + nz * nz)
            if n_len > 1e-6:
                nx, ny, nz = nx / n_len, ny / n_len, nz / n_len
            else:
                nx, ny, nz = 0.0, 0.0, 1.0

            lines.append(f"v {p1[0]:.4f} {p1[1]:.4f} {p1[2]:.4f}")
            lines.append(f"v {p2[0]:.4f} {p2[1]:.4f} {p2[2]:.4f}")
            lines.append(f"v {p3[0]:.4f} {p3[1]:.4f} {p3[2]:.4f}")
            lines.append(f"vn {nx:.4f} {ny:.4f} {nz:.4f}")
            lines.append(f"f {v_offset} {v_offset+1} {v_offset+2}")
            v_offset += 3

    return "\n".join(lines) + "\n"


def export_stl_bytes(
    model: ModelAsset,
    stl_sources: Optional[List[dict]] = None,
) -> bytes:
    """合并所有 STL 部件与几何三角形为二进制 STL 文件。"""
    transformed_triangles = []
    stl_sources = stl_sources or []

    for src in stl_sources:
        triangles = src.get("triangles") or []
        m = src.get("transform") or []
        for tri in triangles:
            p1, p2, p3 = tri[0], tri[1], tri[2]
            if m and len(m) >= 12:
                p1 = [m[0]*p1[0] + m[1]*p1[1] + m[2]*p1[2] + m[3],
                      m[4]*p1[0] + m[5]*p1[1] + m[6]*p1[2] + m[7],
                      m[8]*p1[0] + m[9]*p1[1] + m[10]*p1[2] + m[11]]
                p2 = [m[0]*p2[0] + m[1]*p2[1] + m[2]*p2[2] + m[3],
                      m[4]*p2[0] + m[5]*p2[1] + m[6]*p2[2] + m[7],
                      m[8]*p2[0] + m[9]*p2[1] + m[10]*p2[2] + m[11]]
                p3 = [m[0]*p3[0] + m[1]*p3[1] + m[2]*p3[2] + m[3],
                      m[4]*p3[0] + m[5]*p3[1] + m[6]*p3[2] + m[7],
                      m[8]*p3[0] + m[9]*p3[1] + m[10]*p3[2] + m[11]]

            ux, uy, uz = p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]
            vx, vy, vz = p3[0] - p1[0], p3[1] - p1[1], p3[2] - p1[2]
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            n_len = math.sqrt(nx * nx + ny * ny + nz * nz)
            if n_len > 1e-6:
                norm = (nx / n_len, ny / n_len, nz / n_len)
            else:
                norm = (0.0, 0.0, 1.0)
            transformed_triangles.append((norm, p1, p2, p3))

    for prim in model.geometry.primitives:
        if prim.type in (PrimitiveType.BOX, PrimitiveType.CYLINDER, PrimitiveType.CONE, PrimitiveType.SPHERE, PrimitiveType.TORUS):
            transformed_triangles.extend(primitive_to_triangles(prim))

    if not transformed_triangles:
        for prim in model.geometry.primitives:
            if prim.type == PrimitiveType.LINE:
                s = prim.params.get("start", [0, 0, 0])
                e = prim.params.get("end", [100, 0, 0])
                r = 0.05
                p1 = [s[0], s[1], s[2]]
                p2 = [s[0] + r, s[1], s[2]]
                p3 = [e[0], e[1], e[2]]
                transformed_triangles.append(((0.0, 0.0, 1.0), p1, p2, p3))

    n_tri = len(transformed_triangles)
    header = f"EGLibrary STL Export: {model.name}".encode("ascii", errors="replace")[:80].ljust(80, b"\x00")
    body = bytearray(4 + n_tri * 50)
    struct.pack_into("<I", body, 0, n_tri)

    offset = 4
    for norm, p1, p2, p3 in transformed_triangles:
        struct.pack_into(
            "<12fH",
            body,
            offset,
            float(norm[0]), float(norm[1]), float(norm[2]),
            float(p1[0]), float(p1[1]), float(p1[2]),
            float(p2[0]), float(p2[1]), float(p2[2]),
            float(p3[0]), float(p3[1]), float(p3[2]),
            0,
        )
        offset += 50

    return header + bytes(body)


def primitive_to_triangles(
    prim: Primitive,
) -> List[Tuple[Tuple[float, float, float], List[float], List[float], List[float]]]:
    '''将参数化实体图元转换为三角面片列表，并应用空间变换。'''
    raw_triangles = []
    ptype = prim.type
    params = prim.params or {}

    if ptype == PrimitiveType.BOX:
        w = float(params.get('width') or 0)
        d = float(params.get('depth') or 0)
        h = float(params.get('height') or 0)
        w = w if w > 0 else 20.0
        d = d if d > 0 else 20.0
        h = h if h > 0 else 20.0
        x0, x1 = -w / 2.0, w / 2.0
        y0, y1 = -d / 2.0, d / 2.0
        z0, z1 = 0.0, h
        faces = [
            ((0, 0, 1), [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]),
            ((0, 0, -1), [x0, y1, z0], [x1, y1, z0], [x1, y0, z0], [x0, y0, z0]),
            ((0, -1, 0), [x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]),
            ((0, 1, 0), [x1, y1, z0], [x0, y1, z0], [x0, y1, z1], [x1, y1, z1]),
            ((-1, 0, 0), [x0, y1, z0], [x0, y0, z0], [x0, y0, z1], [x0, y1, z1]),
            ((1, 0, 0), [x1, y0, z0], [x1, y1, z0], [x1, y1, z1], [x1, y0, z1]),
        ]
        for norm, p1, p2, p3, p4 in faces:
            raw_triangles.append((norm, p1, p2, p3))
            raw_triangles.append((norm, p1, p3, p4))

    elif ptype == PrimitiveType.CYLINDER:
        r = float(params.get('radius') or 50.0)
        h = float(params.get('height') or 100.0)
        segs = 16
        for i in range(segs):
            a1 = 2.0 * math.pi * i / segs
            a2 = 2.0 * math.pi * (i + 1) / segs
            x1, y1 = r * math.cos(a1), r * math.sin(a1)
            x2, y2 = r * math.cos(a2), r * math.sin(a2)
            mid_a = (a1 + a2) / 2.0
            n1 = (math.cos(mid_a), math.sin(mid_a), 0.0)
            raw_triangles.append((n1, [x1, y1, 0.0], [x2, y2, 0.0], [x2, y2, h]))
            raw_triangles.append((n1, [x1, y1, 0.0], [x2, y2, h], [x1, y1, h]))
            raw_triangles.append(((0, 0, -1), [0.0, 0.0, 0.0], [x2, y2, 0.0], [x1, y1, 0.0]))
            raw_triangles.append(((0, 0, 1), [0.0, 0.0, h], [x1, y1, h], [x2, y2, h]))

    elif ptype == PrimitiveType.CONE:
        r1 = float(params.get('radius') or 50.0)
        r2 = float(params.get('radius2') or 0.0)
        h = float(params.get('height') or 100.0)
        segs = 16
        for i in range(segs):
            a1 = 2.0 * math.pi * i / segs
            a2 = 2.0 * math.pi * (i + 1) / segs
            x1, y1 = r1 * math.cos(a1), r1 * math.sin(a1)
            x2, y2 = r1 * math.cos(a2), r1 * math.sin(a2)
            tx1, ty1 = r2 * math.cos(a1), r2 * math.sin(a1)
            tx2, ty2 = r2 * math.cos(a2), r2 * math.sin(a2)
            mid_a = (a1 + a2) / 2.0
            raw_triangles.append(((math.cos(mid_a), math.sin(mid_a), 0.0), [x1, y1, 0.0], [x2, y2, 0.0], [tx2, ty2, h]))
            raw_triangles.append(((math.cos(mid_a), math.sin(mid_a), 0.0), [x1, y1, 0.0], [tx2, ty2, h], [tx1, ty1, h]))
            if r1 > 0:
                raw_triangles.append(((0, 0, -1), [0.0, 0.0, 0.0], [x2, y2, 0.0], [x1, y1, 0.0]))
            if r2 > 0:
                raw_triangles.append(((0, 0, 1), [0.0, 0.0, h], [tx1, ty1, h], [tx2, ty2, h]))

    elif ptype == PrimitiveType.SPHERE:
        r = float(params.get('radius') or 50.0)
        rings = 10
        sectors = 14
        for i in range(rings):
            lat1 = math.pi * (-0.5 + float(i) / rings)
            lat2 = math.pi * (-0.5 + float(i + 1) / rings)
            z1 = r * math.sin(lat1)
            zr1 = r * math.cos(lat1)
            z2 = r * math.sin(lat2)
            zr2 = r * math.cos(lat2)
            for j in range(sectors):
                lng1 = 2.0 * math.pi * float(j) / sectors
                lng2 = 2.0 * math.pi * float(j + 1) / sectors
                p1 = [zr1 * math.cos(lng1), zr1 * math.sin(lng1), z1]
                p2 = [zr1 * math.cos(lng2), zr1 * math.sin(lng2), z1]
                p3 = [zr2 * math.cos(lng2), zr2 * math.sin(lng2), z2]
                p4 = [zr2 * math.cos(lng1), zr2 * math.sin(lng1), z2]
                n = (p1[0] / max(1.0, r), p1[1] / max(1.0, r), p1[2] / max(1.0, r))
                raw_triangles.append((n, p1, p2, p3))
                raw_triangles.append((n, p1, p3, p4))

    elif ptype == PrimitiveType.TORUS:
        R = float(params.get('major_radius') or 100.0)
        r = float(params.get('minor_radius') or 20.0)
        segs_r = 12
        segs_t = 16
        for i in range(segs_t):
            u1 = 2.0 * math.pi * i / segs_t
            u2 = 2.0 * math.pi * (i + 1) / segs_t
            for j in range(segs_r):
                v1 = 2.0 * math.pi * j / segs_r
                v2 = 2.0 * math.pi * (j + 1) / segs_r
                def torus_pt(u, v):
                    return [(R + r * math.cos(v)) * math.cos(u), (R + r * math.cos(v)) * math.sin(u), r * math.sin(v)]
                tp1 = torus_pt(u1, v1)
                tp2 = torus_pt(u2, v1)
                tp3 = torus_pt(u2, v2)
                tp4 = torus_pt(u1, v2)
                norm = (math.cos(v1) * math.cos(u1), math.cos(v1) * math.sin(u1), math.sin(v1))
                raw_triangles.append((norm, tp1, tp2, tp3))
                raw_triangles.append((norm, tp1, tp3, tp4))

    out = []
    m = prim.transform
    pos = prim.position or [0.0, 0.0, 0.0]
    for norm, p1, p2, p3 in raw_triangles:
        if m and len(m) == 16:
            def tf16(p):
                return [
                    m[0]*p[0] + m[4]*p[1] + m[8]*p[2] + m[12],
                    m[1]*p[0] + m[5]*p[1] + m[9]*p[2] + m[13],
                    m[2]*p[0] + m[6]*p[1] + m[10]*p[2] + m[14]
                ]
            def tfn16(n):
                nx = m[0]*n[0] + m[4]*n[1] + m[8]*n[2]
                ny = m[1]*n[0] + m[5]*n[1] + m[9]*n[2]
                nz = m[2]*n[0] + m[6]*n[1] + m[10]*n[2]
                l = math.sqrt(nx*nx + ny*ny + nz*nz)
                return (nx/l, ny/l, nz/l) if l > 1e-6 else (0.0, 0.0, 1.0)
            out.append((tfn16(norm), tf16(p1), tf16(p2), tf16(p3)))
        elif m and len(m) >= 12:
            def tf12(p):
                return [
                    m[0]*p[0] + m[1]*p[1] + m[2]*p[2] + m[3],
                    m[4]*p[0] + m[5]*p[1] + m[6]*p[2] + m[7],
                    m[8]*p[0] + m[9]*p[1] + m[10]*p[2] + m[11]
                ]
            def tfn12(n):
                nx = m[0]*n[0] + m[1]*n[1] + m[2]*n[2]
                ny = m[4]*n[0] + m[5]*n[1] + m[6]*n[2]
                nz = m[8]*n[0] + m[9]*n[1] + m[10]*n[2]
                l = math.sqrt(nx*nx + ny*ny + nz*nz)
                return (nx/l, ny/l, nz/l) if l > 1e-6 else (0.0, 0.0, 1.0)
            out.append((tfn12(norm), tf12(p1), tf12(p2), tf12(p3)))
        else:
            tp1 = [p1[0] + pos[0], p1[1] + pos[1], p1[2] + pos[2]]
            tp2 = [p2[0] + pos[0], p2[1] + pos[1], p2[2] + pos[2]]
            tp3 = [p3[0] + pos[0], p3[1] + pos[1], p3[2] + pos[2]]
            out.append((norm, tp1, tp2, tp3))
    return out
