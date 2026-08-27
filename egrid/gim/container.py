"""GIM 存储域解包：头部之后的连续区域为标准 7z 流（Q/GDW 11809 附录A.5.2）。"""
from __future__ import annotations

import io
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import py7zr

from .header import SEVENZIP_MAGIC


def _read_files(root: str) -> dict:
    """并行读回解包目录的文件（20609 个小文件场景 IO 密集，线程显著提速）。"""
    paths = [p for p in Path(root).rglob("*") if p.is_file()]
    files = {}
    workers = min(32, (os.cpu_count() or 4) * 4)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for p, blob in zip(paths, pool.map(lambda p: p.read_bytes(), paths)):
            files[p.relative_to(root).as_posix()] = blob
    return files


def unpack_store(data: bytes, store_offset: int) -> dict:
    """解包 7z 存储域，返回 {相对路径: bytes}（仅文件，不含目录项）。"""
    if data[store_offset:store_offset + len(SEVENZIP_MAGIC)] != SEVENZIP_MAGIC:
        raise ValueError(f"偏移 {store_offset} 处不是 7z 存储域")
    with tempfile.TemporaryDirectory(prefix="egrid_gim_") as tmp:
        with py7zr.SevenZipFile(io.BytesIO(data[store_offset:])) as z:
            z.extractall(tmp)
        return _read_files(tmp)
