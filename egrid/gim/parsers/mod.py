"""mod 几何文件解析。

- 变电/换流站（Q/GDW 11809 附录A.6.5）：XML，Entity 节点 + 参数化图元 + 布尔运算 + 变换矩阵
- 架空线路杆塔（Q/GDW 11810.2 附录A.3）：文本，P 节点 + r 杆件线架 + G 挂点
- 导线弧垂（Q/GDW 11809 附录A.7.2-f.3）：BLHA 塔位 + KVALUE → 悬链线折线
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from ...models import Primitive, PrimitiveType

# 变电 XML 图元标签 → (PrimitiveType, 参数名映射)
XML_PRIMITIVES = {
    "Cuboid": (PrimitiveType.BOX, {"L": "depth", "W": "width", "H": "height"}),
    "Sphere": (PrimitiveType.SPHERE, {"R": "radius"}),
    "Cylinder": (PrimitiveType.CYLINDER, {"R": "radius", "H": "height"}),
    "Cone": (PrimitiveType.CONE, {"R": "radius", "H": "height"}),
    "Ring": (PrimitiveType.TORUS, {"R": "major_radius", "DR": "minor_radius"}),
}


def sagcurve_wire(blha_a: tuple, blha_b: tuple, kvalue: float = 0.0, samples: int = 24) -> list:
    """导线弧垂悬链线（抛物线近似）→ 线段参数列表（米单位，档距局部坐标）。

    BLHA = (纬度°, 经度°, 高程m, 北方向偏角°)；弧垂 f = K·L²/4（K=γ/2σ）。
    返回 [{"start": [x,y,z], "end": [x,y,z]}, ...]，z 为高程。
    """
    lat1, lon1, h1, _ = blha_a
    lat2, lon2, h2, _ = blha_b
    dx = (lon2 - lon1) * 111320.0 * math.cos(math.radians((lat1 + lat2) / 2.0))
    dy = (lat2 - lat1) * 110540.0
    span = math.hypot(dx, dy)
    sag = kvalue * span * span / 4.0
    pts = []
    for i in range(samples + 1):
        t = i / samples
        x = dx * t
        y = dy * t
        z = h1 + (h2 - h1) * t - 4.0 * sag * t * (1.0 - t)
        pts.append((round(x, 3), round(y, 3), round(z, 3)))
    return [{"start": list(a), "end": list(b)} for a, b in zip(pts, pts[1:])]


def parse_mod(text: str) -> list:
    """按内容自动分派：XML（变电图元）或文本（线路杆塔线架）。"""
    stripped = text.lstrip("\ufeff \t\r\n")
    if stripped.startswith("<"):
        return parse_mod_substation(stripped)
    return parse_mod_tower(text)


def parse_mod_tower(text: str) -> list:
    """杆塔线架：P 节点表 + r 杆件 → LINE 图元集合。"""
    nodes = {}
    prims = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line:
            continue
        parts = [x.strip() for x in line.split(",")]
        tag = parts[0].upper()
        try:
            if tag == "P" and len(parts) >= 5:
                nodes[int(parts[1])] = (float(parts[2]), float(parts[3]), float(parts[4]))
            elif tag == "R" and len(parts) >= 3:
                a, b = int(parts[1]), int(parts[2])
                pa, pb = nodes.get(a), nodes.get(b)
                if pa and pb:
                    prims.append(Primitive(
                        name=parts[3] if len(parts) > 3 and parts[3] else "杆件",
                        type=PrimitiveType.LINE,
                        params={"start": list(pa), "end": list(pb)},
                        material="steel",
                    ))
        except ValueError:
            continue
    return prims


def parse_mod_substation(text: str) -> list:
    """变电 XML：Entity(simple) → 参数化图元；Entity(boolean) → 布尔结构记录。

    布尔运算第一版不做真实 CSG（需网格引擎），解析为组合图元记录：
    params 携带 op/entity1/entity2，渲染按并集近似（保留参与图元）。
    """
    stripped = text.lstrip("\ufeff \t\r\n")
    if not stripped.startswith("<"):
        return []
    try:
        # 规范中多个 Entity 平铺无单一根节点，包裹伪根解析
        root = ET.fromstring("<Root>" + stripped + "</Root>")
    except ET.ParseError:
        return []

    def _matrix_pos(entity):
        transform = entity.find("TransformMatrix")
        if transform is not None and transform.get("Value"):
            try:
                m = [float(x) for x in transform.get("Value").replace(",", " ").split()]
                if len(m) >= 12:
                    return [m[3], m[7], m[11]]
            except ValueError:
                pass
        return [0.0, 0.0, 0.0]

    def _color(entity, default="#888888"):
        color = entity.find("Color")
        if color is None:
            return default
        try:
            return "#{:02X}{:02X}{:02X}".format(
                int(color.get("R", "136")), int(color.get("G", "136")), int(color.get("B", "136"))
            )
        except ValueError:
            return default

    prims = []
    for entity in root.iter("Entity"):
        etype = (entity.get("Type") or "simple").lower()
        pos = _matrix_pos(entity)
        if etype == "boolean":
            bool_node = entity.find("Boolean")
            if bool_node is None:
                continue
            prims.append(Primitive(
                name=f"Boolean({bool_node.get('Type', 'Union')})",
                type=PrimitiveType.BOX,
                params={
                    "op": bool_node.get("Type", "Union"),
                    "entity1": bool_node.get("Entity1", ""),
                    "entity2": bool_node.get("Entity2", ""),
                },
                position=pos,
                color=_color(entity),
            ))
            continue
        color_hex = _color(entity)
        for child in entity:
            if child.tag not in XML_PRIMITIVES:
                continue
            ptype, keymap = XML_PRIMITIVES[child.tag]
            params = {}
            for xml_key, param_key in keymap.items():
                raw = child.get(xml_key)
                if raw is None:
                    continue
                try:
                    params[param_key] = float(raw)
                except ValueError:
                    continue
            prims.append(Primitive(
                name=child.tag,
                type=ptype,
                params=params,
                position=pos,
                color=color_hex,
            ))
    return prims
