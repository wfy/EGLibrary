"""GIM 组装器：沿 CBM → DEV → PHM → MOD 引用链组装 ModelAsset。

依据 Q/GDW 11809 附录A.6/A.7/A.9：
- 单设备文件（A.9）：CBM 入口 ENTITYNAME=Device，直接走设备链
- 工程文件（A.6/A.7）：project.cbm 为入口，聚合式导入：
  工程 → F1/F2/F3 层级节点 → 塔组逐基建模；导体组/交叉跨越聚合为
  F3 统计属性 + 每耐张段抽样一条导线弧垂曲线（防上万模型爆炸）。
"""
from __future__ import annotations

import math
from pathlib import Path

from ..models import Geometry, ModelAsset, ModelAttribute, Primitive, PrimitiveType
from .container import unpack_store
from .header import GimHeader, category_for_gim_kind, parse_header
from .parsers.fam import extract_asset_fields, parse_attributes
from .parsers.mod import parse_mod, sagcurve_wire
from .records import IDENTITY4, mat4_multiply, parse_kv_dict, parse_transform, transpose_matrix

# 工程电压继承链兜底：自身 → 层级 → 工程根 → 导入参数 → 110kV
DEFAULT_VOLTAGE = "110kV"

# cbm 中表示子级引用的键（工程树，第一版按引用展开）
_CHILD_REF_PREFIXES = ("SUBSYSTEM", "SECTION", "STRAINSECTION", "GROUP", "SUBDEVICE", "STRING", "BASE")

# 绝缘子串逐串建模开关：组装缓存修复 + 解析去重后，逐串工程导入
# 实测 ~11s（原 >15min），已达到 5min 门槛，默认开启
ENABLE_STRING_ASSETS = True

# 子分类（设备类型）映射：DEVICETYPE/GROUPTYPE → 设备类型名
SUBCATEGORY_MAP = {
    "TOWER": "杆塔",
    "WIRE": "导线",
    "GROUNDWIRE": "地线",
    "OPGW": "地线",
    "ADSS": "地线",
    "STRING": "绝缘子串",
    "INSULATOR": "绝缘子串",
    "BASE": "基础",
    "FITTINGS": "金具",
    "CROSS": "交叉跨越",
    "EQUIPMENT": "设备",
    "ARRESTER": "避雷器",
    "COMPOSITE": "设备",
}


def _find_entry(files: dict) -> str:
    """定位 CBM 入口：project.cbm 优先，否则第一个 .cbm。"""
    for name in files:
        if Path(name).name.lower() == "project.cbm":
            return name
    for name in sorted(files):
        if name.lower().endswith(".cbm"):
            return name
    raise ValueError("GIM 包中未找到 CBM 入口文件")


_INDEX_CACHE = {"files": None, "index": None}


def _path_index(files: dict) -> dict:
    """构建 O(1) 路径索引（按 files 对象缓存）：{全路径lower: 原名} + {文件名lower: 原名}。"""
    if _INDEX_CACHE["files"] is files and _INDEX_CACHE["index"] is not None:
        return _INDEX_CACHE["index"]
    exact = {}
    by_base = {}
    for name in files:
        low = name.lower()
        exact[low] = name
        by_base.setdefault(low.split("/")[-1], name)
    index = {"exact": exact, "base": by_base}
    _INDEX_CACHE["files"] = files
    _INDEX_CACHE["index"] = index
    return index


def _resolve(files: dict, base_dir: str, ref: str, index: dict = None) -> str:
    """把 cbm/dev/phm/mod 内的相对引用解析为包内路径（O(1) 索引查找）。"""
    ref = ref.strip().replace("\\", "/")
    if index is None:
        index = _path_index(files)
    exact = index["exact"]
    candidate = f"{base_dir}/{ref}".lower()
    if candidate in exact:
        return exact[candidate]
    base = index["base"].get(ref.lower())
    if base:
        return base
    return f"{base_dir}/{ref}"


