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
from .header import GimHeader, parse_header
from .parsers.fam import extract_asset_fields, parse_attributes
from .parsers.mod import parse_mod, sagcurve_wire
from .records import parse_kv_dict

# cbm 中表示子级引用的键（工程树，第一版按引用展开）
_CHILD_REF_PREFIXES = ("SUBSYSTEM", "SECTION", "STRAINSECTION", "GROUP", "SUBDEVICE", "STRING", "BASE")

# 子分类映射：DEVICETYPE/GROUPTYPE → 子分类名
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


def _resolve(files: dict, base_dir: str, ref: str) -> str:
    """把 cbm/dev/phm/mod 内的相对引用解析为包内路径。"""
    ref = ref.strip().replace("\\", "/")
    candidate = f"{base_dir}/{ref}"
    for name in files:
        if name.lower() == candidate.lower() or name.lower().endswith("/" + ref.lower()):
            return name
    return candidate


def _decode(data: bytes) -> str:
    return data.decode("utf-8-sig", errors="replace")


def _collect_children(files: dict, cbm_path: str) -> list:
    """收集 cbm 的子级 cbm 引用（工程层级树）。"""
    records = parse_kv_dict(_decode(files[cbm_path]))
    base = Path(cbm_path).parent.as_posix()
    children = []
    for key, value in records.items():
        if key.isupper() and key.startswith(_CHILD_REF_PREFIXES) and value.lower().endswith(".cbm"):
            child = _resolve(files, base, value)
            if child in files:
                children.append(child)
    return children


def _build_device_asset(files: dict, cbm_path: str, header: GimHeader) -> ModelAsset:
    """单设备链：cbm → dev → (fam 属性 + phm → mod 几何)。"""
    cbm = parse_kv_dict(_decode(files[cbm_path]))
    base = Path(cbm_path).parent.as_posix()

    dev_ref = cbm.get("OBJECTMODELPOINTER", "")
    dev_path = _resolve(files, base, dev_ref) if dev_ref else ""
    dev = parse_kv_dict(_decode(files[dev_path])) if dev_path in files else {}
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
        attributes = parse_attributes(_decode(files[fam_path]))

    # 几何：dev → phm → mod
    primitives = []
    symbol_name = dev.get("SYMBOLNAME", "")
    for key, value in dev.items():
        if key.upper() == "SOLIDMODEL0" or (key.upper().startswith("SOLIDMODEL") and key.upper().endswith(tuple("0123456789"))):
            phm_path = _resolve(files, dev_base, value)
            if phm_path not in files:
                continue
            phm = parse_kv_dict(_decode(files[phm_path]))
            phm_base = Path(phm_path).parent.as_posix()
            for k2, v2 in phm.items():
                if k2.upper().startswith("SOLIDMODEL") and k2.upper() != "SOLIDMODELS.NUM":
                    mod_path = _resolve(files, phm_base, v2)
                    if mod_path in files and mod_path.lower().endswith(".mod"):
                        primitives.extend(parse_mod(_decode(files[mod_path])))
                    elif mod_path in files and mod_path.lower().endswith(".stl"):
                        # STL 挂件：统计入属性（三角面不入几何 JSON，端点按需加载）
                        from .parsers.stl import parse_stl
                        info = parse_stl(files[mod_path])
                        attributes.append(ModelAttribute(
                            key="STL挂件",
                            value=f"{Path(mod_path).name}（{info['triangles']}面）",
                            category="design",
                            description="STL 三维挂件，面数统计",
                        ))

    fields = extract_asset_fields(attributes)
    name = header.name or symbol_name or Path(cbm_path).stem
    description_parts = []
    if header.software:
        description_parts.append(f"来源软件：{header.software}")
    if header.organization:
        description_parts.append(f"组织单位：{header.organization}")
    if header.created_at:
        description_parts.append(f"创建时间：{header.created_at}")

    return ModelAsset(
        name=name,
        code=header.name or symbol_name,
        model_type="device",
        voltage_level=fields.get("voltage_level", ""),
        description="；".join(description_parts) or "GIM 导入",
        attributes=attributes,
        geometry=Geometry(primitives=primitives),
        level=4,
    )


def _walk_cbm(files: dict, cbm_path: str, header: GimHeader, parent_id, seen: set, assets: list):
    if cbm_path in seen:
        return
    seen.add(cbm_path)
    records = parse_kv_dict(_decode(files[cbm_path]))
    entity = records.get("ENTITYNAME", "")
    if entity.upper() in ("F1SYSTEM", "F2SYSTEM", "F3SYSTEM", "F4SYSTEM"):
        # 工程层级节点：建节点资产并递归
        base = Path(cbm_path).parent.as_posix()
        fam_ref = records.get("BASEFAMILY", "")
        attributes = []
        if fam_ref:
            fam_path = _resolve(files, base, fam_ref)
            if fam_path in files:
                attributes = parse_attributes(_decode(files[fam_path]))
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
    records = parse_kv_dict(_decode(files[entry]))
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


