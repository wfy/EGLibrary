"""FastAPI 接口层：电力矢量模型库 Web API。"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .models import ModelAsset, ModelQuery, ModelVersion, PointCloudSample
from .render import render_model_svg, sample_model_pointcloud
from .service import ModelService

app = FastAPI(
    title="电力矢量模型库 API",
    description="参照 Q/GDW 11809/11810 系列标准的 GIM 模型库基础服务",
    version="0.1.0",
)

# 默认服务实例；生产可替换为依赖注入
service = ModelService()


class VersionCreate(BaseModel):
    note: str = ""


class ImportResult(BaseModel):
    created: List[ModelAsset]


@app.get("/health")
def health():
    return {"status": "ok", "service": "eglibrary", "total": service.stats().get("total", 0)}


@app.get("/api/models", response_model=List[ModelAsset])
def list_models(
    keyword: Optional[str] = None,
    model_type: Optional[str] = None,
    stage: Optional[str] = None,
    specialty: Optional[str] = None,
    voltage_level: Optional[str] = None,
    level: Optional[int] = None,
    parent_id: Optional[str] = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    query = ModelQuery(
        keyword=keyword,
        model_type=model_type,
        stage=stage,
        specialty=specialty,
        voltage_level=voltage_level,
        level=level,
        parent_id=parent_id,
        offset=offset,
        limit=limit,
    )
    return service.list_models(query)


@app.post("/api/models", response_model=ModelAsset, status_code=201)
def create_model(payload: ModelAsset):
    return service.create_model(payload)


@app.get("/api/models/{model_id}", response_model=ModelAsset)
def get_model(model_id: str):
    model = service.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    return model


@app.put("/api/models/{model_id}", response_model=ModelAsset)
def update_model(model_id: str, payload: Dict):
    model = service.update_model(model_id, payload)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    return model


@app.delete("/api/models/{model_id}", status_code=204)
def delete_model(model_id: str):
    if not service.delete_model(model_id):
        raise HTTPException(status_code=404, detail="模型不存在")
    return Response(status_code=204)


@app.post("/api/models/{model_id}/versions", response_model=ModelVersion)
def add_version(model_id: str, payload: VersionCreate):
    version = service.add_version(model_id, payload.note)
    if not version:
        raise HTTPException(status_code=404, detail="模型不存在")
    return version


@app.get("/api/models/{model_id}/versions", response_model=List[ModelVersion])
def list_versions(model_id: str):
    return service.list_versions(model_id)


@app.post("/api/models/import", response_model=ImportResult)
async def import_gim(
    file: UploadFile = File(...),
    name: Optional[str] = Query(None),
    voltage_level: str = Query(""),
):
    suffix = Path(file.filename or "model.gim").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        created = service.import_gim_package(tmp_path, name=name, voltage_level=voltage_level)
        return ImportResult(created=created)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.get("/api/models/{model_id}/export")
def export_model(model_id: str):
    try:
        out_path = service.export_gim_package(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        out_path,
        media_type="application/zip",
        filename=Path(out_path).name,
    )


@app.get("/api/models/{model_id}/preview.svg")
def preview_svg(model_id: str):
    model = service.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    svg = render_model_svg(model)
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/api/models/{model_id}/pointcloud", response_model=PointCloudSample)
def pointcloud(model_id: str, count: int = Query(500, ge=1, le=100000), seed: Optional[int] = None):
    model = service.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    return sample_model_pointcloud(model, count=count, seed=seed)


@app.get("/api/stats")
def stats():
    return service.stats()
