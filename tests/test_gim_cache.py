"""组装缓存回归测试：同一包内重复调用必须命中缓存，禁止重复解析。"""
from pathlib import Path

from egrid.gim import assembler

FIXTURE = Path(__file__).parent / "fixtures" / "sample.stl"


def test_path_index_same_files_object_hits_cache():
    """同一 files 对象重复构建索引必须返回同一对象（原 is id() 判断失效 bug）。"""
    files = {"a.cbm": b"", "b/dev/dev1.dev": b""}
    i1 = assembler._path_index(files)
    i2 = assembler._path_index(files)
    assert i1 is i2


def test_path_index_new_files_object_rebuilds():
    """不同 files 对象必须重新构建索引，不得返回陈旧缓存。"""
    files1 = {"a.cbm": b""}
    files2 = {"b.cbm": b""}
    i1 = assembler._path_index(files1)
    i2 = assembler._path_index(files2)
    assert i1 is not i2
    assert "b.cbm" in i2["exact"]


def test_records_cache_same_files_object_hits():
    files = {"x.cbm": b"KEY=1\n"}
    r1 = assembler._records_cached(files, "x.cbm")
    r2 = assembler._records_cached(files, "x.cbm")
    assert r1 is r2


def test_records_cache_isolated_between_files_objects():
    files1 = {"x.cbm": b"KEY=1\n"}
    files2 = {"x.cbm": b"KEY=2\n"}
    assert assembler._records_cached(files1, "x.cbm")["KEY"] == "1"
    assert assembler._records_cached(files2, "x.cbm")["KEY"] == "2"


def test_attributes_cache_same_files_object_hits():
    files = {"x.fam": "[产品参数]\nNAME=中文=值\n".encode("utf-8")}
    a1 = assembler._attributes_cached(files, "x.fam")
    a2 = assembler._attributes_cached(files, "x.fam")
    assert a1 is a2


def test_stl_stats_cache_same_files_object_hits():
    blob = FIXTURE.read_bytes()
    files = {"x.stl": blob}
    s1 = assembler._stl_stats(files, "x.stl")
    s2 = assembler._stl_stats(files, "x.stl")
    assert s1 is s2


def test_stl_stats_cache_isolated_between_files_objects():
    blob = FIXTURE.read_bytes()
    files1 = {"x.stl": blob}
    files2 = {"x.stl": blob}
    s1 = assembler._stl_stats(files1, "x.stl")
    s2 = assembler._stl_stats(files2, "x.stl")
    assert s1 is not s2