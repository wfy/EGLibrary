import pytest

from egrid.models import ModelAsset, ModelQuery, ModelVersion
from egrid.storage import ModelRepository


@pytest.fixture()
def repo():
    r = ModelRepository(":memory:")
    yield r
    r.close()


def test_create_and_get(repo):
    asset = repo.create_model(ModelAsset(name="隔离开关", voltage_level="220kV"))
    got = repo.get_model(asset.id)
    assert got is not None
    assert got.name == "隔离开关"


def test_update(repo):
    asset = repo.create_model(ModelAsset(name="旧名称"))
    asset.name = "新名称"
    updated = repo.update_model(asset)
    assert updated is not None
    assert repo.get_model(asset.id).name == "新名称"


def test_delete(repo):
    asset = repo.create_model(ModelAsset(name="待删除"))
    assert repo.delete_model(asset.id) is True
    assert repo.get_model(asset.id) is None


def test_list_filter(repo):
    repo.create_model(ModelAsset(name="变压器", model_type="device", voltage_level="110kV"))
    repo.create_model(ModelAsset(name="电缆", model_type="material", voltage_level="10kV"))
    result = repo.list_models(ModelQuery(voltage_level="110kV"))
    assert len(result) == 1
    result = repo.list_models(ModelQuery(model_type="material"))
    assert len(result) == 1


def test_version(repo):
    asset = repo.create_model(ModelAsset(name="带版本"))
    repo.add_version(asset.id, ModelVersion(version="v1", note="初始"))
    versions = repo.list_versions(asset.id)
    assert len(versions) == 1
    assert versions[0].version == "v1"
