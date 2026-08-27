"""分类双维度测试：电力领域（平级）× 设备类型（全局清单），均可增删。"""
import pytest

from egrid.models import ModelQuery
from egrid.service import ModelService


@pytest.fixture()
def service(tmp_path):
    return ModelService(
        db_path=str(tmp_path / "t.db"),
        storage_dir=str(tmp_path / "files"),
    )


def test_category_domains(service):
    roots = service.list_categories()
    assert {"变电", "输电", "电缆", "配电"} <= set(roots)
    service.add_category("直流")
    assert "直流" in service.list_categories()
    with pytest.raises(ValueError):
        service.add_category("直流")


def test_equipment_types(service):
    assert "杆塔" in service.list_equipment_types()   # 预置
    service.add_equipment_type("避雷器")
    assert "避雷器" in service.list_equipment_types()
    with pytest.raises(ValueError):
        service.add_equipment_type("避雷器")


def test_delete_category(service):
    service.create_model({"name": "塔A", "category": "输电"})
    service.add_category("直流")
    service.delete_category("直流")
    assert "直流" not in service.list_categories()
    # 删除被模型使用的领域 → 模型 category 清空
    service.delete_category("输电")
    got = service.list_models(ModelQuery(category="输电"))
    assert got == []


def test_delete_equipment_type(service):
    service.create_model({"name": "塔B", "subcategory": "杆塔"})
    service.delete_equipment_type("杆塔")
    assert "杆塔" not in service.list_equipment_types()
    got = service.list_models(ModelQuery(subcategory="杆塔"))
    assert got == []          # 模型 subcategory 引用被清空


def test_import_registers_equipment_type(service, tmp_path):
    """导入 GIM 时新设备类型自动注册。"""
    import struct
    import py7zr

    def make_stl(tris):
        out = b"\x00" * 80 + struct.pack("<I", len(tris))
        for t in tris:
            out += struct.pack("<12fH", 0, 0, 1, *t[0], *t[1], *t[2], 0)
        return out

    files = {
        "Cbm/a.cbm": "ENTITYNAME=Device\nOBJECTMODELPOINTER=b.dev\n".encode(),
        "Dev/b.dev": ("DEVICETYPE=ARRESTER\nSYMBOLNAME=避雷器\n"
                      "SOLIDMODELS.NUM=0\n").encode(),
    }
    pkg = tmp_path / "arrester.gim"
    with py7zr.SevenZipFile(pkg, "w") as z:
        for name, content in files.items():
            z.writestr(content, name)
    created = service.import_gim_package(str(pkg))
    assert created[0].subcategory == "避雷器"
    assert "避雷器" in service.list_equipment_types()
