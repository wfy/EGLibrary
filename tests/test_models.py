from egrid.models import Geometry, ModelAsset, Primitive, PrimitiveType


def test_model_defaults():
    asset = ModelAsset(name="主变")
    assert asset.id
    assert asset.model_type.value == "device"
    assert asset.level == 4
    assert asset.geometry.primitives == []


def test_primitive_serialization():
    prim = Primitive(
        name="套管",
        type=PrimitiveType.CYLINDER,
        params={"radius": 50, "height": 300},
        position=[10, 20, 30],
        color="#8B5A2B",
    )
    asset = ModelAsset(name="套管模型", geometry=Geometry(primitives=[prim]))
    data = asset.model_dump(mode="json")
    restored = ModelAsset.model_validate(data)
    assert restored.geometry.primitives[0].params["radius"] == 50
