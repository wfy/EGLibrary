"""通用行格式解析：cbm/dev/phm 的 "KEY=值" 与 fam 的 "[段] + EN=中文=值"。

依据 Q/GDW 11809 附录A.6.x：文件采用"标识符=值"行存储；
fam 属性行第一项为英文属性项、第二项为中文描述、第三项为属性值。
"""
from __future__ import annotations

from typing import NamedTuple

SECTION_CATEGORY = {
    "设计参数": "design",
    "设计冻结参数": "design_frozen",
    "产品参数": "product",
    "施工参数": "construction",
    "测试参数": "test",
    "运检参数": "operation",
}


class FamAttr(NamedTuple):
    category: str
    key: str
    description: str
    value: str


def parse_kv_lines(text: str) -> list:
    """解析 "KEY = value" 行序列，返回 [(key, value)]，忽略空行与注释。"""
    records = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or line.startswith("//") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        records.append((key.strip(), value.strip()))
    return records


def parse_kv_dict(text: str) -> dict:
    """同 parse_kv_lines，但返回 dict（同 key 后者覆盖，适合单值文件）。"""
    return dict(parse_kv_lines(text))


def parse_fam_text(text: str) -> list:
    """解析 fam 属性文本，返回 FamAttr 列表。"""
    attrs = []
    category = "design"
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            category = SECTION_CATEGORY.get(line[1:-1].strip(), "design")
            continue
        parts = line.split("=")
        if len(parts) >= 3:
            attrs.append(FamAttr(
                category=category,
                key=parts[0].strip(),
                description=parts[1].strip(),
                value="=".join(parts[2:]).strip(),
            ))
        elif len(parts) == 2:
            attrs.append(FamAttr(category, parts[0].strip(), "", parts[1].strip()))
    return attrs


def parse_matrix(text: str) -> list:
    """解析 4x4 齐次变换矩阵（按行存储的 16 个逗号分隔数值）。"""
    return [float(x) for x in text.replace(",", " ").split()]


def matrix_translation(text_or_values) -> list:
    """取变换矩阵的平移分量 (M14, M24, M34)。"""
    m = text_or_values if isinstance(text_or_values, list) else parse_matrix(text_or_values)
    return [m[3], m[7], m[11]]
