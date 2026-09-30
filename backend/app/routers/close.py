"""今日收口泳道接口：看板汇总、风险格处置与业务日收口。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import CloseBatchPayload, RiskDispositionPayload
from app.services.close import CloseService, ConflictError, LANE_MODULES

router = APIRouter(prefix="/api/close", tags=["今日收口"])

service = CloseService()


@router.get("/board")
def get_board(biz_date: str | None = Query(default=None, description="业务日 YYYY-MM-DD，默认今天")) -> dict:
    """横向泳道看板：钻孔、岩心、地层、外业车辆的待办与风险数量及明细。"""
    return service.board(biz_date)


@router.post("/lanes/{module}/risks/{entry_id}/dispose")
def dispose_risk(module: str, entry_id: int, payload: RiskDispositionPayload) -> dict:
    """从风险格处置一条记录：退回补录同步台账/待办/概览，现场整改当场清除风险。"""
    if module not in LANE_MODULES:
        raise HTTPException(status_code=404, detail=f"模块「{module}」不在今日收口泳道内")
    try:
        return service.dispose_risk(
            module,
            entry_id,
            payload.conclusion,
            reason=payload.reason,
            operator=payload.operator,
            request_id=payload.request_id,
            expected_version=payload.expected_version,
        )
    except ConflictError as exc:
        # 乐观锁冲突：409，前端据此提示“已被他人更新”，不自动重复计数。
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/batch")
def close_batch(payload: CloseBatchPayload) -> dict:
    """提交业务日收口；版本冲突返回 409，同 request_id 重试回放首次结果。"""
    try:
        return service.close_batch(
            operator=payload.operator,
            request_id=payload.request_id,
            expected_version=payload.expected_version,
            force=payload.force,
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
