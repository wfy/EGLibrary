"""变电 XML 图元解析测试：扩展图元（套管/端子排/拉伸体/截锥）+ 变压器集成。"""
from pathlib import Path

from egrid.gim import parse_gim
from egrid.gim.parsers.mod import parse_mod
from egrid.models import PrimitiveType

BYQ_FIXTURE = Path(__file__).parent / "fixtures" / "byq_transformer.gim"

XML = """<?xml version="1.0" encoding="utf-8"?>
<Device><Entities>
<Entity ID="1" Type="simple"><Cylinder R="10" H="5"/><Color R="1" G="2" B="3" A="0"/><TransformMatrix Value="1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1"/></Entity>
<Entity ID="2" Type="simple"><PorcelainBushing R1="100" R2="80" R="30" H="350" N="10"/><TransformMatrix Value="1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1"/></Entity>
<Entity ID="3" Type="simple"><TerminalBlock L="180" W="160" T="20"/><TransformMatrix Value="1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1"/></Entity>
<Entity ID="4" Type="simple"><StretchedBody L="5" Normal="0,0,1" Array="0,0,0;10,0,0;10,4,0;0,4,0"/><TransformMatrix Value="1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1"/></Entity>
<Entity ID="5" Type="simple"><TruncatedCone BR="50" TR="20" H="30"/><TransformMatrix Value="1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1"/></Entity>
</Entities></Device>"""


def test_extended_primitives_parsed():
    prims = parse_mod(XML)
    assert len(prims) == 5
    by_name = {p.name: p for p in prims}

    bush = by_name["PorcelainBushing"]
    assert bush.type == PrimitiveType.CYLINDER
    assert bush.params == {"radius": 100.0, "height": 350.0}

    block = by_name["TerminalBlock"]
    assert block.type == PrimitiveType.BOX
    assert block.params == {"depth": 180.0, "width": 160.0, "height": 20.0}

    stretch = by_name["StretchedBody"]
    assert stretch.type == PrimitiveType.BOX
    assert stretch.params == {"depth": 5.0, "width": 10.0, "height": 4.0}

    cone = by_name["TruncatedCone"]
    assert cone.type == PrimitiveType.CONE
    assert cone.params == {"radius": 50.0, "radius2": 20.0, "height": 30.0}


def test_byq_transformer_geometry_renders():
    """真实变电设备（山西院变压器）：全图元解析，几何可渲染。"""
    assets = parse_gim(BYQ_FIXTURE.read_bytes())
    assert len(assets) == 1
    asset = assets[0]
    assert "变压器" in asset.name or asset.attributes
    prims = asset.geometry.primitives
    # 实测 440 图元（基础 307 + 扩展 133），至少应覆盖扩展图元
    assert len(prims) >= 400
    types = {p.type for p in prims}
    assert PrimitiveType.CYLINDER in types
    assert PrimitiveType.BOX in types
    assert PrimitiveType.CONE in types


def test_byq_dev_subdevices_are_device_refs():
    """变压器根 dev 用 SUBDEVICEn 引用 28 个部件（与 SOLIDMODELn 并列的设备引用键）。"""
    from egrid.gim import parse_header
    from egrid.gim.assembler import _records_cached
    from egrid.gim.container import unpack_store
    data = BYQ_FIXTURE.read_bytes()
    header = parse_header(data)
    files = unpack_store(data, header.store_offset)
    cbm = next(n for n in files if n.lower().endswith(".cbm"))
    records = _records_cached(files, cbm)
    dev_path = "DEV/" + records["OBJECTMODELPOINTER"]
    dev = _records_cached(files, dev_path)
    sub_refs = [v for k, v in dev.items() if k.startswith("SUBDEVICE") and v.endswith(".dev")]
    assert len(sub_refs) >= 20