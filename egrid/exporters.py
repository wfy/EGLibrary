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

from .models import ModelAsset, PrimitiveType

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

