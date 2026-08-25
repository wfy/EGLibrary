"""GIM 容器头解析。

依据 Q/GDW 11809—2018 附录A.5：
- 文件标识 16 字节：GIMPKGS(变电) / GIMPKGT(线路) / GIMPKEC(电缆)
- 其后依次为文件名称/设计者/组织单位/软件名称/创建时间/版本号/存储域大小
- A.5.2 存储区域为连续字节，实测为标准 7z 流（37 7A BC AF 27 1C）

厂商实现与规范文字布局存在出入，故字段解析采用
"固定偏移(标识/名称) + 特征定位(7z签名) + 启发式提取(时间/单位/软件)" 的稳健策略。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SEVENZIP_MAGIC = b"\x37\x7A\xBC\xAF\x27\x1C"

# 文件标识前缀 → 工程类型
KIND_BY_MAGIC = {
    b"GIMPKGS": "substation",   # 变电工程
    b"GIMPKGT": "line",         # 架空输电线路工程
    b"GIMPKEC": "cable",        # 电缆线路工程
}

_NAME_OFFSET = 16
_TIME_RE = re.compile(rb"\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?")
# GBK 汉字区（连续双字节），用于提取头部中文元数据
_CJK_RE = re.compile(rb"(?:[\xB0-\xF7][\xA1-\xFE]){2,}")


@dataclass
class GimHeader:
    """GIM 容器头元数据。"""
    kind: str                       # substation / line / cable
    name: str = ""                  # 文件名称
    organization: str = ""          # 组织单位（启发式提取）
    software: str = ""              # 生成软件（启发式提取）
    created_at: str = ""            # 创建时间
    store_offset: int = -1          # 7z 存储域起点
    extra_strings: list = field(default_factory=list)  # 头部其他可读字符串


def is_gim(data: bytes) -> bool:
    """判断数据是否为真实 GIM 专有容器。"""
    return any(data.startswith(m) for m in KIND_BY_MAGIC)


def _decode(raw: bytes) -> str:
    return raw.decode("gbk", errors="replace").strip("\x00 ").strip()


def _read_cstring(data: bytes, offset: int, limit: int = 256) -> str:
    end = data.find(b"\x00", offset, offset + limit)
    end = end if end >= 0 else min(offset + limit, len(data))
    return _decode(data[offset:end])


def _extract_cjk_strings(head: bytes) -> list:
    """提取头部 GBK 中文串（启发式，用于组织单位/软件名称）。"""
    out = []
    for m in _CJK_RE.finditer(head):
        text = m.group().decode("gbk", errors="replace")
        if len(text) >= 2:
            out.append((m.start(), text))
    return out


def parse_header(data: bytes) -> GimHeader:
    if not is_gim(data):
        raise ValueError("不是 GIM 专有容器（文件标识不符）")

    kind = next(k for m, k in KIND_BY_MAGIC.items() if data.startswith(m))
    store_offset = data.find(SEVENZIP_MAGIC)
    if store_offset < 0:
        raise ValueError("未找到 7z 存储域（文件可能损坏）")

    header = GimHeader(
        kind=kind,
        name=_read_cstring(data, _NAME_OFFSET),
        store_offset=store_offset,
    )

    head = data[:store_offset]
    m = _TIME_RE.search(head)
    if m:
        header.created_at = m.group().decode("ascii")

    strings = _extract_cjk_strings(head)
    header.extra_strings = [s for _, s in strings]
    for _, text in strings:
        if "系统" in text or "设计" in text or "软件" in text:
            header.software = text
            break
    # 组织单位取其余串中最长者（堆数据误报通常较短）
    rest = [t for _, t in strings if t != header.software]
    if rest:
        header.organization = max(rest, key=len)
    return header
