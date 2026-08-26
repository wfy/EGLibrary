"""SQLite 存储层：模型资产、属性、文件、几何、版本历史。"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import List, Optional

from .models import (
    Geometry,
    ModelAsset,
    ModelAttribute,
    ModelFile,
    ModelQuery,
    ModelVersion,
    new_guid,
    utcnow,
)


def _json_dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _json_loads(text: str):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


class ModelRepository:
    """基于 SQLite 的轻量级模型库仓储。生产环境可替换为 PostgreSQL + PostGIS。"""

    def __init__(self, db_path: str = "data/eglibrary.db"):
        self.db_path = db_path
        if self.db_path != ":memory:":
            parent = os.path.dirname(os.path.abspath(db_path))
            Path(parent).mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS models (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    code TEXT DEFAULT '',
                    model_type TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    specialty TEXT NOT NULL,
                    voltage_level TEXT DEFAULT '',
                    version TEXT DEFAULT 'v1',
                    description TEXT DEFAULT '',
                    tags TEXT DEFAULT '[]',
                    attributes TEXT DEFAULT '[]',
                    files TEXT DEFAULT '[]',
                    geometry TEXT DEFAULT '{}',
                    parent_id TEXT,
                    level INTEGER DEFAULT 4,
                    created_at TEXT,
                    updated_at TEXT,
                    created_by TEXT DEFAULT 'system',
                    extra TEXT DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_models_name ON models(name);
                CREATE INDEX IF NOT EXISTS idx_models_type ON models(model_type);
                CREATE INDEX IF NOT EXISTS idx_models_voltage ON models(voltage_level);

                CREATE TABLE IF NOT EXISTS model_versions (
                    id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    note TEXT DEFAULT '',
                    created_at TEXT,
                    data TEXT DEFAULT '{}',
                    FOREIGN KEY(model_id) REFERENCES models(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                );
                """
            )
            # 旧库迁移：models 表补 category 列
            cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(models)")}
            if "category" not in cols:
                self._conn.execute("ALTER TABLE models ADD COLUMN category TEXT DEFAULT ''")
            for col in ("subcategory", "source", "origin"):
                if col not in cols:
                    self._conn.execute(
                        f"ALTER TABLE models ADD COLUMN {col} TEXT DEFAULT ''"
                        if col != "origin" else
                        "ALTER TABLE models ADD COLUMN origin TEXT DEFAULT '{}'"
                    )
            # categories 表补 parent_id（两级分类树）
            ccols = {r["name"] for r in self._conn.execute("PRAGMA table_info(categories)")}
            if "parent_id" not in ccols:
                self._conn.execute("ALTER TABLE categories ADD COLUMN parent_id INTEGER")
            # 分类预置
            existing = self._conn.execute("SELECT COUNT(*) AS c FROM categories").fetchone()["c"]
            if not existing:
                self._conn.executemany(
                    "INSERT INTO categories (name) VALUES (?)",
                    [("变电",), ("输电",), ("电缆",), ("配电",)],
                )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def list_categories(self) -> List[dict]:
        rows = self._conn.execute(
            "SELECT id, name, parent_id FROM categories ORDER BY id"
        ).fetchall()
        return [{"id": r["id"], "name": r["name"], "parent_id": r["parent_id"]} for r in rows]

    def add_category(self, name: str, parent_id: Optional[int] = None) -> int:
        try:
            with self._conn:
                cur = self._conn.execute(
                    "INSERT INTO categories (name, parent_id) VALUES (?, ?)",
                    (name, parent_id),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"分类已存在: {name}") from exc
        return cur.lastrowid

    def create_model(self, asset: ModelAsset) -> ModelAsset:
        asset.id = asset.id or new_guid()
        asset.touch()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO models (
                    id, name, code, category, subcategory, source, origin,
                    model_type, stage, specialty, voltage_level,
                    version, description, tags, attributes, files, geometry,
                    parent_id, level, created_at, updated_at, created_by, extra
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset.id,
                    asset.name,
                    asset.code,
                    asset.category,
                    asset.subcategory,
                    asset.source,
                    _json_dumps(asset.origin),
                    asset.model_type.value,
                    asset.stage.value,
                    asset.specialty.value,
                    asset.voltage_level,
                    asset.version,
                    asset.description,
                    _json_dumps(asset.tags),
                    _json_dumps([a.model_dump() for a in asset.attributes]),
                    _json_dumps([f.model_dump() for f in asset.files]),
                    _json_dumps(asset.geometry.model_dump()),
                    asset.parent_id,
                    asset.level,
                    asset.created_at,
                    asset.updated_at,
                    asset.created_by,
                    _json_dumps(asset.extra),
                ),
            )
        return asset

    def get_model(self, model_id: str) -> Optional[ModelAsset]:
        row = self._conn.execute(
            "SELECT * FROM models WHERE id = ?", (model_id,)
        ).fetchone()
        return self._row_to_asset(row) if row else None

    def list_models(self, query: Optional[ModelQuery] = None) -> List[ModelAsset]:
        q = query or ModelQuery()
        sql = "SELECT * FROM models WHERE 1=1"
        params: list = []

        if q.keyword:
            sql += " AND (name LIKE ? OR code LIKE ? OR description LIKE ?)"
            like = f"%{q.keyword}%"
            params.extend([like, like, like])
        if q.category:
            sql += " AND category = ?"
            params.append(q.category)
        if getattr(q, "subcategory", None):
            sql += " AND subcategory = ?"
            params.append(q.subcategory)
        if getattr(q, "source", None):
            sql += " AND source = ?"
            params.append(q.source)
        if q.model_type:
            sql += " AND model_type = ?"
            params.append(q.model_type.value)
        if q.stage:
            sql += " AND stage = ?"
            params.append(q.stage.value)
        if q.specialty:
            sql += " AND specialty = ?"
            params.append(q.specialty.value)
        if q.voltage_level:
            sql += " AND voltage_level = ?"
            params.append(q.voltage_level)
        if q.level:
            sql += " AND level = ?"
            params.append(q.level)
        if q.parent_id:
            sql += " AND parent_id = ?"
            params.append(q.parent_id)
        if q.tags:
            # SQLite JSON1 可用时按 tags 模糊匹配；这里用简单文本包含。
            for tag in q.tags:
                sql += " AND tags LIKE ?"
                params.append(f"%{tag}%")

        sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([q.limit, q.offset])
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_asset(r) for r in rows]

    def update_model(self, asset: ModelAsset) -> Optional[ModelAsset]:
        if not self.get_model(asset.id):
            return None
        asset.touch()
        with self._conn:
            self._conn.execute(
                """
                UPDATE models SET
                    name = ?, code = ?, category = ?, subcategory = ?, source = ?, origin = ?,
                    model_type = ?, stage = ?, specialty = ?,
                    voltage_level = ?, version = ?, description = ?, tags = ?,
                    attributes = ?, files = ?, geometry = ?, parent_id = ?,
                    level = ?, updated_at = ?, created_by = ?, extra = ?
                WHERE id = ?
                """,
                (
                    asset.name,
                    asset.code,
                    asset.category,
                    asset.subcategory,
                    asset.source,
                    _json_dumps(asset.origin),
                    asset.model_type.value,
                    asset.stage.value,
                    asset.specialty.value,
                    asset.voltage_level,
                    asset.version,
                    asset.description,
                    _json_dumps(asset.tags),
                    _json_dumps([a.model_dump() for a in asset.attributes]),
                    _json_dumps([f.model_dump() for f in asset.files]),
                    _json_dumps(asset.geometry.model_dump()),
                    asset.parent_id,
                    asset.level,
                    asset.updated_at,
                    asset.created_by,
                    _json_dumps(asset.extra),
                    asset.id,
                ),
            )
        return asset

    def delete_model(self, model_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM models WHERE id = ?", (model_id,))
        return cur.rowcount > 0

    def add_version(self, model_id: str, version: ModelVersion) -> ModelVersion:
        version.id = version.id or new_guid()
        if not version.created_at:
            version.created_at = utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO model_versions (id, model_id, version, note, created_at, data)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    version.id,
                    model_id,
                    version.version,
                    version.note,
                    version.created_at,
                    _json_dumps(version.data),
                ),
            )
        return version

    def list_versions(self, model_id: str) -> List[ModelVersion]:
        rows = self._conn.execute(
            "SELECT * FROM model_versions WHERE model_id = ? ORDER BY created_at DESC",
            (model_id,),
        ).fetchall()
        return [
            ModelVersion(
                id=r["id"],
                version=r["version"],
                note=r["note"],
                created_at=r["created_at"],
                data=_json_loads(r["data"]) or {},
            )
            for r in rows
        ]

    def stats(self) -> dict:
        total = self._conn.execute("SELECT COUNT(*) AS c FROM models").fetchone()["c"]
        by_type = {
            r["model_type"]: r["c"]
            for r in self._conn.execute(
                "SELECT model_type, COUNT(*) AS c FROM models GROUP BY model_type"
            ).fetchall()
        }
        return {"total": total, "by_type": by_type}

    @staticmethod
    def _row_to_asset(row: sqlite3.Row) -> ModelAsset:
        return ModelAsset(
            id=row["id"],
            name=row["name"],
            code=row["code"],
            category=row["category"] or "",
            subcategory=row["subcategory"] or "",
            source=(row["source"] if "source" in row.keys() else "manual") or "manual",
            origin=_json_loads(row["origin"]) if "origin" in row.keys() and row["origin"] else {},
            model_type=row["model_type"],
            stage=row["stage"],
            specialty=row["specialty"],
            voltage_level=row["voltage_level"],
            version=row["version"],
            description=row["description"],
            tags=_json_loads(row["tags"]) or [],
            attributes=[ModelAttribute(**a) for a in _json_loads(row["attributes"]) or []],
            files=[ModelFile(**f) for f in _json_loads(row["files"]) or []],
            geometry=Geometry.model_validate_json(row["geometry"]) if row["geometry"] else Geometry(),
            parent_id=row["parent_id"],
            level=row["level"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            created_by=row["created_by"],
            extra=_json_loads(row["extra"]) or {},
        )
