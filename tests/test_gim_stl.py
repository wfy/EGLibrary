"""STL 几何文件解析测试（二进制/ASCII 双格式）。"""
import struct
from pathlib import Path

from egrid.gim.parsers.stl import parse_stl, stl_triangles

FIXTURE = Path(__file__).parent / "fixtures" / "sample.stl"


def test_parse_stl_stats():
    data = FIXTURE.read_bytes()
    info = parse_stl(data)
    assert info["triangles"] == 312
    assert len(info["bounds"]) == 2          # [min, max]
    assert len(info["bounds"][0]) == 3
    lo, hi = info["bounds"]
    assert lo[0] <= hi[0] and lo[1] <= hi[1] and lo[2] <= hi[2]


def test_stl_triangles_stream():
    data = FIXTURE.read_bytes()
    tris = list(stl_triangles(data))
    assert len(tris) == 312
    v0, v1, v2 = tris[0]
    assert len(v0) == 3 and len(v1) == 3 and len(v2) == 3


def test_parse_stl_ascii():
    body = (
        "solid demo\n"
        "facet normal 0 0 1\n"
        "  outer loop\n"
        "    vertex 0 0 0\n    vertex 1 0 0\n    vertex 0 1 0\n"
        "  endloop\n"
        "endfacet\n"
        "endsolid demo\n"
    )
    info = parse_stl(body.encode())
    assert info["triangles"] == 1
    assert info["format"] == "ascii"
    tris = list(stl_triangles(body.encode()))
    assert tris[0][0] == [0.0, 0.0, 0.0]


def test_parse_stl_garbage():
    assert parse_stl(b"not a stl")["triangles"] == 0
