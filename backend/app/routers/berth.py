"""泊位计划接口：维护泊位计划，覆盖确认编排、确认靠泊、确认离泊等动作。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.berth import BerthService

router = APIRouter(prefix="/api/berth", tags=["泊位计划"])

service = BerthService()

LIST_FIELDS = ["计划编号", "泊位编号", "靠泊船舶", "计划靠泊时间", "计划离泊时间", "船长", "吃水深度", "计划状态"]
STATUSES = ["待编排", "已编排", "已靠泊", "已离泊"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按计划编号检索"),
    berth: str | None = Query(default=None, description="按泊位编号检索"),
    vessel: str | None = Query(default=None, description="按靠泊船舶检索"),
    date: str | None = Query(default=None, description="筛选该日仍在泊的计划，格式 YYYY-MM-DD"),
    status: str | None = Query(default=None, description="待编排、已编排、已靠泊、已离泊"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按计划编号、泊位、船舶、日期与状态过滤泊位计划列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if date:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="日期筛选格式应为 YYYY-MM-DD") from None
    items, total = service.list_entries(
        keyword=keyword, berth=berth, vessel=vessel, date=date, status=status, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出泊位计划清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "berth", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条泊位计划明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"泊位计划 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条泊位计划，缺字段或编排冲突时说明原因而不是静默丢弃。"""
    entry, problems = service.create_entry(payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message="泊位计划已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """保存编排修改：靠泊时间、靠泊船舶等变更校验通过后落库，看板与列表读同一份数据。"""
    entry, message = service.update_entry(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条泊位计划执行确认编排、确认靠泊、确认离泊；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