def _assemble_project(files: dict, entry: str, header: GimHeader) -> list:
    """工程聚合导入：根 + F1/F2/F3 层级 + 塔组逐基 + 导线/交叉跨越聚合。"""
    assets: list = []
    root = ModelAsset(
        name=header.name or "GIM 工程",
        code=header.name,
        model_type="line" if header.kind in ("line", "unknown") else "device",
        category={"substation": "变电", "line": "输电", "cable": "电缆"}.get(header.kind, "输电"),
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
            ent = parse_kv_dict(_decode(content)).get("ENTITYNAME", "").upper()
            if ent == "F1SYSTEM" and name not in chains:
                chains.append(name)

    for i, f1 in enumerate(chains, 1):
        f1_records = parse_kv_dict(_decode(files[f1]))
        sub = _walk_level(files, f1, header, root.id, assets, f"F1-{i}", seen=seen)
        if not root_attrs_done:
            # 工程级属性：从首个 F1 的 fam 上提
            base = Path(f1).parent.as_posix()
            fam_ref = f1_records.get("BASEFAMILY", "")
            if fam_ref:
                fam_path = _resolve(files, base, fam_ref)
                if fam_path in files:
                    root.attributes = parse_attributes(_decode(files[fam_path]))
            root.voltage_level = next(
                (a.value for a in root.attributes if a.key in ("VOLTAGE", "VOLTAGECLASS") and a.value), ""
            )
            root_attrs_done = True
    return assets


def _walk_level(files: dict, cbm_path: str, header: GimHeader,
                parent_id, assets: list, path_label: str, seen=None) -> dict:
    """递归 F1/F2/F3 层级；返回统计（塔数/导线档数等，供父级聚合）。"""
    if seen is None:
        seen = set()
    if cbm_path in seen:
        return {}
    seen.add(cbm_path)
    records = parse_kv_dict(_decode(files[cbm_path]))
    entity = records.get("ENTITYNAME", "").upper()
    base = Path(cbm_path).parent.as_posix()

    fam_ref = records.get("BASEFAMILY", "")
    attributes = []
    if fam_ref:
        fam_path = _resolve(files, base, fam_ref)
        if fam_path in files:
            attributes = parse_attributes(_decode(files[fam_path]))
    fields = extract_asset_fields(attributes)

    label = {"F1SYSTEM": "全线", "F2SYSTEM": "分段", "F3SYSTEM": "耐张段"}.get(entity, entity)
    node = ModelAsset(
        name=f"{path_label} {_node_name(records, label)}",
        code=header.name,
        model_type="system",
        category={"substation": "变电", "line": "输电", "cable": "电缆"}.get(header.kind, "输电"),
        voltage_level=fields.get("voltage_level", ""),
        description=f"GIM 工程层级 {entity}",
        attributes=attributes,
        parent_id=parent_id,
        level=min(3, len(path_label.split("-"))),
        source="gim",
        origin=_origin_of(header),
    )
    assets.append(node)

    stats = {"towers": 0, "wires": 0, "cross": 0, "tower_assets": 0}
    sag_segs: list = []

    for child in _collect_children(files, cbm_path):
        child_records = parse_kv_dict(_decode(files[child]))
        child_entity = child_records.get("ENTITYNAME", "").upper()
        if child_entity in ("F1SYSTEM", "F2SYSTEM", "F3SYSTEM"):
            sub = _walk_level(files, child, header, node.id, assets,
                              f"{path_label}-{len(assets)}", seen)
            for k in stats:
                stats[k] += sub.get(k, 0)
        elif child_entity == "F4SYSTEM":
            group_stats = _handle_group(files, child, header, node, assets)
            sag_segs.extend(group_stats.get("sag_segs", []))
            stats["towers"] += group_stats.get("towers", 0)
            stats["wires"] += group_stats.get("wires", 0)
            stats["cross"] += group_stats.get("cross", 0)
            stats["tower_assets"] += group_stats.get("tower_assets", 0)
        elif child_entity in ("TOWER_DEVICE", "WIRE_DEVICE", "WIRE", "CROSS", "DEVICE"):
            # 工程包中散落的子设备：聚合统计，不逐个建模
            stats["wires"] += 1

    # 全档弧垂曲线挂 F3（每档一条折线，米制局部坐标）
    if sag_segs:
        node.geometry = Geometry(
            primitives=[
                Primitive(
                    name="导线弧垂",
                    type=PrimitiveType.LINE,
                    params={"start": s["start"], "end": s["end"]},
                    material="conductor",
                )
                for s in sag_segs
            ]
        )
        node.geometry.unit = "m"

    # 聚合统计写入层级属性
    if stats["towers"]:
        node.attributes.append(ModelAttribute(key="杆塔基数", value=str(stats["towers"]), category="design"))
    if stats["wires"]:
        node.attributes.append(ModelAttribute(key="导线档数", value=str(stats["wires"]), category="design"))
    if stats["cross"]:
        node.attributes.append(ModelAttribute(key="交叉跨越数", value=str(stats["cross"]), category="design"))
    return stats


def _handle_group(files: dict, group_path: str, header: GimHeader,
                  f3_node: ModelAsset, assets: list) -> dict:
    """F4 设备组：塔组逐基建模；导体组全档弧垂；交叉跨越聚合。"""
    records = parse_kv_dict(_decode(files[group_path]))
    base = Path(group_path).parent.as_posix()
    group_type = records.get("GROUPTYPE", "").upper()
    stats = {"towers": 0, "wires": 0, "cross": 0, "tower_assets": 0, "sag_segs": []}

    if group_type == "TOWER":
        stats["towers"] = 1
        blha = records.get("BLHA", "")
        tower_ref = records.get("TOWER", "")
        if tower_ref:
            tower_cbm = _resolve(files, base, tower_ref)
            if tower_cbm in files:
                tower = _build_tower_asset(files, tower_cbm, header, blha, len(assets))
                tower.parent_id = f3_node.id
                tower.voltage_level = tower.voltage_level or f3_node.voltage_level
                assets.append(tower)
                stats["tower_assets"] = 1
        # 绝缘子串/基础等挂件聚合计数
        stats["wires"] += sum(1 for k in records if k.upper().startswith("STRING") and k.endswith(".STRING"))
        stats["wires"] += sum(1 for k in records if k.upper().startswith("BASE") and k not in ("BASEFAMILY",))
    elif group_type == "WIRE":
        stats["wires"] = 1
        # 全档展开：每个导线档生成弧垂曲线
        wire_cbm = _first_wire_cbm(files, group_path)
        if wire_cbm:
            segs = _wire_sag_segments(files, wire_cbm)
            if segs:
                stats["sag_segs"] = segs
    elif group_type == "CROSS":
        stats["cross"] = 1
    return stats


def _first_wire_cbm(files: dict, group_path: str):
    base = Path(group_path).parent.as_posix()
    records = parse_kv_dict(_decode(files[group_path]))
    for key, value in records.items():
        ku = key.upper()
        if ku.startswith("SUBDEVICE") and not ku.endswith(".NUM") and value.lower().endswith(".cbm"):
            child = _resolve(files, base, value)
            if child in files:
                child_records = parse_kv_dict(_decode(files[child]))
                if child_records.get("ENTITYNAME", "").upper() == "WIRE":
                    return child
    return None


def _wire_sag_segments(files: dict, wire_cbm: str):
    """从 WIRE cbm 提取 BLHA/KVALUE 生成弧垂折线。"""
    records = parse_kv_dict(_decode(files[wire_cbm]))

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


def _build_tower_asset(files: dict, cbm_path: str, header: GimHeader, blha: str, idx: int) -> ModelAsset:
    """塔组子设备（TOWER_DEVICE）→ 杆塔模型资产。"""
    asset = _build_device_asset(files, cbm_path, header)
    asset.subcategory = SUBCATEGORY_MAP.get("TOWER", "杆塔")
    asset.source = "gim"
    asset.category = {"substation": "变电", "line": "输电", "cable": "电缆"}.get(header.kind, "输电")
    asset.origin = _origin_of(header, BLHA=blha)
    asset.level = 4
    # 命名：塔型 + 顺序号
    tower_type = ""
    for a in asset.attributes:
        if a.key in ("TYPE", "TOWERTYPE") and a.value:
            tower_type = a.value
            break
    asset.name = f"塔{idx}-{tower_type}" if tower_type else f"塔{idx}"
    return asset


def assemble_gim(files: dict, header: GimHeader) -> list:
    """GIM 文件集 → ModelAsset 列表（工程聚合 / 单设备）。"""
    entry = _find_entry(files)
    if _is_project_entry(files, entry):
        return _assemble_project(files, entry, header)
    assets = []
    _walk_cbm(files, entry, header, None, set(), assets)
    return assets


def parse_gim(data: bytes) -> list:
    """真实 GIM 容器 → ModelAsset 列表。"""
    header = parse_header(data)
    files = unpack_store(data, header.store_offset)
    return assemble_gim(files, header)
