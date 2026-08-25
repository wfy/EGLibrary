"""GIM 存储域解包：头部之后的连续区域为标准 7z 流（Q/GDW 11809 附录A.5.2）。"""
from __future__ import annotations

import io
import tempfile
from pathlib import Path

import py7zr

from .header import SEVENZIP_MAGIC


def unpack_store(data: bytes, store_offset: int) -> dict:
    """解包 7z 存储域，返回 {相对路径: bytes}（仅文件，不含目录项）。"""
    if data[store_offset:store_offset + len(SEVENZIP_MAGIC)] != SEVENZIP_MAGIC:
        raise ValueError(f"偏移 {store_offset} 处不是 7z 存储域")
    files = {}
    with tempfile.TemporaryDirectory(prefix="egrid_gim_") as tmp:
        with py7zr.SevenZipFile(io.BytesIO(data[store_offset:])) as z:
            z.extractall(tmp)
        for p in Path(tmp).rglob("*"):
            if p.is_file():
                files[p.relative_to(tmp).as_posix()] = p.read_bytes()
    return files
