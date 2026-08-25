"""GIM 文件解析器：fam 属性、mod 几何。"""
from .fam import parse_attributes
from .mod import parse_mod, parse_mod_substation, parse_mod_tower

__all__ = ["parse_attributes", "parse_mod", "parse_mod_substation", "parse_mod_tower"]
