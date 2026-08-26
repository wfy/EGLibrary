"""来源溯源 + 子分类体系测试。"""
import pytest

from egrid.models import ModelAsset
from egrid.service import ModelService


@pytest.fixture()
def service(tmp_path):
    return ModelService(
        db_path=str(tmp_path / "t.db"),
        storage_dir=str(tmp_path / "files"),
    )


def test_asset_source_fields():
    a = ModelAsset(name="塔", source="gim", subcategory="杆塔",
                   origin={"软件": "道亨三维设计系统", "组织单位": "绍兴院"})
    assert a.source == "gim"
    assert a.subcategory == "杆塔"
    assert a.origin["组织单位"] == "绍兴院"
    assert ModelAsset(name="x").source == "manual"


def test_source_roundtrip(service):
    a = service.create_model({
        "name": "2F4-SDJ", "source": "gim", "subcategory": "杆塔",
        "origin": {"原文件名": "x.gim", "软件名称": "道亨"},
    })
    got = service.get_model(a.id)
    assert got.source == "gim"
    assert got.subcategory == "杆塔"
    assert got.origin["软件名称"] == "道亨"


def test_category_tree(service):
    # 预置 4 大类；添加子分类挂到输电
    roots = service.list_categories()
    assert {"变电", "输电", "电缆", "配电"} <= {c["name"] for c in roots}

    service.add_category("杆塔", parent="输电")
    service.add_category("导线", parent="输电")
    with pytest.raises(ValueError):
        service.add_category("杆塔", parent="输电")

    tree = service.list_category_tree()
    shudian = next(c for c in tree if c["name"] == "输电")
    assert {"杆塔", "导线"} <= {c["name"] for c in shudian["children"]}


def test_list_models_filter_subcategory(service):
    service.create_model({"name": "塔A", "category": "输电", "subcategory": "杆塔"})
    service.create_model({"name": "线B", "category": "输电", "subcategory": "导线"})
    from egrid.models import ModelQuery
    got = service.list_models(ModelQuery(subcategory="杆塔"))
    assert [m.name for m in got] == ["塔A"]