def _decode(data: bytes) -> str:
    return data.decode("utf-8-sig", errors="replace")


def _collect_children(files: dict, cbm_path: str) -> list:
    """收集 cbm 的子级 cbm 引用（工程层级树）。"""
    records = _records_cached(files, cbm_path)
    base = Path(cbm_path).parent.as_posix()
    children = []
    for key, value in records.items():
        if key.isupper() and key.startswith(_CHILD_REF_PREFIXES) and value.lower().endswith(".cbm"):
            child = _resolve(files, base, value)
            if child in files:
                children.append(child)
    return children


def _iter_solid_models(records: dict):
    """遍历 SOLIDMODELn 引用（含配对 TRANSFORMMATRIXn），产出 (引用, 矩阵)。"""
    for key, value in records.items():
        ku = key.upper()
        if ku == "SOLIDMODELS.NUM" or not ku.startswith("SOLIDMODEL"):
            continue
        if not (ku == "SOLIDMODEL0" or ku.endswith(tuple("0123456789"))):
            continue
        idx = ku.replace("SOLIDMODEL", "")
        m_raw = records.get(f"TRANSFORMMATRIX{idx}", "")
        m = parse_transform(m_raw) if m_raw else IDENTITY4
        yield value, m


def _iter_device_refs(records: dict):
    """遍历设备几何引用：SOLIDMODELn 与 SUBDEVICEn（均配 TRANSFORMMATRIXn）。

    实测厂商差异：线路塔 dev 用 SOLIDMODEL 链；变电设备（山西院变压器）
    根 dev 用 SUBDEVICEn 引用 28 个部件子 dev。"""
    for key, value in records.items():
        ku = key.upper()
        for prefix in ("SOLIDMODEL", "SUBDEVICE"):
            if ku == f"{prefix}S.NUM" or not ku.startswith(prefix):
                continue
            rest = ku[len(prefix):]
            if rest != "0" and not rest.isdigit():
                continue
            m_raw = records.get(f"TRANSFORMMATRIX{rest}", "")
            m = parse_transform(m_raw) if m_raw else IDENTITY4
            yield value, m
            break


_STL_STATS_CACHE = {"files": None, "cache": {}}


def _stl_stats(files: dict, path: str) -> dict:
    """parse_stl 结果缓存（同一包内同文件只解析一次）。"""
    if _STL_STATS_CACHE["files"] is not files:
        _STL_STATS_CACHE["files"] = files
        _STL_STATS_CACHE["cache"] = {}
    cache = _STL_STATS_CACHE["cache"]
    if path not in cache:
        from .parsers.stl import parse_stl
        cache[path] = parse_stl(files[path])
    return cache[path]


_RECORDS_CACHE = {"files": None, "cache": {}}
_ATTR_CACHE = {"files": None, "cache": {}}


def _copy_attribute(a: ModelAttribute) -> ModelAttribute:
    return ModelAttribute(key=a.key, value=a.value, category=a.category,
                          unit=a.unit, description=a.description)


def _attributes_cached(files: dict, path: str) -> list:
    """fam 属性解析缓存（返回副本，调用方可安全追加）。"""
    if _ATTR_CACHE["files"] is not files:
        _ATTR_CACHE["files"] = files
        _ATTR_CACHE["cache"] = {}
    cache = _ATTR_CACHE["cache"]
    if path not in cache:
        cache[path] = parse_attributes(_decode(files[path]))
    return cache[path]


def _records_cached(files: dict, path: str) -> dict:
    """cbm/dev/phm 的 key=value 解析缓存（同一包内同文件只解析一次）。"""
    if _RECORDS_CACHE["files"] is not files:
        _RECORDS_CACHE["files"] = files
        _RECORDS_CACHE["cache"] = {}
    cache = _RECORDS_CACHE["cache"]
    if path not in cache:
        cache[path] = parse_kv_dict(_decode(files[path]))
    return cache[path]


