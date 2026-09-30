"""今日收口业务规则。

一条泳道对应一个模块（钻孔 / 岩心 / 地层 / 外业车辆），泳道统计按
**原始采集时间** 归属业务日：跨日入库的资料即使今天才收到，也仍算昨天的
收口内容。既有确认成果（已终孔、已归还、已确认、已归场等终态）按原口径
留档，既不进待办也不进风险。

风险格提交处置结论后，结论同步写回对应模块台账，并联动：
- 退回补录：在待办清单挂一条补录任务，风险仍留在泳道（状态转待补录）；
- 现场核实闭环：风险直接关闭、退出风险计数。

批次收口成功时汇总缓存与批次状态在同一把锁里一并更新；两个账号并发收口
时后发起者收到冲突提示（409），请求凭 request_id 幂等，重试不会重复计数。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.store import CLOSING_LANES, store

# 泳道元数据：模块名 -> 看板文案
LANE_META: dict[str, dict[str, str]] = {
    "borehole": {"key": "borehole", "name": "钻孔", "code": "钻孔编号"},
    "core": {"key": "core", "name": "岩心", "code": "岩心编号"},
    "stratigraphy": {"key": "stratigraphy", "name": "地层", "code": "单元编号"},
    "vehicle": {"key": "vehicle", "name": "外业车辆", "code": "车辆编号"},
}

# 各模块“既有确认成果”的终态：处于这些状态的记录不进收口泳道
FINAL_STATUSES: dict[str, frozenset[str]] = {
    "borehole": frozenset({"已终孔", "已封孔", "已废弃"}),
    "core": frozenset({"已归还"}),
    "stratigraphy": frozenset({"已确认"}),
    "vehicle": frozenset({"已归场", "已报废"}),
}

CONCLUSIONS = ("退回补录", "现场核实闭环")
CONCLUSION_SEND_BACK = "退回补录"
CONCLUSION_VERIFIED = "现场核实闭环"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ClosingError(Exception):
    """收口流程的可读错误，由路由层翻译成对应的 HTTP 状态码。"""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def parse_business_day(day: str) -> str:
    if not _DATE_RE.match(day or ""):
        raise ClosingError("业务日格式应为 YYYY-MM-DD")
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise ClosingError("业务日不是有效日期")
    return day


def _item_brief(row: dict[str, Any], *, module: str, lane_name: str) -> dict[str, Any]:
    """风险格/待办列表里展示的精简条目。"""
    code_field = LANE_META[module]["code"]
    collected_day = str(row.get("collected_at", ""))[:10]
    received_day = str(row.get("received_at", ""))[:10]
    return {
        "module": module,
        "lane": lane_name,
        "entry_id": row.get("id"),
        "code": row.get(code_field) or f"#{row.get('id')}",
        "status": row.get("status"),
        "collected_at": row.get("collected_at"),
        "received_at": row.get("received_at"),
        "business_day": collected_day,
        "late": collected_day != received_day,
        "disposition": row.get("disposition"),
        "disposition_note": row.get("disposition_note"),
        "disposition_operator": row.get("disposition_operator"),
        "disposition_at": row.get("disposition_at"),
    }


def _lane_rows(module: str, business_day: str) -> list[dict[str, Any]]:
    """取归属指定业务日且未终态确认的台账记录（按原始采集时间归属）。"""
    finals = FINAL_STATUSES[module]
    result = []
    for row in store.rows(module):
        if str(row.get("collected_at", ""))[:10] != business_day:
            continue
        if row.get("status") in finals:
            continue
        result.append(row)
    return result


def _build_lane(module: str, business_day: str) -> dict[str, Any]:
    meta = LANE_META[module]
    lanes_rows = _lane_rows(module, business_day)
    risk_items = [_item_brief(row, module=module, lane_name=meta["name"])
                  for row in lanes_rows if row.get("abnormal")]
    pending_items = [_item_brief(row, module=module, lane_name=meta["name"])
                     for row in lanes_rows if row.get("pending")]
    # 一条记录可能同时挂待办和风险，跨日计数按条目去重，避免双计
    counted: set[Any] = set()
    late_count = 0
    for item in [*pending_items, *risk_items]:
        if item["late"] and item["entry_id"] not in counted:
            counted.add(item["entry_id"])
            late_count += 1
    return {
        "module": module,
        "name": meta["name"],
        "pending_count": len(pending_items),
        "risk_count": sum(1 for item in risk_items
                          if item["disposition"] != CONCLUSION_VERIFIED),
        "send_back_count": sum(1 for item in risk_items
                               if item["disposition"] == CONCLUSION_SEND_BACK),
        "disposed_count": sum(1 for item in risk_items if item["disposition"]),
        "late_count": late_count,
        "risk_items": risk_items,
        "pending_items": pending_items,
    }


def _build_snapshot(business_day: str) -> dict[str, Any]:
    lanes = [_build_lane(module, business_day) for module in CLOSING_LANES]
    open_todos = [todo for todo in store.closing_todos
                  if todo.get("business_day") == business_day
                  and not todo.get("done")]
    return {
        "business_day": business_day,
        "batch_status": "进行中",
        "version": store.closing_version,
        "lanes": lanes,
        "todos": open_todos,
        "totals": {
            "pending": sum(int(lane["pending_count"]) for lane in lanes),
            "risk": sum(int(lane["risk_count"]) for lane in lanes),
            "send_back": sum(int(lane["send_back_count"]) for lane in lanes),
            "late": sum(int(lane["late_count"]) for lane in lanes),
        },
    }


def get_board(business_day: str) -> dict[str, Any]:
    """看板：已收口的业务日返回冻结缓存，进行中的业务日实时汇总。"""
    parse_business_day(business_day)
    with store.lock():
        batch = store.closing_batches.get(business_day)
        if batch is not None:
            snapshot = dict(batch["snapshot"])
            # 已收口后退回补录仍允许跟进完成，待办清单读实时数据
            snapshot["todos"] = [todo for todo in store.closing_todos
                                 if todo.get("business_day") == business_day
                                 and not todo.get("done")]
            snapshot["frozen"] = True
            return snapshot
        snapshot = _build_snapshot(business_day)
        snapshot["frozen"] = False
        return snapshot


def _idem_get(scope: str, request_id: str | None) -> dict[str, Any] | None:
    if not request_id:
        return None
    record = store.idem_results.get(f"{scope}:{request_id}")
    if record is not None and record.get("scope") != scope:
        raise ClosingError("请求编号已用于其他类型的操作，请更换后再提交", status_code=409)
    return record.get("response") if record else None


def _idem_put(scope: str, request_id: str | None, response: dict[str, Any]) -> None:
    if request_id:
        store.idem_results[f"{scope}:{request_id}"] = {
            "scope": scope, "response": response,
        }


def _guard_batch_open(business_day: str) -> dict[str, Any] | None:
    batch = store.closing_batches.get(business_day)
    if batch is not None:
        raise ClosingError(
            f"{business_day} 已收口（{batch.get('operator')} 发起），"
            "处置结论请走留档更正流程，不能再改当日泳道",
            status_code=409,
        )
    return batch


def submit_disposition(
    *,
    business_day: str,
    module: str,
    entry_id: int,
    conclusion: str,
    note: str | None,
    operator: str,
    request_id: str | None,
    version: int | None,
) -> dict[str, Any]:
    """风险格提交处置结论：同步台账、待办清单并推高看板版本。"""
    parse_business_day(business_day)
    if module not in LANE_META:
        raise ClosingError(f"「{module}」不属于今日收口泳道")
    conclusion = (conclusion or "").strip()
    if conclusion not in CONCLUSIONS:
        raise ClosingError(f"处置结论只能是：{'、'.join(CONCLUSIONS)}")

    with store.lock():
        cached = _idem_get("disposition", request_id)
        if cached is not None:
            return cached
        _guard_batch_open(business_day)
        if version is not None and version != store.closing_version:
            raise ClosingError("泳道数据已被其他账号更新，请刷新后重试", status_code=409)

        entry = store.find(module, entry_id)
        if entry is None:
            raise ClosingError(f"{LANE_META[module]['name']}记录 {entry_id} 不存在")
        collected_day = str(entry.get("collected_at", ""))[:10]
        if collected_day != business_day:
            raise ClosingError(
                f"该记录按原始采集时间归属 {collected_day} 业务日，"
                f"请在 {collected_day} 的泳道处置",
                status_code=409,
            )
        if entry.get("status") in FINAL_STATUSES[module]:
            raise ClosingError("该记录是已确认成果，按原口径留档，不再进入收口处置")
        if not entry.get("abnormal") and not entry.get("disposition"):
            raise ClosingError("只能对泳道风险格中的记录提交处置结论")

        # 1) 结论写回模块台账（处置结论、处置人、处置时间）
        now = datetime.now().replace(microsecond=0).isoformat()
        entry["disposition"] = conclusion
        entry["disposition_note"] = (note or "").strip() or None
        entry["disposition_operator"] = operator
        entry["disposition_at"] = now

        # 2) 待办清单：退回补录挂待办（同一条重复退回不重复计数）
        if conclusion == CONCLUSION_SEND_BACK:
            existing = next(
                (todo for todo in store.closing_todos
                 if todo.get("module") == module
                 and todo.get("entry_id") == entry_id
                 and not todo.get("done")),
                None,
            )
            if existing is None:
                todo_id = max((int(t.get("id", 0)) for t in store.closing_todos), default=0) + 1
                code = entry.get(LANE_META[module]["code"]) or f"#{entry_id}"
                store.closing_todos.append({
                    "id": todo_id,
                    "business_day": business_day,
                    "module": module,
                    "lane": LANE_META[module]["name"],
                    "entry_id": entry_id,
                    "code": code,
                    "title": f"{LANE_META[module]['name']} {code} 退回补录",
                    "note": entry["disposition_note"],
                    "operator": operator,
                    "created_at": now,
                    "done": False,
                })
        else:
            # 现场核实闭环：若此前退回补录挂过待办，一并关闭
            for todo in store.closing_todos:
                if (todo.get("module") == module
                        and todo.get("entry_id") == entry_id
                        and not todo.get("done")):
                    todo["done"] = True
                    todo["done_at"] = now
                    todo["done_operator"] = operator

        # 3) 推高看板版本，概览看板下次读取即体现最新风险计数
        store.closing_version += 1
        response = _build_snapshot(business_day)
        response["frozen"] = False
        response["action"] = {
            "type": "disposition",
            "module": module,
            "entry_id": entry_id,
            "conclusion": conclusion,
        }
        _idem_put("disposition", request_id, response)
        return response


def complete_todo(
    todo_id: int,
    *,
    operator: str,
    request_id: str | None,
) -> dict[str, Any]:
    """完成一条退回补录待办（已收口业务日的待办也允许跟进）。"""
    with store.lock():
        cached = _idem_get("todo", request_id)
        if cached is not None:
            return cached
        todo = next((item for item in store.closing_todos
                     if int(item.get("id", 0)) == todo_id), None)
        if todo is None:
            raise ClosingError(f"待办 {todo_id} 不存在")
        if todo.get("done"):
            raise ClosingError("该待办已完成，请勿重复提交", status_code=409)
        now = datetime.now().replace(microsecond=0).isoformat()
        todo["done"] = True
        todo["done_at"] = now
        todo["done_operator"] = operator
        response = {"ok": True, "todo": todo}
        _idem_put("todo", request_id, response)
        return response


def close_day(
    business_day: str,
    *,
    operator: str,
    request_id: str | None,
    version: int | None,
) -> dict[str, Any]:
    """批次收口：风险清零后冻结汇总缓存并更新批次状态（同一把锁内完成）。"""
    parse_business_day(business_day)
    with store.lock():
        cached = _idem_get("close", request_id)
        if cached is not None:
            return cached

        existing = store.closing_batches.get(business_day)
        if existing is not None:
            raise ClosingError(
                f"{business_day} 已由 {existing.get('operator')} 收口，"
                "后发起的收口请求不再执行",
                status_code=409,
            )
        if version is not None and version != store.closing_version:
            raise ClosingError("泳道数据已被其他账号更新，请刷新确认风险处置后再收口",
                               status_code=409)

        snapshot = _build_snapshot(business_day)
        if snapshot["totals"]["risk"] > 0:
            raise ClosingError(
                f"仍有 {snapshot['totals']['risk']} 条风险未闭环，"
                "请在风险格完成处置后再收口",
                status_code=409,
            )

        # 汇总缓存与批次状态一并落账，避免外部读到“状态已收口但缓存还是旧值”
        now = datetime.now().replace(microsecond=0).isoformat()
        snapshot["batch_status"] = "已收口"
        snapshot["closed_at"] = now
        snapshot["closed_by"] = operator
        snapshot["frozen"] = True
        store.closing_batches[business_day] = {
            "business_day": business_day,
            "status": "已收口",
            "operator": operator,
            "closed_at": now,
            "version": store.closing_version,
            "snapshot": snapshot,
        }
        _idem_put("close", request_id, snapshot)
        return snapshot
