"""业务服务层：模型入库、查询、修改、导出、版本、导入。"""
from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Union

from .models import (
    GIMFileKind,
    ModelAsset,
    ModelAttribute,
    ModelFile,
    ModelQuery,
    ModelVersion,
    new_guid,
    utcnow,
)
from .gim import is_gim, parse_gim
from .storage import ModelRepository

# GIM 标准四目录结构
GIM_DIRS = ["CBM", "DEV", "PHM", "MOD"]
GIM_EXT_TO_KIND = {
    ".mod": GIMFileKind.MOD,
    ".phm": GIMFileKind.PHM,
    ".dev": GIMFileKind.DEV,
    ".cbm": GIMFileKind.CBM,
    ".fam": GIMFileKind.FAM,
    ".gim": GIMFileKind.GIM,
    ".stl": GIMFileKind.STL,
    ".obj": GIMFileKind.OBJ,
    ".ifc": GIMFileKind.IFC,
}

# 真实 GIM 专有包魔数（GIMPKGT）
GIM_MAGIC = b"GIMPKGT"


class ModelService:
    def __init__(
        self,
        repo: Optional[ModelRepository] = None,
        storage_dir: str = "data/files",
        db_path: str = "data/eglibrary.db",
    ):
        self.repo = repo or ModelRepository(db_path)
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    # ---------- CRUD ----------
    def create_model(self, data: Union[ModelAsset, Dict]) -> ModelAsset:
        if isinstance(data, ModelAsset):
            asset = data
        else:
            asset = ModelAsset.model_validate(data)
        if not asset.id:
            asset.id = new_guid()
        return self.repo.create_model(asset)

    def get_model(self, model_id: str) -> Optional[ModelAsset]:
        return self.repo.get_model(model_id)

    def list_models(self, query: Optional[ModelQuery] = None) -> List[ModelAsset]:
        return self.repo.list_models(query)

    def update_model(self, model_id: str, patch: Dict) -> Optional[ModelAsset]:
        existing = self.repo.get_model(model_id)
        if not existing:
            return None
        data = existing.model_dump(mode="json")
        data.update(patch)
        data["id"] = model_id
        updated = ModelAsset.model_validate(data)
        return self.repo.update_model(updated)

    def delete_model(self, model_id: str) -> bool:
        # 同时删除本地文件
        model = self.repo.get_model(model_id)
        if model:
            for f in model.files:
                try:
                    p = self._file_path(model_id, f.path)
                    if p.exists():
                        p.unlink()
                except OSError:
                    pass
        return self.repo.delete_model(model_id)

    def add_version(self, model_id: str, note: str = "") -> Optional[ModelVersion]:
        model = self.repo.get_model(model_id)
        if not model:
            return None
        version = ModelVersion(
            version=model.version,
            note=note or f"快照 {utcnow()}",
            data=model.model_dump(mode="json"),
        )
        return self.repo.add_version(model_id, version)

    def list_versions(self, model_id: str) -> List[ModelVersion]:
        return self.repo.list_versions(model_id)

    # ---------- 分类（电力领域 × 设备类型，双正交维度） ----------
    def list_categories(self) -> List[str]:
        return self.repo.list_categories()

    def add_category(self, name: str) -> int:
        name = (name or "").strip()
        if not name:
            raise ValueError("领域名称不能为空")
        return self.repo.add_category(name)

    def delete_category(self, name: str) -> bool:
        return self.repo.delete_category((name or "").strip())

    def list_equipment_types(self) -> List[str]:
        return self.repo.list_equipment_types()

    def add_equipment_type(self, name: str) -> int:
        name = (name or "").strip()
        if not name:
            raise ValueError("设备类型名称不能为空")
        return self.repo.add_equipment_type(name)

    def delete_equipment_type(self, name: str) -> bool:
        return self.repo.delete_equipment_type((name or "").strip())

    # ---------- 文件存储 ----------
    def _file_path(self, model_id: str, relative_path: str) -> Path:
        # 防止路径穿越
        rel = Path(relative_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"非法文件路径: {relative_path}")
        return self.storage_dir / model_id / rel

    def _store_uploaded_file(self, model_id: str, filename: str, content: bytes) -> ModelFile:
        target = self._file_path(model_id, filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        ext = Path(filename).suffix.lower()
        kind = GIM_EXT_TO_KIND.get(ext, GIMFileKind.OTHER)
        return ModelFile(
            path=filename,
            kind=kind,
            size=len(content),
        )

    # ---------- GIM 导入 ----------
    def import_gim_package(
        self,
        package_path: str,
        name: Optional[str] = None,
        voltage_level: str = "",
        fallback_name: Optional[str] = None,
    ) -> List[ModelAsset]:
        """导入 .gim/.zip 包或目录。

        真实 GIM 为专有 7Z 类压缩包，本实现使用 ZIP 作为可移植的简化载体，
        同时兼容直接传入解包后的目录。文件会复制到本地模型库存储区。
        fallback_name 用于上传场景：临时文件名无意义时回退为原始文件名。
        """
        src = Path(package_path)
        if not src.exists():
            raise FileNotFoundError(f"模型包不存在: {src}")

        created: List[ModelAsset] = []
        with tempfile.TemporaryDirectory(prefix="egrid_import_") as tmp:
            tmp_path = Path(tmp)
            if src.is_file() and zipfile.is_zipfile(src):
                with zipfile.ZipFile(src) as zf:
                    zf.extractall(tmp_path)
                root = tmp_path
            elif src.is_file():
                content = src.read_bytes()
                if is_gim(content):
                    return self._import_real_gim(
                        content, src, name or fallback_name, voltage_level
                    )
                # 简化：单文件作为 .mod 直接入库
                return [self._import_single_file(src, name or fallback_name, voltage_level)]
            else:
                root = src

            manifest = None
            manifest_file = root / "manifest.json"
            if manifest_file.exists():
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

            files: List[ModelFile] = []
            temp_ids: List[str] = []
            for p in sorted(root.rglob("*")):
                if p.is_file() and p.suffix.lower() in GIM_EXT_TO_KIND:
                    rel = p.relative_to(root).as_posix()
                    content = p.read_bytes()
                    temp_id = new_guid()
                    temp_ids.append(temp_id)
                    files.append(self._store_uploaded_file(
                        temp_id,  # 临时 id，后面统一替换
                        rel,
                        content,
                    ))

            if not files and manifest:
                # 至少保留 manifest 作为模型文件
                files.append(ModelFile(
                    path="manifest.json",
                    kind=GIMFileKind.OTHER,
                    size=len(json.dumps(manifest).encode("utf-8")),
                ))

            if manifest and "models" in manifest:
                for m in manifest["models"]:
                    asset = ModelAsset.model_validate(m)
                    asset.id = new_guid()
                    # 将暂存文件归属到该模型（每个模型使用独立副本，避免互相覆盖）
                    model_files = copy.deepcopy(files)
                    asset.files = model_files
                    asset.voltage_level = asset.voltage_level or voltage_level
                    self._persist_files_from_temp(asset, model_files)
                    created.append(self.repo.create_model(asset))
            else:
                asset_name = name or (manifest.get("name") if manifest else None) or fallback_name or src.stem
                asset = ModelAsset(
                    name=asset_name,
                    voltage_level=voltage_level,
                    files=files,
                    attributes=self._parse_fam_attributes(files),
                )
                # 从 CBM 文件名推断编码
                for f in files:
                    if f.kind == GIMFileKind.CBM:
                        asset.code = Path(f.path).stem
                        break
                self._persist_files_from_temp(asset, files)
                created.append(self.repo.create_model(asset))

            self._cleanup_temp_files(temp_ids)

        return created

    def _cleanup_temp_files(self, temp_ids: List[str]) -> None:
        for temp_id in temp_ids:
            path = self.storage_dir / temp_id
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)

    def _import_real_gim(
        self,
        content: bytes,
        src: Path,
        name: Optional[str],
        voltage_level: str,
    ) -> List[ModelAsset]:
        """真实 GIM 专有容器：解析属性与几何，原包仅随根模型存档一份。"""
        assets = parse_gim(content)
        created = []
        # STL 挂件落盘到根模型目录（供三维端点按需加载）
        stl_files = {}
        from .gim.container import unpack_store
        from .gim.header import parse_header as _gim_header
        try:
            store = unpack_store(content, _gim_header(content).store_offset)
            for rel, blob in store.items():
                if rel.lower().endswith(".stl"):
                    stl_files[rel] = blob
        except Exception:
            stl_files = {}  # STL 落盘失败不阻断导入

        for i, asset in enumerate(assets):
            is_root = not asset.parent_id
            if name and is_root:
                asset.name = name
            asset.voltage_level = asset.voltage_level or voltage_level
            # 新设备类型自动注册（筛选清单随导入扩展）
            if asset.subcategory:
                self.repo.upsert_equipment_type(asset.subcategory)
            if is_root:
                # 原包只存档一份（挂根模型），子模型不重复落盘
                model_file = self._store_uploaded_file(asset.id, src.name, content)
                asset.files = [model_file]
                # STL 部件唯一文件落盘（实例矩阵走 extra.stl_parts，多实例共享文件）
                for rel, blob in stl_files.items():
                    asset.files.append(self._store_uploaded_file(asset.id, rel, blob))
            created.append(self.repo.create_model(asset))
        return created

    def _import_single_file(self, path: Path, name: Optional[str], voltage_level: str) -> ModelAsset:
        content = path.read_bytes()
        description = ""
        if content.startswith(GIM_MAGIC):
            # 真实 GIM 专有包：暂仅存档，不做结构解析
            description = (
                "检测到真实 GIM 专有格式（GIMPKGT），当前版本仅存档未解析；"
                "几何与属性需待 GIM 解析模块支持。"
            )
        asset = ModelAsset(
            name=name or path.stem,
            voltage_level=voltage_level,
            description=description,
        )
        asset.id = new_guid()
        model_file = self._store_uploaded_file(asset.id, path.name, content)
        asset.files = [model_file]
        return self.repo.create_model(asset)

    def _persist_files_from_temp(self, asset: ModelAsset, files: List[ModelFile]) -> None:
        # 导入时已经用临时 id 存了文件，需要复制到最终模型目录。
        # 为简单起见，在 create_model 后由 create_model 直接保存也可；
        # 这里直接修正文件路径并确保文件在最终目录。
        for f in files:
            tmp_path = self._file_path(f.guid, f.path)
            final_path = self._file_path(asset.id, f.path)
            if tmp_path.exists():
                final_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(tmp_path, final_path)
            f.guid = new_guid()

    def _parse_fam_attributes(self, files: List[ModelFile]) -> List[ModelAttribute]:
        attrs: List[ModelAttribute] = []
        for f in files:
            if f.kind != GIMFileKind.FAM:
                continue
            path = self._file_path(f.guid, f.path)
            parsed = False
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="ignore")
                for line in text.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("//"):
                        continue
                    if "=" in line:
                        key, value = line.split("=", 1)
                        attrs.append(ModelAttribute(
                            key=key.strip(),
                            value=value.strip(),
                            category="design",
                        ))
                        parsed = True
            if not parsed:
                # 真实 .fam 是 XML/专有格式，需按 Q/GDW 11809 完整解析
                attrs.append(ModelAttribute(
                    key="fam_file",
                    value=f.path,
                    category="design",
                    description="关联的 GIM 属性文件",
                ))
        return attrs

    # ---------- GIM 导出 ----------
    def export_gim_package(self, model_id: str, out_path: Optional[str] = None) -> str:
        model = self.repo.get_model(model_id)
        if not model:
            raise KeyError(f"模型不存在: {model_id}")
        out = Path(out_path) if out_path else self.storage_dir / f"{model.name}_{model.id}.gim"
        out.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="egrid_export_") as tmp:
            root = Path(tmp)
            for d in GIM_DIRS:
                (root / d).mkdir(parents=True, exist_ok=True)

            for f in model.files:
                src = self._file_path(model_id, f.path)
                if src.exists():
                    target = root / f.path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, target)
                else:
                    # 允许只包含元数据的模型
                    (root / f.path).parent.mkdir(parents=True, exist_ok=True)
                    (root / f.path).write_text("", encoding="utf-8")

            manifest = {
                "name": model.name,
                "id": model.id,
                "code": model.code,
                "version": model.version,
                "model_type": model.model_type.value,
                "stage": model.stage.value,
                "specialty": model.specialty.value,
                "voltage_level": model.voltage_level,
                "attributes": [a.model_dump(mode="json") for a in model.attributes],
                "geometry": model.geometry.model_dump(mode="json"),
            }
            (root / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            if out.exists():
                out.unlink()
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in sorted(root.rglob("*")):
                    if p.is_file():
                        zf.write(p, p.relative_to(root).as_posix())
        return str(out)

    # ---------- 统计 ----------
    def stats(self) -> dict:
        return self.repo.stats()