def _collect_geometry(files: dict, dev_path: str, m_parent: list,
                      primitives: list, stl_parts: list, attributes: list, seen: set):
    """递归收集设备几何：dev → (子 dev | phm) → mod/stl，矩阵逐层组合。"""
    key = dev_path.lower()
    if key in seen or dev_path not in files:
        return
    seen.add(key)
    dev = _records_cached(files, dev_path)
    base = Path(dev_path).parent.as_posix()

    for ref, m_local in _iter_device_refs(dev):
        sub_path = _resolve(files, base, ref)
        if sub_path not in files:
            continue
        m = mat4_multiply(m_parent, m_local)
        low = sub_path.lower()
        if low.endswith(".dev"):
            _collect_geometry(files, sub_path, m, primitives, stl_parts, attributes, seen)
        elif low.endswith(".phm"):
            phm = _records_cached(files, sub_path)
            for ref2, m2_local in _iter_solid_models(phm):
                leaf = _resolve(files, Path(sub_path).parent.as_posix(), ref2)
                if leaf not in files:
                    continue
                m2 = mat4_multiply(m, m2_local)
                leaf_low = leaf.lower()
                if leaf_low.endswith(".mod"):
                    # mod 图元自带局部变换，叠加链平移（旋转保留在图元内部）
                    # m2 为原样布局（平移在 12/13/14），转置一次供所有图元复用
                    mt = transpose_matrix(m2)
                    for prim in parse_mod(_decode(files[leaf])):
                        prim.position = [
                            mt[3] + prim.position[0],
                            mt[7] + prim.position[1],
                            mt[11] + prim.position[2],
                        ]
                        primitives.append(prim)
                elif leaf_low.endswith(".stl"):
                    # STL 部件：组合矩阵（原样右乘）后整体转置一次，
                    # 平移落到 3/7/11；平移单位为米，×1000 归一到 mm（STL 为 mm）
                    info = _stl_stats(files, leaf)
                    m3 = transpose_matrix(m2)
                    m3[3] *= 1000.0
                    m3[7] *= 1000.0
                    m3[11] *= 1000.0
                    stl_parts.append({
                        "path": leaf.replace("\\", "/"),
                        "transform": [round(x, 6) for x in m3],
                        "faces": info["triangles"],
                    })
                    attributes.append(ModelAttribute(
                        key="STL部件",
                        value=f"{Path(leaf).name}（{info['triangles']}面）",
                        category="design",
                        description="STL 三维部件，面数统计",
                    ))


def _build_device_asset(files: dict, cbm_path: str, header: GimHeader) -> ModelAsset:
    """单设备链：cbm → dev → (fam 属性 + 递归几何)。"""
    cbm = _records_cached(files, cbm_path)
    base = Path(cbm_path).parent.as_posix()

    dev_ref = cbm.get("OBJECTMODELPOINTER", "")
    dev_path = _resolve(files, base, dev_ref) if dev_ref else ""
    dev = _records_cached(files, dev_path) if dev_path in files else {}
    dev_base = Path(dev_path).parent.as_posix() if dev_path else ""

    # 属性：dev 对应 fam（BASEFAMILYPOINTER），回退 cbm 同名 fam
    attributes: list = []
    fam_ref = dev.get("BASEFAMILYPOINTER") or cbm.get("BASEFAMILY") or ""
    fam_path = _resolve(files, dev_base or base, fam_ref) if fam_ref else ""
    if fam_path not in files:
        stem = Path(dev_path or cbm_path).stem
        for name in files:
            if Path(name).stem == stem and name.lower().endswith(".fam"):
                fam_path = name
                break
    if fam_path in files:
        attributes = [_copy_attribute(a) for a in _attributes_cached(files, fam_path)]

    # 几何：dev → (dev 嵌套 | phm) → mod/stl，矩阵逐层组合
    primitives = []
    stl_parts: list = []
    symbol_name = dev.get("SYMBOLNAME", "")
    m_root = parse_transform(cbm.get("TRANSFORMMATRIX", "")) if cbm.get("TRANSFORMMATRIX") else IDENTITY4
    _collect_geometry(files, dev_path, m_root, primitives, stl_parts, attributes, set())

    fields = extract_asset_fields(attributes)
    name = header.name or symbol_name or Path(cbm_path).stem
    description_parts = []
    if header.software:
        description_parts.append(f"来源软件：{header.software}")
    if header.organization:
        description_parts.append(f"组织单位：{header.organization}")
    if header.created_at:
        description_parts.append(f"创建时间：{header.created_at}")

    # 设备类型（subcategory）：DEVICETYPE 映射，未知类型原样保留
    dev_type = (dev.get("DEVICETYPE") or "").strip()
    subcategory = SUBCATEGORY_MAP.get(dev_type.upper(), dev_type) if dev_type else ""

    extra = {}
    if stl_parts:
        extra["stl_parts"] = stl_parts

    return ModelAsset(
        name=name,
        code=header.name or symbol_name,
        model_type="device",
        category=category_for_gim_kind(header.kind),
        voltage_level=fields.get("voltage_level", ""),
        description="；".join(description_parts) or "GIM 导入",
        attributes=attributes,
        geometry=Geometry(primitives=primitives),
        level=4,
        subcategory=subcategory,
        source="gim",
        origin=_origin_of(header),
        extra=extra,
    )


