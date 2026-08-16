"""内置示例模型：用于快速搭建演示数据。"""
from __future__ import annotations

from typing import List

from .models import (
    Geometry,
    ModelAsset,
    ModelAttribute,
    Primitive,
    PrimitiveType,
)
from .service import ModelService


def build_demo_models() -> List[ModelAsset]:
    return [
        ModelAsset(
            name="220kV 油浸式电力变压器",
            code="SFZ11-180000/220",
            model_type="device",
            voltage_level="220kV",
            stage="product",
            description="通用产品模型：主变外形及主要接口",
            attributes=[
                ModelAttribute(key="额定容量", value="180MVA", category="design", unit="MVA"),
                ModelAttribute(key="额定电压", value="220/110/35kV", category="design"),
            ],
            geometry=Geometry(primitives=[
                Primitive(name="油箱", type=PrimitiveType.BOX, params={"width": 3000, "depth": 1500, "height": 2200}, material="steel"),
                Primitive(name="高压套管", type=PrimitiveType.CYLINDER, params={"radius": 120, "height": 1800}, position=[1200, 0, 900], material="insulator"),
                Primitive(name="中压套管", type=PrimitiveType.CYLINDER, params={"radius": 100, "height": 1500}, position=[0, 0, 900], material="insulator"),
                Primitive(name="低压套管", type=PrimitiveType.CYLINDER, params={"radius": 80, "height": 1200}, position=[-1200, 0, 900], material="insulator"),
            ]),
        ),
        ModelAsset(
            name="110kV 隔离开关",
            code="GW4-126",
            model_type="device",
            voltage_level="110kV",
            stage="product",
            description="双柱水平开启式隔离开关",
            attributes=[ModelAttribute(key="额定电流", value="1250A", category="design", unit="A")],
            geometry=Geometry(primitives=[
                Primitive(name="支柱绝缘子", type=PrimitiveType.CYLINDER, params={"radius": 80, "height": 1200}, position=[-400, 0, 0], material="insulator"),
                Primitive(name="支柱绝缘子", type=PrimitiveType.CYLINDER, params={"radius": 80, "height": 1200}, position=[400, 0, 0], material="insulator"),
                Primitive(name="导电杆", type=PrimitiveType.BOX, params={"width": 1200, "depth": 60, "height": 60}, material="conductor"),
            ]),
        ),
        ModelAsset(
            name="绝缘子串",
            code="XP-70",
            model_type="material",
            voltage_level="110kV",
            stage="common",
            description="盘形悬式绝缘子串",
            geometry=Geometry(primitives=[
                Primitive(name="绝缘子", type=PrimitiveType.CYLINDER, params={"radius": 70, "height": 120}, position=[i * 140, 0, 0], material="insulator")
                for i in range(7)
            ]),
        ),
        ModelAsset(
            name="角钢塔",
            code="2C2W8-J1",
            model_type="civil",
            voltage_level="220kV",
            stage="common",
            description="输电线路角钢塔简化模型",
            geometry=Geometry(primitives=[
                Primitive(name="塔腿", type=PrimitiveType.BOX, params={"width": 200, "depth": 200, "height": 1200}, position=[-800, -800, 0], material="steel"),
                Primitive(name="塔腿", type=PrimitiveType.BOX, params={"width": 200, "depth": 200, "height": 1200}, position=[800, -800, 0], material="steel"),
                Primitive(name="塔腿", type=PrimitiveType.BOX, params={"width": 200, "depth": 200, "height": 1200}, position=[-800, 800, 0], material="steel"),
                Primitive(name="塔腿", type=PrimitiveType.BOX, params={"width": 200, "depth": 200, "height": 1200}, position=[800, 800, 0], material="steel"),
                Primitive(name="横担", type=PrimitiveType.BOX, params={"width": 3000, "depth": 150, "height": 150}, position=[0, 0, 1200], material="steel"),
            ]),
        ),
        ModelAsset(
            name="架空导线",
            code="LGJ-400/35",
            model_type="line",
            voltage_level="220kV",
            stage="common",
            description="钢芯铝绞线参数化模型",
            geometry=Geometry(primitives=[
                Primitive(name="导线", type=PrimitiveType.LINE, params={"start": [-5000, 0, 0], "end": [5000, 0, 0]}, material="conductor"),
            ]),
        ),
    ]


def seed_demo_models(service: ModelService) -> List[ModelAsset]:
    created = []
    for asset in build_demo_models():
        created.append(service.create_model(asset))
    return created
