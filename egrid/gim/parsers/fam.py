"""fam 属性文件解析（Q/GDW 11809 附录A.6.2-h / A.7.2-g）。

属性行格式：EN=中文描述=值；六大类以 [段名] 划分。
"""
from __future__ import annotations

from ...models import ModelAttribute, normalize_voltage_level
from ..records import parse_fam_text

# 常用工程级属性 → ModelAsset 字段的映射
ASSET_FIELD_KEYS = {
    "VOLTAGE": "voltage_level",
    "VOLTAGECLASS": "voltage_level",
    "DESIGNVOLTAGE": "voltage_level",
}

# 电压取值优先级（工程实测常为 DESIGNVOLTAGE）
_VOLTAGE_KEY_PRIORITY = ("DESIGNVOLTAGE", "VOLTAGECLASS", "VOLTAGE")


def parse_attributes(text: str) -> list:
    """fam 文本 → ModelAttribute 列表。"""
    return [
        ModelAttribute(
            key=a.key,
            value=a.value,
            category=a.category,
            description=a.description,
        )
        for a in parse_fam_text(text)
    ]


def extract_asset_fields(attrs: list) -> dict:
    """从属性列表提取模型主记录字段（电压等级等，按优先级取并归一化）。"""
    fields = {}
    values = {a.key: a.value for a in attrs if a.key in ASSET_FIELD_KEYS and a.value}
    for key in _VOLTAGE_KEY_PRIORITY:
        if key in values:
            fields["voltage_level"] = normalize_voltage_level(values[key])
            break
    return fields
