"""命令行入口：python -m egrid.cli ..."""
from __future__ import annotations

import argparse
import json
import sys

from .models import ModelAsset, ModelQuery
from .render import render_model_svg, sample_model_pointcloud
from .seed import seed_demo_models
from .service import ModelService


def _print(obj) -> None:
    if isinstance(obj, list):
        for item in obj:
            print(json.dumps(item.model_dump(mode="json"), ensure_ascii=False, indent=2))
    elif isinstance(obj, ModelAsset):
        print(json.dumps(obj.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="egrid", description="电力矢量模型库 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="新建模型")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--code", default="")
    p_add.add_argument("--type", default="device", choices=["device", "material", "civil", "system", "line", "other"])
    p_add.add_argument("--stage", default="common", choices=["common", "product", "finished", "custom"])
    p_add.add_argument("--specialty", default="electrical_primary", choices=["electrical_primary", "electrical_secondary", "civil", "hvac", "general"])
    p_add.add_argument("--voltage", default="")
    p_add.add_argument("--desc", default="")
    p_add.add_argument("--parent", default=None)
    p_add.add_argument("--level", type=int, default=4)

    p_list = sub.add_parser("list", help="查询模型")
    p_list.add_argument("--keyword", default=None)
    p_list.add_argument("--type", default=None)
    p_list.add_argument("--stage", default=None)
    p_list.add_argument("--voltage", default=None)
    p_list.add_argument("--limit", type=int, default=100)

    p_get = sub.add_parser("get", help="查看模型")
    p_get.add_argument("id")

    p_update = sub.add_parser("update", help="修改模型（JSON patch）")
    p_update.add_argument("id")
    p_update.add_argument("--patch", required=True, help="JSON 字符串或 @文件")

    p_delete = sub.add_parser("delete", help="删除模型")
    p_delete.add_argument("id")

    p_import = sub.add_parser("import", help="导入 GIM/ZIP 模型包")
    p_import.add_argument("path")
    p_import.add_argument("--name", default=None)
    p_import.add_argument("--voltage", default="")

    p_export = sub.add_parser("export", help="导出 GIM/ZIP 模型包")
    p_export.add_argument("id")
    p_export.add_argument("--out", default=None)

    p_version = sub.add_parser("version", help="创建版本快照")
    p_version.add_argument("id")
    p_version.add_argument("--note", default="")

    p_preview = sub.add_parser("preview", help="生成 SVG 预览")
    p_preview.add_argument("id")
    p_preview.add_argument("--out", default=None)

    p_pc = sub.add_parser("pointcloud", help="生成点云采样")
    p_pc.add_argument("id")
    p_pc.add_argument("--count", type=int, default=500)
    p_pc.add_argument("--seed", type=int, default=None)

    p_stats = sub.add_parser("stats", help="模型统计")

    p_seed = sub.add_parser("seed", help="写入内置演示模型")

    args = parser.parse_args(argv)
    svc = ModelService()

    if args.command == "add":
        asset = svc.create_model(ModelAsset(
            name=args.name,
            code=args.code,
            model_type=args.type,
            stage=args.stage,
            specialty=args.specialty,
            voltage_level=args.voltage,
            description=args.desc,
            parent_id=args.parent,
            level=args.level,
        ))
        _print(asset)
    elif args.command == "list":
        query = ModelQuery(
            keyword=args.keyword,
            model_type=args.type,
            stage=args.stage,
            voltage_level=args.voltage,
            limit=args.limit,
        )
        _print(svc.list_models(query))
    elif args.command == "get":
        model = svc.get_model(args.id)
        if not model:
            print("模型不存在", file=sys.stderr)
            return 1
        _print(model)
    elif args.command == "update":
        raw = args.patch
        if raw.startswith("@"):
            with open(raw[1:], encoding="utf-8") as f:
                patch = json.load(f)
        else:
            patch = json.loads(raw)
        model = svc.update_model(args.id, patch)
        if not model:
            print("模型不存在", file=sys.stderr)
            return 1
        _print(model)
    elif args.command == "delete":
        if not svc.delete_model(args.id):
            print("模型不存在", file=sys.stderr)
            return 1
        print("已删除")
    elif args.command == "import":
        _print(svc.import_gim_package(args.path, name=args.name, voltage_level=args.voltage))
    elif args.command == "export":
        print(svc.export_gim_package(args.id, out_path=args.out))
    elif args.command == "version":
        version = svc.add_version(args.id, args.note)
        if not version:
            print("模型不存在", file=sys.stderr)
            return 1
        _print(version)
    elif args.command == "preview":
        model = svc.get_model(args.id)
        if not model:
            print("模型不存在", file=sys.stderr)
            return 1
        svg = render_model_svg(model)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(svg)
            print(args.out)
        else:
            print(svg)
    elif args.command == "pointcloud":
        model = svc.get_model(args.id)
        if not model:
            print("模型不存在", file=sys.stderr)
            return 1
        _print(sample_model_pointcloud(model, count=args.count, seed=args.seed))
    elif args.command == "stats":
        _print(svc.stats())
    elif args.command == "seed":
        _print(seed_demo_models(svc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