def _walk_cbm(files: dict, cbm_path: str, header: GimHeader, parent_id, seen: set, assets: list):
    if cbm_path in seen:
        return
    seen.add(cbm_path)
    records = _records_cached(files, cbm_path)
    entity = records.get("ENTITYNAME", "")
    if entity.upper() in ("F1SYSTEM", "F2SYSTEM", "F3SYSTEM", "F4SYSTEM"):
        # 工程层级节点：建节点资产并递归
        base = Path(cbm_path).parent.as_posix()
        fam_ref = records.get("BASEFAMILY", "")
        attributes = []
        if fam_ref:
            fam_path = _resolve(files, base, fam_ref)
            if fam_path in files:
                attributes = _attributes_cached(files, fam_path)
        fields = extract_asset_fields(attributes)
        assets.append(ModelAsset(
            name=header.name or Path(cbm_path).stem,
            code=header.name,
            voltage_level=fields.get("voltage_level", ""),
            description=f"GIM 工程层级 {entity}",
            attributes=attributes,
            parent_id=parent_id,
            level=min(4, len(assets) + 1),
        ))
        for child in _collect_children(files, cbm_path):
            _walk_cbm(files, child, header, assets[-1].id, seen, assets)
    else:
        # 设备/部件节点
        assets.append(_build_device_asset(files, cbm_path, header))
        for child in _collect_children(files, cbm_path):
            _walk_cbm(files, child, header, assets[-1].id, seen, assets)


def _is_project_entry(files: dict, entry: str) -> bool:
    """工程模式判定：入口名为 project.cbm，或其子级含 F1System。"""
    if Path(entry).name.lower() == "project.cbm":
        return True
    records = _records_cached(files, entry)
    if records.get("ENTITYNAME", "").upper() in ("F1SYSTEM", "F2SYSTEM", "F3SYSTEM"):
        return True
    return any(
        k.startswith(_CHILD_REF_PREFIXES) and k.upper() in ("SUBSYSTEM", "SECTION0")
        for k in records
    )


def _origin_of(header: GimHeader, **extra) -> dict:
    origin = {
        "gim类型": {"substation": "变电", "line": "输电线路", "cable": "电缆线路"}.get(header.kind, "未知"),
    }
    for key, attr in (("原文件名", "name"), ("软件名称", "software"),
                      ("组织单位", "organization"), ("原始创建时间", "created_at")):
        val = getattr(header, attr, "")
        if val:
            origin[key] = val
    origin.update(extra)
    return origin


