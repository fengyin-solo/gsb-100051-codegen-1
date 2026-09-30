"""今日收口泳道接口：看板、风险处置、退回补录待办与批次收口。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ClosingBatchPayload, ClosingDispositionPayload, TodoCompletePayload
from app.services import closing as svc

router = APIRouter(prefix="/api/closing", tags=["今日收口"])


@router.get("/board")
def board(business_day: str = Query(description="业务日 YYYY-MM-DD，默认今天")) -> dict:
    """横向四条泳道（钻孔/岩心/地层/外业车辆）的待办、风险与跨日资料计数。"""
    return svc.get_board(business_day)


@router.post("/dispositions")
def submit_disposition(payload: ClosingDispositionPayload) -> dict:
    """风险格处置：结论同步模块台账、待办清单和概览看板（幂等）。"""
    try:
        return svc.submit_disposition(
            business_day=payload.business_day,
            module=payload.module,
            entry_id=payload.entry_id,
            conclusion=payload.conclusion,
            note=payload.note,
            operator=payload.operator,
            request_id=payload.request_id,
            version=payload.version,
        )
    except svc.ClosingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/todos/{todo_id}/complete")
def complete_todo(todo_id: int, payload: TodoCompletePayload) -> dict:
    """完成退回补录待办；重复完成给冲突提示，重试凭请求编号不重复计数。"""
    try:
        return svc.complete_todo(
            todo_id, operator=payload.operator, request_id=payload.request_id,
        )
    except svc.ClosingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/batch/{business_day}/close")
def close_batch(business_day: str, payload: ClosingBatchPayload) -> dict:
    """批次收口：风险清零后冻结汇总缓存、更新批次状态（并发后者收到 409）。"""
    try:
        return svc.close_day(
            business_day,
            operator=payload.operator,
            request_id=payload.request_id,
            version=payload.version,
        )
    except svc.ClosingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
