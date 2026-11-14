"""拖拽可视化接口：维护可视化方案，覆盖字段绑定准入、校验、发布、嵌入、归档等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.vizdrag import VizdragService

router = APIRouter(prefix="/api/vizdrag", tags=["拖拽可视化"])

service = VizdragService()

LIST_FIELDS = ["方案编号", "方案名称", "数据源绑定", "图表类型", "横轴字段", "纵轴字段", "分组字段", "方案状态"]
STATUSES = ["草稿", "已发布", "已嵌入", "已归档"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按方案编号检索"),
    status: str | None = Query(default=None, description="草稿、已发布、已嵌入、已归档"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按方案编号与状态过滤拖拽可视化列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/rules", response_model=dict)
def binding_rules() -> dict[str, Any]:
    """返回字段绑定准入的唯一标准：数据源允许范围、数量上限与冲突优先级。"""
    return service.binding_rules()


@router.post("/{entry_id}/bindings", response_model=ActionResult)
def save_binding(entry_id: int, payload: EntryPayload) -> ActionResult:
    """保存横轴/纵轴/分组字段与图表类型绑定；超过上限、范围外或冲突时拒绝保存。

    携带 expected_version 时启用乐观并发控制，两个编辑者同时修改只接受先通过条件校验的版本。
    """
    entry, message = service.save_binding(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/validate", response_model=ActionResult)
def validate_binding(entry_id: int, payload: EntryPayload) -> ActionResult:
    """字段绑定准入校验；同一方案编号同一份绑定内容只返回一份结论（命中缓存会带 cached=true）。

    提交的绑定字段作为覆盖值参与校验但不落库；force/full_admission 为控制参数不参与绑定。
    """
    force = bool(payload.values.get("force"))
    full_admission = bool(payload.values.get("full_admission", True))
    override = {
        key: value
        for key, value in payload.values.items()
        if key not in ("force", "full_admission")
    }
    conclusion = service.validate_entry(
        entry_id,
        override=override or None,
        full_admission=full_admission,
        force=force,
    )
    if conclusion is None:
        return ActionResult(ok=False, message=f"可视化方案 {entry_id} 不存在或已归档")
    return ActionResult(
        ok=bool(conclusion["ok"]),
        message=conclusion["conclusion"],
        entry=conclusion,
    )


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出拖拽可视化清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "vizdrag", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条可视化方案明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"可视化方案 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条可视化方案，缺字段或方案编号重复时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=("；".join(missing) if "已存在" in str(missing) else f"缺少必填字段：{'、'.join(missing)}"))
    return ActionResult(ok=True, message="可视化方案已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条可视化方案执行发布方案、嵌入看板、归档方案；不允许的动作会被拦下并说明原因。

    发布前强制走字段绑定准入，发布成功后同步分析导出中心并按字段规则验收。
    """
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
