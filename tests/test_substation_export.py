"""变电参数化图元多格式导出测试 (OBJ, STL, LAS, TXT)。"""
from pathlib import Path
import pytest
from egrid.gim import parse_gim
from egrid.exporters import (
    export_obj_mesh,
    export_stl_bytes,
    export_las_bytes,
    export_txt_pointcloud,
)
from egrid.models import ModelAsset, Geometry, Primitive, PrimitiveType

BYQ_FIXTURE = Path(__file__).parent / "fixtures" / "byq_transformer.gim"


def test_export_primitives_to_obj():
    model = ModelAsset(
        name="测试变压器",
        category="变电",
        subcategory="变压器",
        voltage_level="220kV",
        geometry=Geometry(primitives=[
            Primitive(type=PrimitiveType.BOX, params={"depth": 1000, "width": 500, "height": 800}, position=[0, 0, 0]),
            Primitive(type=PrimitiveType.CYLINDER, params={"radius": 100, "height": 600}, position=[200, 200, 800]),
            Primitive(type=PrimitiveType.SPHERE, params={"radius": 150}, position=[200, 200, 1400]),
            Primitive(type=PrimitiveType.CONE, params={"radius": 120, "radius2": 80, "height": 300}, position=[-200, -200, 800]),
            Primitive(type=PrimitiveType.TORUS, params={"major_radius": 300, "minor_radius": 50}, position=[0, 0, 1200]),
        ])
    )
    obj_text = export_obj_mesh(model)
    assert "v " in obj_text
    assert "f " in obj_text
    assert obj_text.count("f ") >= 50


def test_export_primitives_to_stl():
    model = ModelAsset(
        name="测试变压器",
        geometry=Geometry(primitives=[
            Primitive(type=PrimitiveType.BOX, params={"depth": 1000, "width": 500, "height": 800}),
            Primitive(type=PrimitiveType.CYLINDER, params={"radius": 100, "height": 600}),
        ])
    )
    stl_data = export_stl_bytes(model)
    assert len(stl_data) > 84
    assert stl_data[:80].startswith(b"EGLibrary STL Export")


def test_byq_gim_export_obj_and_stl():
    assets = parse_gim(BYQ_FIXTURE.read_bytes())
    asset = assets[0]
    obj_text = export_obj_mesh(asset)
    assert len(obj_text) > 10000
    assert "f " in obj_text

    stl_data = export_stl_bytes(asset)
    assert len(stl_data) > 10000


def test_byq_gim_export_pointcloud():
    from egrid.render import sample_model_pointcloud
    assets = parse_gim(BYQ_FIXTURE.read_bytes())
    asset = assets[0]
    sample = sample_model_pointcloud(asset, count=1000, seed=42)
    assert len(sample.points) == 1000
    assert len(sample.labels) == 1000
    txt = export_txt_pointcloud(sample.points, sample.labels)
    assert len(txt.splitlines()) >= 1001
    las = export_las_bytes(sample.points, sample.labels)
    assert len(las) > 227
