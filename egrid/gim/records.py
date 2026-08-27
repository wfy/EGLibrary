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


# 4x4 单位矩阵（行主序）
IDENTITY4 = [1.0, 0.0, 0.0, 0.0,
             0.0, 1.0, 0.0, 0.0,
             0.0, 0.0, 1.0, 0.0,
             0.0, 0.0, 0.0, 1.0]


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


def parse_transform(text: str) -> list:
    """解析 GIM 变换矩阵，返回 4 行×4 值原样布局（平移在 12/13/14）。

    对齐参考实现 XGIMDataGenerator：各层矩阵读入原样、右乘组合（A·B），
    组合完成后由 transpose_matrix 统一转置一次（等效 CBM 层 TransposeSelf）。
    """
    return parse_matrix(text)


def transpose_matrix(m: list) -> list:
    """4x4 行主序数组转置。GIM 原生布局（平移在 12/13/14）转置后
    平移落到 3/7/11，可用于标准 M·v 列向量变换。"""
    if len(m) != 16:
        return m
    return [m[c * 4 + r] for r in range(4) for c in range(4)]


def matrix_translation(text_or_values) -> list:
    """取变换矩阵的平移分量 (M14, M24, M34)。"""
    m = text_or_values if isinstance(text_or_values, list) else parse_matrix(text_or_values)
    return [m[3], m[7], m[11]]


def mat4_multiply(a: list, b: list) -> list:
    """4x4 行主序矩阵乘法 A·B（列向量右乘约定：v' = A·(B·v)）。"""
    out = [0.0] * 16
    for r in range(4):
        for c in range(4):
            out[r * 4 + c] = sum(
                a[r * 4 + k] * b[k * 4 + c] for k in range(4)
            )
    return out
