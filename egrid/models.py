"""领域模型：电力矢量模型库的核心数据结构。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def new_guid() -> str:
    return str(uuid.uuid4()).upper()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ModelType(str, Enum):
    DEVICE = "device"          # 设备
    MATERIAL = "material"      # 材料
    CIVIL = "civil"            # 构筑物/土建
    SYSTEM = "system"          # 系统/区域
    LINE = "line"              # 线路
    OTHER = "other"


class ModelStage(str, Enum):
    COMMON = "common"          # 通用模型库
    PRODUCT = "product"        # 产品模型库
    FINISHED = "finished"      # 成品/竣工模型库
    CUSTOM = "custom"


class Specialty(str, Enum):
    ELECTRICAL_PRIMARY = "electrical_primary"      # 电气一次
    ELECTRICAL_SECONDARY = "electrical_secondary"  # 电气二次
    CIVIL = "civil"                                # 土建
    HVAC = "hvac"                                  # 水暖
    GENERAL = "general"                            # 总图


class GIMFileKind(str, Enum):
    MOD = "mod"   # 几何模型单元
    PHM = "phm"   # 组合模型
    DEV = "dev"   # 物理模型
    CBM = "cbm"   # 工程模型
    FAM = "fam"   # 属性信息
    GIM = "gim"   # 真实 GIM 专有包（暂仅存档）
    STL = "stl"
    OBJ = "obj"
    IFC = "ifc"
    OTHER = "other"


class PrimitiveType(str, Enum):
    BOX = "box"
    CYLINDER = "cylinder"
    SPHERE = "sphere"
    CONE = "cone"
    TORUS = "torus"
    LINE = "line"
    POLYGON = "polygon"
    POINT = "point"


class Primitive(BaseModel):
    """参数化基本图元，对应 GIM *.mod 的简化表达。"""
    id: str = Field(default_factory=new_guid)
    name: str = "primitive"
    type: PrimitiveType = PrimitiveType.BOX
    params: Dict[str, Any] = Field(default_factory=dict)
    # 本地坐标变换：位置、旋转(欧拉角，度)、缩放
    position: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale: List[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0])
    color: str = "#888888"
    material: str = "default"


class Geometry(BaseModel):
    primitives: List[Primitive] = Field(default_factory=list)
    # 单位：mm，符合 GIM 1:1 建模要求
    unit: str = "mm"


class ModelAttribute(BaseModel):
    key: str
    value: Any
    category: str = "design"   # design/product/construction/test/operation
    unit: str = ""
    description: str = ""


class ModelFile(BaseModel):
    guid: str = Field(default_factory=new_guid)
    path: str
    kind: GIMFileKind = GIMFileKind.OTHER
    size: int = 0
    checksum: str = ""
    transform: List[float] = Field(default_factory=list)  # 引用链组合变换矩阵（16值，空=单位阵）


class ModelVersion(BaseModel):
    id: str = Field(default_factory=new_guid)
    version: str = "v1"
    note: str = ""
    created_at: str = Field(default_factory=utcnow)
    data: Dict[str, Any] = Field(default_factory=dict)


class ModelAsset(BaseModel):
    """模型主记录，对应数据库 model_asset 表。"""
    id: str = Field(default_factory=new_guid)
    name: str
    code: str = ""                     # GB/T 51061 / 物料编码
    category: str = ""                 # 业务大类：变电/输电/电缆/配电（可扩展）
    model_type: ModelType = ModelType.DEVICE
    stage: ModelStage = ModelStage.COMMON
    specialty: Specialty = Specialty.ELECTRICAL_PRIMARY
    voltage_level: str = ""            # 如 110kV / 220kV / 10kV
    version: str = "v1"
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    attributes: List[ModelAttribute] = Field(default_factory=list)
    files: List[ModelFile] = Field(default_factory=list)
    geometry: Geometry = Field(default_factory=Geometry)
    parent_id: Optional[str] = None    # 支持 F1-F5 层级
    level: int = 4                     # 1-5，默认设备级
    subcategory: str = ""              # 子分类：杆塔/导线/绝缘子串等（挂大类下）
    source: str = "manual"             # 来源：manual/gim/zip
    origin: Dict[str, Any] = Field(default_factory=dict)  # 溯源：原文件名/软件/单位/原始时间
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)
    created_by: str = "system"
    extra: Dict[str, Any] = Field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = utcnow()


class ModelQuery(BaseModel):
    keyword: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    source: Optional[str] = None
    model_type: Optional[ModelType] = None
    stage: Optional[ModelStage] = None
    specialty: Optional[Specialty] = None
    voltage_level: Optional[str] = None
    level: Optional[int] = None
    parent_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    offset: int = 0
    limit: int = 100


class PointCloudSample(BaseModel):
    model_id: str
    points: List[List[float]]
    labels: List[str]
    count: int = 0
    format: str = "json"
