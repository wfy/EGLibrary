# 电力矢量模型库 (EGLibrary)

参照国家电网 Q/GDW 11809 / 11810 系列 GIM 标准搭建的电力矢量模型库基础工程。

## 功能

- **模型入库**：手动创建参数化模型、批量导入 GIM/ZIP 模型包、自动解析文件与属性
- **模型查询**：按名称/编码/类型/电压等级/层级/标签检索
- **模型修改**：更新模型属性、几何、文件、层级关系
- **模型导出**：导出为 GIM 风格 ZIP 包（含 CBM/DEV/PHM/MOD 目录与 manifest.json）
- **模型渲染**：SVG 二维预览，参数化基本图元
- **点云采样**：从矢量模型表面生成带标签合成点云，用于电力点云分类训练
- **版本管理**：模型修改前可生成版本快照
- **Web API**：FastAPI REST 接口
- **CLI**：命令行管理

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# CLI 示例
python -m egrid seed                       # 写入内置演示模型
python -m egrid add --name "220kV隔离开关" --code "GW4-220" --voltage "220kV"
python -m egrid list --voltage "220kV"
python -m egrid export <model-id> --out /tmp/model.gim

# Web API
uvicorn egrid.api:app --reload --port 8000
# 打开 http://127.0.0.1:8000/docs
```

## 项目结构

```
EGLibrary/
├── egrid/
│   ├── __init__.py
│   ├── models.py       # 领域模型（GIM 资产/属性/文件/几何）
│   ├── storage.py      # SQLite 仓储层
│   ├── service.py      # 业务服务层（CRUD/导入导出/版本）
│   ├── render.py       # SVG 预览 + 点云采样
│   ├── api.py          # FastAPI 接口
│   └── cli.py          # 命令行
├── tests/              # 单元测试
├── data/               # SQLite 与模型文件存储
└── docs/               # 架构说明
```

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /health | 健康检查 |
| GET | /api/models | 查询模型列表 |
| POST | /api/models | 新建模型 |
| GET | /api/models/{id} | 查看模型 |
| PUT | /api/models/{id} | 修改模型 |
| DELETE | /api/models/{id} | 删除模型 |
| POST | /api/models/import | 导入 GIM/ZIP 包 |
| GET | /api/models/{id}/export | 导出 GIM/ZIP 包 |
| GET | /api/models/{id}/preview.svg | SVG 预览 |
| GET | /api/models/{id}/pointcloud | 点云采样 |
| POST | /api/models/{id}/versions | 创建版本快照 |
| GET | /api/stats | 统计 |

## 说明

- 真实 GIM 文件为 7Z 压缩包且内部格式复杂，本仓库提供 **可移植的 ZIP+manifest 简化载体**，便于开发、测试与二次开发。
- 生产环境建议替换为 PostgreSQL + PostGIS、MinIO/OSS、微服务架构，并实现完整 GIM 合规审查与国网编码。
- 数据默认存储于 `data/eglibrary.db` 和 `data/files/`。
