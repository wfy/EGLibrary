"""STL 几何文件解析（Q/GDW 11809 A.6.4 挂接文件，二进制/ASCII 双格式）。

STL 三角面数量大（单文件可达数万面），不入模型几何 JSON；
提供统计（parse_stl）与流式三角面（stl_triangles）供三维端点按需加载。
"""
from __future__ import annotations

import struct

MIN_BINARY_SIZE = 84


def _is_binary(data: bytes) -> bool:
    if len(data) < MIN_BINARY_SIZE:
        return False
    count = struct.unpack("<I", data[80:84])[0]
    # 二进制 STL：84 + 50*面数 应与文件长度吻合
    return 84 + 50 * count == len(data)


def parse_stl(data: bytes) -> dict:
    """STL 统计：{format, triangles, bounds}。bounds=[[minxyz],[maxxyz]]。"""
    fmt = "binary" if _is_binary(data) else "ascii"
    count = 0
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3

    if fmt == "binary":
        if len(data) < MIN_BINARY_SIZE:
            return {"format": "binary", "triangles": 0, "bounds": [[0, 0, 0], [0, 0, 0]]}
        count = struct.unpack("<I", data[80:84])[0]
        offset = 84
        for _ in range(count):
            vals = struct.unpack("<12f", data[offset:offset + 48])  # 法线3+顶点9
            for vi in range(3):
                x, y, z = vals[3 + vi * 3:3 + vi * 3 + 3]
                lo[0] = min(lo[0], x); hi[0] = max(hi[0], x)
                lo[1] = min(lo[1], y); hi[1] = max(hi[1], y)
                lo[2] = min(lo[2], z); hi[2] = max(hi[2], z)
            offset += 50
    else:
        try:
            text = data.decode("ascii", errors="replace")
        except Exception:
            text = ""
        verts = []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("vertex"):
                try:
                    verts.append([float(x) for x in s.split()[1:4]])
                except (ValueError, IndexError):
                    continue
        count = len(verts) // 3
        for v in verts:
            for i in range(3):
                lo[i] = min(lo[i], v[i]); hi[i] = max(hi[i], v[i])

    if count == 0:
        lo, hi = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    return {
        "format": fmt,
        "triangles": count,
        "bounds": [
            [round(v, 4) for v in lo],
            [round(v, 4) for v in hi],
        ],
    }


def stl_triangles(data: bytes):
    """流式产出三角面 [[[x,y,z],[x,y,z],[x,y,z]], ...]（生成器，省内存）。"""
    if _is_binary(data):
        count = struct.unpack("<I", data[80:84])[0]
        offset = 84
        for _ in range(count):
            vals = struct.unpack("<12f", data[offset:offset + 48])  # 法线3+顶点9
            yield [list(vals[3 + i * 3:3 + i * 3 + 3]) for i in range(3)]
            offset += 50
        return
    verts = []
    for line in data.decode("ascii", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("vertex"):
            try:
                verts.append([float(x) for x in s.split()[1:4]])
            except (ValueError, IndexError):
                continue
    for i in range(0, len(verts) - 2, 3):
        yield verts[i:i + 3]