def _node_name(records: dict, fallback: str) -> str:
    """层级节点命名：优先 fam 名称字段，否则用回退名。"""
    for key in ("SECTIONNAME", "STRAINSECTIONNAME", "SYSTEMNAME1", "NAME"):
        if records.get(key):
            return records[key]
    return fallback


def _assemble_project(files: dict, entry: str, header: GimHeader,
                      include_string_assets: bool,
                      fallback_voltage: str = "") -> list:
    """工程聚合导入：根 + F1/F2/F3 层级 + 塔组逐基 + 导线/交叉跨越聚合。"""
    assets: list = []
    root = ModelAsset(
        name=header.name or "GIM 工程",
        code=header.name,
        model_type="line" if header.kind in ("line", "unknown") else "device",
        category=category_for_gim_kind(header.kind),
        source="gim",
        origin=_origin_of(header),
        description="GIM 工程根（聚合导入）",
        level=1,
    )
    assets.append(root)

    seen: set = set()
    root_attrs_done = False
    chains = _collect_children(files, entry)
    # π 接/多线工程：project.cbm 可能漏挂部分 F1（实测厂商打包缺陷），扫描孤儿 F1 补挂
    for name, content in files.items():
        if name.lower().endswith(".cbm"):
            ent = _records_cached(files, name).get("ENTITYNAME", "").upper()
            if ent == "F1SYSTEM" and name not in chains:
                chains.append(name)

    for i, f1 in enumerate(chains, 1):
        f1_records = _records_cached(files, f1)
        if not root_attrs_done:
            # 工程级属性：从首个 F1 的 fam 上提
            base = Path(f1).parent.as_posix()
            fam_ref = f1_records.get("BASEFAMILY", "")
            if fam_ref:
                fam_path = _resolve(files, base, fam_ref)
                if fam_path in files:
                    root.attributes = _attributes_cached(files, fam_path)
            root.voltage_level = extract_asset_fields(root.attributes).get("voltage_level", "")
            root_attrs_done = True
        inherited = root.voltage_level or fallback_voltage or DEFAULT_VOLTAGE
        sub = _walk_level(files, f1, header, root.id, assets, f"F1-{i}", seen=seen,
                          include_string_assets=include_string_assets,
                          inherited_voltage=inherited)
    return assets


def _walk_level(files: dict, cbm_path: str, header: GimHeader,
                parent_id, assets: list, path_label: str, seen=None,
                include_string_assets: bool = False,
                inherited_voltage: str = "") -> dict:
    """递归 F1/F2/F3 层级；返回统计（塔数/导线档数等，供父级聚合）。

    inherited_voltage：父级电压（工程根 → F1 → F2 → F3），子级自身无电压时继承。
    """
    if seen is None:
        seen = set()
    if cbm_path in seen:
        return {}
    seen.add(cbm_path)
    records = _records_cached(files, cbm_path)
    entity = records.get("ENTITYNAME", "").upper()
    base = Path(cbm_path).parent.as_posix()

    fam_ref = records.get("BASEFAMILY", "")
    attributes = []
    if fam_ref:
        fam_path = _resolve(files, base, fam_ref)
        if fam_path in files:
            attributes = _attributes_cached(files, fam_path)
    fields = extract_asset_fields(attributes)
    node_voltage = fields.get("voltage_level") or inherited_voltage

    label = {"F1SYSTEM": "全线", "F2SYSTEM": "分段", "F3SYSTEM": "耐张段"}.get(entity, entity)
    node = ModelAsset(
        name=f"{path_label} {_node_name(records, label)}",
        code=header.name,
        model_type="system",
        category=category_for_gim_kind(header.kind),
        voltage_level=node_voltage,
        description=f"GIM 工程层级 {entity}",
        attributes=attributes,
        parent_id=parent_id,
        level=min(3, len(path_label.split("-"))),
        source="gim",
        origin=_origin_of(header),
    )
    assets.append(node)

    stats = {"towers": 0, "wires": 0, "cross": 0, "tower_assets": 0}
    child_inherited = node_voltage or inherited_voltage

    for child in _collect_children(files, cbm_path):
        child_records = _records_cached(files, child)
        child_entity = child_records.get("ENTITYNAME", "").upper()
        if child_entity in ("F1SYSTEM", "F2SYSTEM", "F3SYSTEM"):
            sub = _walk_level(files, child, header, node.id, assets,
                              f"{path_label}-{len(assets)}", seen,
                              include_string_assets=include_string_assets,
                              inherited_voltage=child_inherited)
            for k in stats:
                stats[k] += sub.get(k, 0)
        elif child_entity == "F4SYSTEM":
            group_stats = _handle_group(files, child, header, node, assets,
                                        include_string_assets=include_string_assets,
                                        inherited_voltage=child_inherited)
            stats["towers"] += group_stats.get("towers", 0)
            stats["cross"] += group_stats.get("cross", 0)
            stats["tower_assets"] += group_stats.get("tower_assets", 0)
        elif child_entity in ("TOWER_DEVICE", "WIRE_DEVICE", "WIRE", "CROSS", "DEVICE"):
            # 工程包中散落的子设备：聚合统计，不逐个建模
            stats["wires"] += 1

    # 聚合统计写入层级属性（导线不入库，无导线档数）
    if stats["towers"]:
        node.attributes.append(ModelAttribute(key="杆塔基数", value=str(stats["towers"]), category="design"))
    if stats["cross"]:
        node.attributes.append(ModelAttribute(key="交叉跨越数", value=str(stats["cross"]), category="design"))
    return stats


