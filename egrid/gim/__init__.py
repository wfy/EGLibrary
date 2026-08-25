"""GIM 解析框架：按 Q/GDW 11809 附录A 解析真实 GIM 专有容器。"""
from .assembler import assemble_gim, parse_gim
from .header import GimHeader, is_gim, parse_header

__all__ = ["GimHeader", "is_gim", "parse_header", "parse_gim", "assemble_gim"]
