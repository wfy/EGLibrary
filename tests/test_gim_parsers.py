"""GIM 文件解析器测试：fam 属性 → ModelAttribute，mod 几何 → Primitive。"""
from egrid.gim.parsers.fam import parse_attributes
from egrid.gim.parsers.mod import parse_mod, parse_mod_tower

FAM_SAMPLE = """[设计参数]
VOLTAGE=电压等级=220kV

TYPE=塔型=2F4-SDJ
TOWERTYPE=杆塔类型=终端
[产品参数]
WEIGHT=重量=1200
"""

TOWER_MOD_SAMPLE = """HNum,1
H,15000,Body1,Leg1
Body1
HBody1,26700
P,1,1100.0,-1100.0,47000.0
P,2,-1100.0,-1100.0,47000.0
P,3,1100.0,1100.0,47000.0
P,4,-1100.0,1100.0,47000.0
Leg1
HLeg1,3000,5000
P,5,-301.71,-301.71,1400.00
P,6,301.71,-301.71,1400.00
r,1,2
r,3,4,L20x3,Q235,0,0,0,0,1,0
r,5,6
G,C,前导1,10.00,10.00,15.00
"""

SUBSTATION_MOD_SAMPLE = """<Entity ID="1" Type="simple" Visible="false">
<Cuboid L="100" W="200" H="300" />
<TransformMatrix Value="1,0,0,10,0,1,0,20,0,0,1,30,0,0,0,1" />
</Entity>
<Entity ID="2" Type="simple" Visible="true">
<Cylinder R="50" H="200" />
<Color R="0" G="100" B="255" A="0"/>
<TransformMatrix Value="1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1" />
</Entity>
<Entity ID="3" Type="boolean" Visible="true">
<Boolean Type="Difference" Entity1="1" Entity2="2" />
<Color R="255" G="0" B="0" A="0"/>
<TransformMatrix Value="1,0,0,5,0,1,0,6,0,0,1,7,0,0,0,1" />
</Entity>
"""


def test_parse_mod_boolean_structure():
    """Boolean 节点解析：类型/引用/颜色/变换完整记录。"""
    prims = parse_mod(SUBSTATION_MOD_SAMPLE)
    bools = [p for p in prims if p.params.get("op")]
    assert len(bools) == 1
    b = bools[0]
    assert b.params["op"] == "Difference"
    assert b.params["entity1"] == "1"
    assert b.params["entity2"] == "2"
    assert b.color == "#FF0000"
    assert b.position == [5.0, 6.0, 7.0]
    # 参与图元仍保留（并集近似渲染）
    assert any(p.type.value == "box" for p in prims)
    assert any(p.type.value == "cylinder" for p in prims)


def test_parse_attributes():
    attrs = parse_attributes(FAM_SAMPLE)
    assert len(attrs) == 4
    a0 = attrs[0]
    assert a0.key == "VOLTAGE"
    assert a0.value == "220kV"
    assert a0.category == "design"
    assert a0.description == "电压等级"
    assert attrs[3].category == "product"
    assert attrs[3].key == "WEIGHT"


def test_parse_mod_tower_lines():
    prims = parse_mod_tower(TOWER_MOD_SAMPLE)
    assert len(prims) == 3
    p0 = prims[0]
    assert p0.type.value == "line"
    assert p0.params["start"] == [1100.0, -1100.0, 47000.0]
    assert p0.params["end"] == [-1100.0, -1100.0, 47000.0]
    assert prims[1].params["start"] == [1100.0, 1100.0, 47000.0]


def test_parse_mod_dispatch():
    assert len(parse_mod(TOWER_MOD_SAMPLE)) == 3
    assert len(parse_mod(SUBSTATION_MOD_SAMPLE)) >= 2


def test_parse_mod_substation_xml():
    prims = parse_mod(SUBSTATION_MOD_SAMPLE)
    box = next(p for p in prims if p.type.value == "box")
    assert box.params == {"width": 200.0, "depth": 100.0, "height": 300.0}
    assert box.position == [10.0, 20.0, 30.0]
    cyl = next(p for p in prims if p.type.value == "cylinder")
    assert cyl.params == {"radius": 50.0, "height": 200.0}
