"""电压等级归一化测试（交流/直流前缀去除 + 单位统一）。"""
import pytest

from egrid.gim.header import category_for_gim_kind
from egrid.gim.parsers.fam import extract_asset_fields, parse_attributes
from egrid.models import ModelAsset, ModelQuery, normalize_voltage_level


@pytest.mark.parametrize("raw,expected", [
    ("AC110kV", "110kV"),
    ("DC110kV", "110kV"),
    ("DC±500kV", "±500kV"),
    (" 110 kV ", "110kV"),
    ("110KV", "110kV"),
    ("220kv", "220kV"),
    ("", ""),
    (None, ""),
])
def test_normalize_voltage_level(raw, expected):
    assert normalize_voltage_level(raw) == expected


def test_model_asset_voltage_normalized():
    asset = ModelAsset(name="测试", voltage_level="AC110kV")
    assert asset.voltage_level == "110kV"


def test_model_query_voltage_normalized():
    q = ModelQuery(voltage_level="DC220kV")
    assert q.voltage_level == "220kV"


@pytest.mark.parametrize("kind,expected", [
    ("substation", "变电"),
    ("line", "输电"),
    ("cable", "电缆"),
    ("unknown", "输电"),
    ("", "输电"),
])
def test_category_for_gim_kind(kind, expected):
    assert category_for_gim_kind(kind) == expected


def test_fam_voltage_priority_designvoltage_first():
    text = "[设计冻结参数]\nDESIGNVOLTAGE=设计电压=AC110kV\nVOLTAGECLASS=电压等级=220kV\nVOLTAGE=电压=35kV\n"
    attrs = parse_attributes(text)
    fields = extract_asset_fields(attrs)
    assert fields["voltage_level"] == "110kV"


def test_fam_voltage_fallback_to_voltageclass():
    text = "[设计参数]\nVOLTAGECLASS=电压等级=DC110kV\n"
    attrs = parse_attributes(text)
    fields = extract_asset_fields(attrs)
    assert fields["voltage_level"] == "110kV"


def test_fam_voltage_keeps_raw_attribute_value():
    """归一化只影响主字段，原始属性值保留用于溯源。"""
    text = "[设计参数]\nVOLTAGE=电压=AC110kV\n"
    attrs = parse_attributes(text)
    assert attrs[0].value == "AC110kV"