"""GIM 存储域解包与通用行格式解析测试。"""
from pathlib import Path

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
    assert m[13] == -42000.08
