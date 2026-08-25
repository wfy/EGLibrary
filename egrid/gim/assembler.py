"""GIM 组装器：沿 CBM → DEV → PHM → MOD 引用链组装 ModelAsset。

依据 Q/GDW 11809 附录A.6/A.7/A.9：
- 单设备文件（A.9）：CBM 入口 ENTITYNAME=Device，直接走设备链
- 工程文件（A.6/A.7）：project.cbm 为入口，SUBSYSTEM/SECTION 等引用构成层级树
"""
from __future__ import annotations

from pathlib import Path

from ..models import Geometry, ModelAsset, ModelAttribute
from .container import unpack_store
from .header import GimHeader, parse_header
from .parsers.fam import extract_asset_fields, parse_attributes
from .parsers.mod import parse_mod
from .records import parse_kv_dict

# cbm 中表示子级引用的键（工程树，第一版按引用展开）
_CHILD_REF_PREFIXES = ("SUBSYSTEM", "SECTION", "STRAINSECTION", "GROUP", "SUBDEVICE", "STRING", "BASE")


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
                    elif mod_path in files:
                        # stl/ifc 等挂接文件第一版仅存档
                        pass

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


def assemble_gim(files: dict, header: GimHeader) -> list:
    """GIM 文件集 → ModelAsset 列表（含层级挂接）。"""
    entry = _find_entry(files)
    assets = []
    _walk_cbm(files, entry, header, None, set(), assets)
    return assets


def parse_gim(data: bytes) -> list:
    """真实 GIM 容器 → ModelAsset 列表。"""
    header = parse_header(data)
    files = unpack_store(data, header.store_offset)
    return assemble_gim(files, header)
