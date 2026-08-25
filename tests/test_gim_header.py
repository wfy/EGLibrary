"""GIM 容器头解析测试（Q/GDW 11809 附录A.5）。"""
from pathlib import Path

from egrid.gim.header import GimHeader, is_gim, parse_header

FIXTURE = Path(__file__).parent / "fixtures" / "tower_2f4sdj.gim"


def test_is_gim():
    data = FIXTURE.read_bytes()
    assert is_gim(data)
    assert not is_gim(b"PK\x03\x04 not a gim")
    assert not is_gim(b"short")


def test_parse_header_line_gim():
    data = FIXTURE.read_bytes()
    h = parse_header(data)
    assert isinstance(h, GimHeader)
    assert h.kind == "line"          # GIMPKGT = 线路工程
    assert h.name == "2F4-SDJ"
    assert h.store_offset == 776
    assert "2019-08-23" in h.created_at


def test_parse_header_substation_magic():
    data = b"GIMPKGS\x00" + b"\x00" * 800 + b"\x37\x7A\xBC\xAF\x27\x1C" + b"\x00" * 16
    h = parse_header(data)
    assert h.kind == "substation"
    assert h.store_offset == len(data) - 22


def test_parse_header_cable_magic():
    data = b"GIMPKEC\x00" + b"\x00" * 800 + b"\x37\x7A\xBC\xAF\x27\x1C" + b"\x00" * 16
    h = parse_header(data)
    assert h.kind == "cable"
