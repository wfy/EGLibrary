import zipfile
from pathlib import Path

import pytest

from egrid.models import Geometry, ModelAsset, ModelQuery, Primitive, PrimitiveType
from egrid.render import render_model_svg, sample_model_pointcloud
from egrid.service import ModelService

GIM_FIXTURE = Path(__file__).parent / "fixtures" / "tower_2f4sdj.gim"


@pytest.fixture()
def service(tmp_path):
    return ModelService(
        db_path=str(tmp_path / "test.db"),
        storage_dir=str(tmp_path / "files"),
    )


def test_category_filter(service):
    service.create_model({"name": "主变", "category": "变电"})
    service.create_model({"name": "导线", "category": "输电"})

    models = service.list_models(ModelQuery(category="变电"))
    assert [m.name for m in models] == ["主变"]

    assert service.list_category_tree() and len(service.list_categories()) == 4
    service.add_category("直流", parent="输电")
    with pytest.raises(ValueError):
        service.add_category("直流", parent="输电")


def test_crud(service):
    asset = service.create_model({"name": "断路器", "voltage_level": "220kV"})
    assert service.get_model(asset.id) is not None
    updated = service.update_model(asset.id, {"description": "更新描述"})
    assert updated.description == "更新描述"
    assert service.delete_model(asset.id) is True


def test_version(service):
    asset = service.create_model({"name": "互感器"})
    version = service.add_version(asset.id, "初始版本")
    assert version is not None
    assert len(service.list_versions(asset.id)) == 1


def test_import_export_roundtrip(service, tmp_path):
    # 构造一个简化 GIM ZIP
    pkg = tmp_path / "demo.gim"
    with zipfile.ZipFile(pkg, "w") as zf:
        zf.writestr("MOD/demo.mod", "parametric box")
        zf.writestr("FAM/demo.fam", "voltageLevel=220kV\nname=Demo")
        zf.writestr("manifest.json", '{"name":"演示模型","voltage_level":"220kV"}')

    created = service.import_gim_package(str(pkg), voltage_level="220kV")
    assert len(created) == 1
    model = created[0]
    assert model.name == "演示模型"
    assert model.voltage_level == "220kV"
    assert any(f.kind.value == "mod" for f in model.files)

    out = tmp_path / "out.gim"
    out_path = service.export_gim_package(model.id, str(out))
    assert out_path.endswith(".gim")
    with zipfile.ZipFile(out_path) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert any(n.startswith("MOD/") for n in names)


def test_import_real_gim_parses_attributes_and_geometry(service, tmp_path):
    pkg = tmp_path / "2F4-SDJ.gim"
    pkg.write_bytes(GIM_FIXTURE.read_bytes())

    created = service.import_gim_package(str(pkg))
    assert len(created) == 1
    m = created[0]
    assert m.name == "2F4-SDJ"
    assert m.voltage_level == "220kV"
    assert m.code == "2F4-SDJ"

    keys = {a.key: a for a in m.attributes}
    assert keys["TOWERTYPE"].value == "终端"
    assert keys["CONDUCTOR"].value == "LGJ-630/45"

    assert len(m.geometry.primitives) == 1132
    assert m.geometry.primitives[0].type.value == "line"

    # 原始包已存档
    assert m.files[0].kind.value == "gim"

    # 重新读取持久化后数据完整
    loaded = service.get_model(m.id)
    assert loaded is not None
    assert len(loaded.geometry.primitives) == 1132


def test_render_and_pointcloud(service):
    asset = service.create_model(ModelAsset(
        name="绝缘子串",
        geometry=Geometry(primitives=[
            Primitive(name="绝缘子", type=PrimitiveType.CYLINDER, params={"radius": 30, "height": 200}),
            Primitive(name="导体", type=PrimitiveType.LINE, params={"start": [0, 0, 0], "end": [500, 0, 0]}),
        ]),
    ))
    svg = render_model_svg(asset)
    assert svg.startswith("<svg")
    sample = sample_model_pointcloud(asset, count=200, seed=42)
    assert sample.count > 0
    assert len(sample.points) == len(sample.labels)
