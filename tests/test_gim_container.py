"""GIM 存储域解包与通用行格式解析测试。"""
from pathlib import Path

import pytest

from egrid.gim.container import unpack_store
from egrid.gim.records import parse_fam_text, parse_kv_lines, parse_matrix
from egrid.gim.header import parse_header

FIXTURE = Path(__file__).parent / "fixtures" / "tower_2f4sdj.gim"


def test_unpack_store():
    data = FIXTURE.read_bytes()
    header = parse_header(data)
    files = unpack_store(data, header.store_offset)
    assert any(n.endswith("project.cbm") or n.endswith(".cbm") for n in files)
    assert any(n.endswith(".fam") for n in files)
    assert any(n.endswith(".mod") for n in files)
    cbm = next(v for k, v in files.items() if k.endswith(".cbm"))
    assert "ENTITYNAME" in cbm.decode("utf-8", errors="replace")


def test_parse_kv_lines():
    text = "ENTITYNAME = Device\r\nOBJECTMODELPOINTER=abc.dev\r\nTRANSFORMMATRIX = 1,0,0,0\r\n"
    records = parse_kv_lines(text)
    assert records == [
        ("ENTITYNAME", "Device"),
        ("OBJECTMODELPOINTER", "abc.dev"),
        ("TRANSFORMMATRIX", "1,0,0,0"),
    ]


def test_parse_fam_text_sections():
    text = (
        "[设计参数]\n"
        "VOLTAGE=电压等级=220kV\n"
        "\n"
        "TYPE=塔型=2F4-SDJ\n"
        "[产品参数]\n"
        "WEIGHT=重量=1200\n"
    )
    attrs = parse_fam_text(text)
    assert len(attrs) == 3
    assert attrs[0].key == "VOLTAGE"
    assert attrs[0].description == "电压等级"
    assert attrs[0].value == "220kV"
    assert attrs[0].category == "design"
    assert attrs[1].key == "TYPE"
    assert attrs[2].category == "product"


def test_parse_matrix():
    m = parse_matrix("1,0,0,322000.07,0,1,0,-42000.08,0,0,1,41000.0,0,0,0,1")
    assert len(m) == 16
    assert m[3] == 322000.07
    assert m[7] == -42000.08
    assert m[11] == 41000.0


def test_parse_transform_layout_autodetect():
    """厂商矩阵为 [R; t] 列分块按行展开（平移在 12,13,14，3x3 与行主序同序）。

    parse_transform 原样返回（不转置——组合后由 transpose_matrix 统一转置一次，
    对齐参考实现 XGIMDataGenerator：PHM/DEV 层原样右乘，CBM 层 TransposeSelf）。
    """
    from egrid.gim.records import parse_transform, transpose_matrix
    raw = "-0.916048,0.4010694659,0,0,0,0,-1,0,-0.4010694659,-0.9160476426,0,0,4,0.875,36,1"
    m = parse_transform(raw)
    # 原样：平移仍在 12/13/14
    assert m[12] == pytest.approx(4.0)
    assert m[13] == pytest.approx(0.875)
    assert m[14] == pytest.approx(36.0)
    # 整体转置一次后：平移到 3/7/11，3x3 转置（对齐 TransposeSelf）
    t = transpose_matrix(m)
    assert t[3] == pytest.approx(4.0)
    assert t[7] == pytest.approx(0.875)
    assert t[11] == pytest.approx(36.0)
    assert t[12] == t[13] == t[14] == 0.0
    assert t[15] == 1.0

    # 行主序样本（平移在 3,7,11）原样返回
    m2 = parse_transform("1,0,0,10,0,1,0,20,0,0,1,30,0,0,0,1")
    assert m2[3] == 10.0 and m2[7] == 20.0 and m2[11] == 30.0
