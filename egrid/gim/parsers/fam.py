"""fam 属性文件解析（Q/GDW 11809 附录A.6.2-h / A.7.2-g）。

属性行格式：EN=中文描述=值；六大类以 [段名] 划分。
"""
from __future__ import annotations

from ...models import ModelAttribute
from ..records import parse_fam_text

# 常用工程级属性 → ModelAsset 字段的映射
ASSET_FIELD_KEYS = {
    "VOLTAGE": "voltage_level",
    "VOLTAGECLASS": "voltage_level",
}


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
    """从属性列表提取模型主记录字段（电压等级等）。"""
    fields = {}
    for a in attrs:
        field_name = ASSET_FIELD_KEYS.get(a.key)
        if field_name and a.value and field_name not in fields:
            fields[field_name] = a.value
    return fields