def _handle_group(files: dict, group_path: str, header: GimHeader,
                  f3_node: ModelAsset, assets: list,
                  include_string_assets: bool = False,
                  inherited_voltage: str = "") -> dict:
    """F4 设备组：塔组逐基建模（含绝缘子串挂件）；导线/交叉跨越聚合统计。"""
    records = _records_cached(files, group_path)
    base = Path(group_path).parent.as_posix()
    group_type = records.get("GROUPTYPE", "").upper()
    stats = {"towers": 0, "wires": 0, "cross": 0, "tower_assets": 0}

    if group_type == "TOWER":
        stats["towers"] = 1
        blha = records.get("BLHA", "")
        tower_ref = records.get("TOWER", "")
        tower = None
        if tower_ref:
            tower_cbm = _resolve(files, base, tower_ref)
            if tower_cbm in files:
                tower = _build_tower_asset(files, tower_cbm, header, blha, len(assets),
                                           voltage_fallback=inherited_voltage)
                tower.parent_id = f3_node.id
                tower.voltage_level = tower.voltage_level or f3_node.voltage_level or inherited_voltage
                assets.append(tower)
                stats["tower_assets"] = 1
        if tower and include_string_assets:
            # 绝缘子串逐串建模（STRINGn.STRING cbm，挂点姿态在矩阵、挂点名 GPOINT）
            idx = 0
            for key, value in records.items():
                ku = key.upper()
                if ku.startswith("STRING") and ku.endswith(".STRING"):
                    idx += 1
                    string_cbm = _resolve(files, base, value)
                    if string_cbm not in files:
                        continue
                    gpoint = records.get(f"{ku.split('.')[0]}.GPOINT", "")
                    s_asset = _build_tower_asset(files, string_cbm, header, "", len(assets),
                                                 subcategory="绝缘子串",
                                                 voltage_fallback=tower.voltage_level or inherited_voltage)
                    s_asset.name = f"{tower.name}-串{idx}"
                    s_asset.parent_id = tower.id
                    s_asset.origin = dict(s_asset.origin or {}, GPOINT=gpoint)
                    assets.append(s_asset)
    elif group_type == "CROSS":
        stats["cross"] = 1
    return stats


