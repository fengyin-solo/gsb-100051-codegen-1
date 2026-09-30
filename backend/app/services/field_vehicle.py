"""外业车辆业务规则：派车流转、字段校验与筛选口径都收在这里。

车辆既属于普通业务模块（有自己的台账页），也是今日收口泳道的四条泳道之一，
因此建记录时一并写入采集时间与业务日元数据，跨日资料据此归属。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "field_vehicle"
REQUIRED_FIELDS = ["车辆编号", "车牌号", "车辆类型"]
STATUS_ORDER = ["待命", "外业执行中", "归队待检", "已归队", "停用"]
ACTION_RULES = {"派车外业": "外业执行中", "归队待检": "归队待检", "确认归队": "已归队"}
NEGATIVE_ACTIONS = []


def _now_collected_at() -> str:
    """登记车辆记录时的原始采集时间，精确到分钟。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class FieldVehicleService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        biz_date: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("车牌号", "")) or keyword in str(row.get("车辆编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if biz_date:
            rows = [row for row in rows if row.get("biz_date") == biz_date]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        collected_at = str(values.get("collected_at") or _now_collected_at())
        entry["collected_at"] = collected_at
        # 跨日资料按原始采集时间归属业务日：只取日期部分，不受提交时刻影响。
        entry["biz_date"] = collected_at[:10]
        entry["confirmed"] = False
        entry["returned"] = False
        rows.append(entry)
        self._touch_close_cache()
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"外业车辆 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于外业车辆可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        self._touch_close_cache()
        return entry, f"外业车辆已{action}"

    @staticmethod
    def _touch_close_cache() -> None:
        # 车辆台账变化（派车/归队/登记）改变待办与风险，令收口泳道缓存失效。
        from app.services.close import close_service

        close_service.invalidate_all()
