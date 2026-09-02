"""FastAPI 接口层：电力矢量模型库 Web API。"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .models import ModelAsset, ModelQuery, ModelVersion, PointCloudSample
from .render import POINTCLOUD_QUALITY_COUNTS, render_model_svg, sample_model_pointcloud
from .service import ModelService

INDEX_HTML = Path(__file__).parent / "static" / "index.html"

app = FastAPI(
    title="电力矢量模型库 API",
    description="参照 Q/GDW 11809/11810 系列标准的 GIM 模型库基础服务",
    version="0.1.0",
)

# 默认服务实例；生产可替换为依赖注入
service = ModelService()


@app.get("/", include_in_schema=False)
def index():
    """Web 单页操作流入口。"""
    return FileResponse(INDEX_HTML, media_type="text/html")


class VersionCreate(BaseModel):
    note: str = ""


class ImportedSummary(BaseModel):
    """导入结果摘要（不含几何/属性，工程级导入可达数百模型）。"""
    id: str
    name: str
    category: str = ""
    subcategory: str = ""
    parent_id: Optional[str] = None


class ImportResult(BaseModel):
    created: List[ImportedSummary]


def _summarize(assets):
    return [
        ImportedSummary(
            id=a.id, name=a.name, category=a.category,
            subcategory=a.subcategory, parent_id=a.parent_id,
        )
        for a in assets
    ]


@app.get("/health")
def health():
    return {"status": "ok", "service": "eglibrary", "total": service.stats().get("total", 0)}


@app.get("/api/models", response_model=List[ModelAsset])
def list_models(
    response: Response,
    keyword: Optional[str] = None,
    category: Optional[List[str]] = Query(None),
    subcategory: Optional[List[str]] = Query(None),
    source: Optional[str] = None,
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
        category=category,
        subcategory=subcategory,
        source=source,
        model_type=model_type,
        stage=stage,
        specialty=specialty,
        voltage_level=voltage_level,
        level=level,
        parent_id=parent_id,
        offset=offset,
        limit=limit,
    )
    response.headers["X-Total-Count"] = str(service.repo.count_models(query))
    return service.list_models(query)


class CategoryCreate(BaseModel):
    name: str


@app.get("/api/filter-options")
def filter_options():
    """左侧筛选器选项：大类 / 设备类型 / 电压等级（电压数值排序）。"""
    return service.filter_options()


@app.get("/api/categories")
def list_categories():
    return service.list_categories()


@app.post("/api/categories", status_code=201)
def add_category(payload: CategoryCreate):
    try:
        service.add_category(payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"name": payload.name.strip()}


@app.delete("/api/categories/{name}", status_code=204)
def delete_category(name: str):
    if not service.delete_category(name):
        raise HTTPException(status_code=404, detail="领域不存在")


@app.get("/api/equipment-types")
def list_equipment_types():
    return service.list_equipment_types()


@app.post("/api/equipment-types", status_code=201)
def add_equipment_type(payload: CategoryCreate):
    try:
        service.add_equipment_type(payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"name": payload.name.strip()}


@app.delete("/api/equipment-types/{name}", status_code=204)
def delete_equipment_type(name: str):
    if not service.delete_equipment_type(name):
        raise HTTPException(status_code=404, detail="设备类型不存在")


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
        created = service.import_gim_package(
            tmp_path,
            name=name,
            voltage_level=voltage_level,
            fallback_name=Path(file.filename or "model").stem,
        )
        return ImportResult(created=_summarize(created))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.get("/api/models/{model_id}/export/mesh")
def export_model_mesh(
    model_id: str,
    format: str = Query("obj", pattern="^(obj|stl)$"),
):
    try:
        data, filename, media_type = service.export_mesh(model_id, fmt=format)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/models/{model_id}/export/pointcloud")
def export_model_pointcloud(
    model_id: str,
    format: str = Query("las", pattern="^(las|txt)$"),
    quality: str = Query("medium", pattern="^(low|medium|high|custom)$"),
    count: Optional[int] = Query(None, ge=1, le=100000),
    noise: float = Query(0.0, ge=0.0, le=1.0),
    augment: bool = Query(False),
    seed: Optional[int] = Query(None),
):
    if count is None:
        target_count = POINTCLOUD_QUALITY_COUNTS.get(quality, 2000)
    else:
        target_count = count
    try:
        data, filename, media_type = service.export_pointcloud_dataset(
            model_id,
            fmt=format,
            count=target_count,
            noise=noise,
            augment=augment,
            seed=seed,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
def preview_svg(
    model_id: str,
    view: str = Query("iso", pattern="^(iso|front|side|top)$"),
):
    model = service.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    svg = render_model_svg(model, view=view)
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/api/models/{model_id}/pointcloud", response_model=PointCloudSample)
def pointcloud(
    model_id: str,
    quality: Optional[str] = Query(None, pattern="^(low|medium|high|custom)$"),
    count: Optional[int] = Query(None, ge=1, le=100000),
    seed: Optional[int] = None,
):
    """点云采样：quality=low/medium/high 固定档位；custom 需携带 count。

    兼容旧客户端仅传 count=N（视为 custom）。
    """
    model = service.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    if quality is None and count is None:
        quality = "medium"
    elif quality is None:
        quality = "custom"  # 旧客户端仅传 count
    if quality == "custom":
        if count is None:
            raise HTTPException(status_code=422, detail="自定义采样必须提供 count 参数")
    else:
        if count is not None:
            raise HTTPException(status_code=422, detail="low/medium/high 档位不能携带 count 参数")
        from .render import POINTCLOUD_QUALITY_COUNTS
        count = POINTCLOUD_QUALITY_COUNTS[quality]
    try:
        return service.sample_pointcloud(model_id, count=count, seed=seed)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/models/{model_id}/stl/{stl_path:path}")
def get_stl(model_id: str, stl_path: str):
    """按需返回 STL 部件原始三角面（沿 parent 链向根查找存档文件）。"""
    from .gim.parsers.stl import stl_triangles

    target_model = None
    current_id = model_id
    walked = 0
    while current_id and walked < 10:
        model = service.get_model(current_id)
        if not model:
            break
        target = next(
            (f for f in model.files if f.kind.value == "stl" and f.path.lower() == stl_path.lower()),
            None,
        )
        if target:
            target_model = model
            break
        current_id = model.parent_id
        walked += 1

    if not target_model:
        raise HTTPException(status_code=404, detail="STL 文件不存在")
    file_path = Path(service.storage_dir) / target_model.id / target.path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="STL 文件缺失")
    triangles = [
        [[round(x, 4) for x in v] for v in tri]
        for tri in stl_triangles(file_path.read_bytes())
    ]
    return {"path": target.path, "count": len(triangles), "triangles": triangles}


@app.get("/api/stats")
def stats():
    return service.stats()