def _first_wire_cbm(files: dict, group_path: str):
    base = Path(group_path).parent.as_posix()
    records = _records_cached(files, group_path)
    for key, value in records.items():
        ku = key.upper()
        if ku.startswith("SUBDEVICE") and not ku.endswith(".NUM") and value.lower().endswith(".cbm"):
            child = _resolve(files, base, value)
            if child in files:
                child_records = _records_cached(files, child)
                if child_records.get("ENTITYNAME", "").upper() == "WIRE":
                    return child
    return None


def _wire_sag_segments(files: dict, wire_cbm: str):
    """从 WIRE cbm 提取 BLHA/KVALUE 生成弧垂折线。"""
    records = _records_cached(files, wire_cbm)

    def blha_of(point: str):
        raw = records.get(f"POINT{point}.BLHA", "")
        parts = [x.strip() for x in raw.split(",")]
        if len(parts) >= 3:
            try:
                return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]) if len(parts) > 3 else 0.0)
            except ValueError:
                return None
        return None

    a, b = blha_of("0"), blha_of("1")
    if not a or not b:
        return None
    try:
        kvalue = float(records.get("KVALUE", "0") or 0)
    except ValueError:
        kvalue = 0.0
    return sagcurve_wire(a, b, kvalue=kvalue)


def _build_tower_asset(files: dict, cbm_path: str, header: GimHeader, blha: str, idx: int,
                       subcategory: str = "", voltage_fallback: str = "") -> ModelAsset:
    """塔组子设备（TOWER_DEVICE）→ 模型资产（杆塔或绝缘子串等挂件）。"""
    asset = _build_device_asset(files, cbm_path, header)
    # subcategory 优先由 dev DEVICETYPE 映射（STRING/INSULATOR → 绝缘子串）；
    # 显式指定时强制覆盖（杆塔场景）
    asset.subcategory = subcategory or asset.subcategory or "杆塔"
    asset.source = "gim"
    asset.category = category_for_gim_kind(header.kind)
    if not asset.voltage_level and voltage_fallback:
        asset.voltage_level = voltage_fallback
    asset.origin = _origin_of(header, BLHA=blha)
    asset.level = 4
    # 命名：塔型/型号 + 顺序号
    type_name = ""
    for a in asset.attributes:
        if a.key in ("TYPE", "TOWERTYPE") and a.value:
            type_name = a.value
            break
    prefix = "塔" if (subcategory or asset.subcategory) == "杆塔" else "件"
    asset.name = f"{prefix}{idx}-{type_name}" if type_name else f"{prefix}{idx}"
    return asset


def assemble_gim(files: dict, header: GimHeader,
                 *, include_string_assets: bool = ENABLE_STRING_ASSETS,
                 fallback_voltage: str = "") -> list:
    """GIM 文件集 → ModelAsset 列表（工程聚合 / 单设备）。

    include_string_assets：工程导入是否逐串建模绝缘子串（默认跟随
    ENABLE_STRING_ASSETS 开关；性能优化完成后置 True 全局启用）。
    fallback_voltage：工程电压继承链兜底（导入接口参数），缺省时用 110kV。
    """
    entry = _find_entry(files)
    if _is_project_entry(files, entry):
        return _assemble_project(files, entry, header, include_string_assets,
                                 fallback_voltage=fallback_voltage)
    assets = []
    _walk_cbm(files, entry, header, None, set(), assets)
    return assets


def parse_gim(data: bytes, *, with_files: bool = False, fallback_voltage: str = ""):
    """真实 GIM 容器 → ModelAsset 列表。

    with_files=True 时额外返回解包文件字典（{相对路径: bytes}），
    供调用方复用避免二次解包（如 STL 落盘）。
    fallback_voltage：工程电压继承链兜底（导入接口参数），缺省时用 110kV。
    """
    header = parse_header(data)
    files = unpack_store(data, header.store_offset)
    assets = assemble_gim(files, header, fallback_voltage=fallback_voltage)
    if with_files:
        return assets, files
    return assets
