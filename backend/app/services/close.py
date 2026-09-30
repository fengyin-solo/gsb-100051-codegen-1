"""今日收口泳道业务规则。

横向汇总钻孔、岩心、地层、外业车辆四条泳道的待办与风险，并负责：
- 业务日归属：跨日资料按记录原始采集时间 collected_at 推导的 biz_date 归属，
  提交/处置时刻不会改变它；既有确认成果（confirmed=True）按原口径留档，
  不进待办、不进风险。
- 风险格处置：从风险格发起“退回补录/现场整改”后，结论同步写回对应模块台账
  （主表行字段）、待办清单（退回的记录回到待办）与概览看板（计数随之刷新）。
- 汇总缓存与批次状态：按业务日缓存泳道汇总，台账变更即令缓存失效；批次带版本号，
  每次成功提交一并推进版本并重建缓存。
- 并发收口：批次用版本号做乐观并发控制，另用 request_id 做幂等。两个账号同时
  收口时，先提交者成功并推进版本，后发起者的 expected_version 过期只能看到
  冲突提示；同一个 request_id 的重试直接回放首次结果，不会重复计数。
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from app.seed import TODAY
from app.store import store

# 泳道顺序固定：钻孔、岩心、地层、外业车辆。
LANES: tuple[tuple[str, str, str], ...] = (
    # (模块名, 泳道标题, 台账主标识字段)
    ("borehole", "钻孔", "钻孔编号"),
    ("core", "岩心", "岩心编号"),
    ("stratigraphy", "地层", "单元编号"),
    ("field_vehicle", "外业车辆", "车辆编号"),
)
LANE_MODULES = {module for module, _, _ in LANES}

CONFIRM_BY_CONCLUSION = {
    "现场整改": True,       # 当场整改到位：风险清除，不回到待办
    "退回补录": False,      # 退回补录：进入待办清单，待补录后再核
}


class ConflictError(Exception):
    """乐观锁版本冲突：后发起的收口/处置需要刷新后重试。"""


class CloseService:
    def __init__(self) -> None:
        # 每个业务日一份批次状态；汇总缓存单独存放，台账变更即失效。
        self._batches: dict[str, dict[str, Any]] = {}
        self._summary_cache: dict[str, dict[str, Any]] = {}
        # request_id -> 首次成功响应快照，保证重试幂等、不重复计数。
        self._idempotency: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # 批次与缓存
    # ------------------------------------------------------------------
    def _get_batch(self, biz_date: str) -> dict[str, Any]:
        batch = self._batches.get(biz_date)
        if batch is None:
            batch = {
                "biz_date": biz_date,
                "status": "收口中",          # 收口中 / 已收口
                "version": 0,
                "closed_by": None,
                "closed_at": None,
                # 提交时落盘的累计口径，便于核对“不重复计数”。
                "snapshot": None,
            }
            self._batches[biz_date] = batch
        return batch

    def _invalidate_cache(self, biz_date: str) -> None:
        self._summary_cache.pop(biz_date, None)

    def invalidate_all(self) -> None:
        """台账经模块自身动作发生变化时调用，令所有业务日缓存失效。"""
        self._summary_cache.clear()

    def _bump_version(self, batch: dict[str, Any]) -> None:
        batch["version"] += 1
        self._invalidate_cache(batch["biz_date"])

    # ------------------------------------------------------------------
    # 泳道汇总（概览看板的数据源）
    # ------------------------------------------------------------------
    def _compute_summary(self, biz_date: str) -> dict[str, Any]:
        lanes: list[dict[str, Any]] = []
        pending_items: list[dict[str, Any]] = []
        risk_items: list[dict[str, Any]] = []
        totals = {"pending": 0, "risk": 0, "total": 0, "returned": 0}

        for module, title, key_field in LANES:
            lane_pending: list[dict[str, Any]] = []
            lane_risk: list[dict[str, Any]] = []
            for row in store.rows(module):
                # 业务日归属完全取原始采集时间推导出的 biz_date。
                if row.get("biz_date") != biz_date:
                    continue
                # 既有确认成果按原口径留档，不进待办/风险。
                if row.get("confirmed"):
                    continue
                card = self._to_card(module, title, key_field, row)
                if row.get("abnormal"):
                    lane_risk.append(card)
                    risk_items.append(card)
                elif row.get("pending"):
                    lane_pending.append(card)
                    pending_items.append(card)
                if row.get("returned"):
                    totals["returned"] += 1

            lane_total = len(lane_pending) + len(lane_risk)
            totals["pending"] += len(lane_pending)
            totals["risk"] += len(lane_risk)
            totals["total"] += lane_total
            lanes.append({
                "module": module,
                "title": title,
                "pending": len(lane_pending),
                "risk": len(lane_risk),
                "total": lane_total,
            })

        return {
            "biz_date": biz_date,
            "lanes": lanes,
            "pending_items": pending_items,
            "risk_items": risk_items,
            "totals": totals,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _to_card(self, module: str, title: str, key_field: str, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "module": module,
            "lane": title,
            "id": row.get("id"),
            "code": row.get(key_field),
            "status": row.get("status"),
            "detail": row.get("车辆状态") or row.get("钻孔状态") or row.get("样本状态") or row.get("岩性组合") or "",
            "collected_at": row.get("collected_at"),
            "biz_date": row.get("biz_date"),
            "returned": bool(row.get("returned")),
        }

    def board(self, biz_date: str | None = None) -> dict[str, Any]:
        """今日收口泳道看板：四泳道的待办/风险数量、明细与批次状态。"""
        biz_date = biz_date or TODAY
        with store.write_lock:
            batch = self._get_batch(biz_date)
            cached = self._summary_cache.get(biz_date)
            if cached is None:
                cached = self._compute_summary(biz_date)
                self._summary_cache[biz_date] = cached
            summary = deepcopy(cached)
            return {
                "biz_date": biz_date,
                "lanes": summary["lanes"],
                "totals": summary["totals"],
                "pending_items": summary["pending_items"],
                "risk_items": summary["risk_items"],
                "batch": self._batch_view(batch),
                "generated_at": summary["generated_at"],
            }

    def _batch_view(self, batch: dict[str, Any]) -> dict[str, Any]:
        return {
            "biz_date": batch["biz_date"],
            "status": batch["status"],
            "version": batch["version"],
            "closed_by": batch["closed_by"],
            "closed_at": batch["closed_at"],
        }

    # ------------------------------------------------------------------
    # 风险格处置：退回补录 / 现场整改
    # ------------------------------------------------------------------
    def dispose_risk(
        self,
        module: str,
        entry_id: int,
        conclusion: str,
        *,
        reason: str | None,
        operator: str | None,
        request_id: str | None,
        expected_version: int | None,
        biz_date: str | None = None,
    ) -> dict[str, Any]:
        if module not in LANE_MODULES:
            raise ValueError(f"模块「{module}」不在今日收口泳道内")
        if conclusion not in CONFIRM_BY_CONCLUSION:
            raise ValueError("处置结论只支持「退回补录」或「现场整改」")

        # 幂等：同 request_id 的重试直接回放首次结果，绝不重复计数。
        if request_id and request_id in self._idempotency:
            return deepcopy(self._idempotency[request_id])

        with store.write_lock:
            biz_date = biz_date or TODAY
            batch = self._get_batch(biz_date)
            if batch["status"] == "已收口":
                raise ConflictError(f"{biz_date} 已收口，风险格已锁定，不能再处置")
            if expected_version is not None and expected_version != batch["version"]:
                raise ConflictError("批次已被他人更新，请刷新泳道后再处置")

            entry = store.find(module, entry_id)
            if entry is None:
                raise ValueError(f"记录 {entry_id} 不存在或已归档")
            if entry.get("biz_date") != biz_date:
                raise ValueError("该记录不属于当前业务日，不能在此收口泳道处置")
            if entry.get("confirmed"):
                raise ValueError("既有确认成果按原口径留档，不在收口范围内")
            if not entry.get("abnormal"):
                raise ValueError("该记录当前不在风险格，无需处置")

            settle_in_place = CONFIRM_BY_CONCLUSION[conclusion]
            note = reason or ""
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            trace = {"conclusion": conclusion, "reason": note, "operator": operator, "at": stamp}

            # 1) 同步对应模块台账：风险清除，记录处置留痕。
            entry["abnormal"] = False
            entry["disposition"] = trace
            entry.setdefault("disposition_history", []).append(trace)

            if settle_in_place:
                # 现场整改到位：台账标记已整改，不进待办。
                entry["returned"] = False
                entry["settled"] = True
                message = f"{entry.get('车辆编号') or entry.get('钻孔编号') or entry.get('岩心编号') or entry.get('单元编号')} 现场整改完成，风险已清除"
            else:
                # 2) 退回补录：台账置为待补录，并进入待办清单。
                entry["pending"] = True
                entry["returned"] = True
                entry["settled"] = False
                message = f"{entry.get('车辆编号') or entry.get('钻孔编号') or entry.get('岩心编号') or entry.get('单元编号')} 已退回补录，进入待办清单"

            # 3) 推进批次版本并令汇总缓存失效，概览看板计数随下一次读取刷新。
            self._bump_version(batch)
            result = {
                "ok": True,
                "message": message,
                "entry": deepcopy(entry),
                "batch": self._batch_view(batch),
                "summary": self.board_locked(biz_date),
            }
            if request_id:
                self._idempotency[request_id] = deepcopy(result)
            return result

    def board_locked(self, biz_date: str) -> dict[str, Any]:
        """在已持锁的上下文里重建汇总（处置/收口后回传最新看板）。"""
        cached = self._summary_cache.get(biz_date)
        if cached is None:
            cached = self._compute_summary(biz_date)
            self._summary_cache[biz_date] = cached
        return deepcopy(cached)

    # ------------------------------------------------------------------
    # 业务日收口
    # ------------------------------------------------------------------
    def close_batch(
        self,
        *,
        biz_date: str | None = None,
        operator: str | None,
        request_id: str | None,
        expected_version: int | None,
        force: bool,
    ) -> dict[str, Any]:
        if request_id and request_id in self._idempotency:
            return deepcopy(self._idempotency[request_id])

        with store.write_lock:
            biz_date = biz_date or TODAY
            batch = self._get_batch(biz_date)

            if batch["status"] == "已收口":
                # 已收口：同号重试回放成功；不同号则视为后来者的并发收口，给冲突提示。
                if request_id and self._idempotency.get(request_id):
                    return deepcopy(self._idempotency[request_id])
                raise ConflictError(
                    f"{biz_date} 已由 {batch['closed_by']} 于 {batch['closed_at']} 收口，"
                    "你当前看到的是过期看板，请刷新"
                )

            if expected_version is not None and expected_version != batch["version"]:
                raise ConflictError("收口期间数据已被他人更新（批次版本不一致），请刷新泳道后重新提交")

            # 先重建一份最新汇总，确保判定基于当前台账。
            self._invalidate_cache(biz_date)
            summary = self.board_locked(biz_date)
            if summary["totals"]["risk"] > 0 and not force:
                return {
                    "ok": False,
                    "blocked": True,
                    "message": f"仍有 {summary['totals']['risk']} 条风险未处置，不能收口；可先退回补录或现场整改",
                    "batch": self._batch_view(batch),
                    "summary": summary,
                }

            # 提交成功：批次状态、版本、汇总缓存、收口快照一并更新。
            batch["status"] = "已收口"
            batch["closed_by"] = operator
            batch["closed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            batch["snapshot"] = {
                "pending": summary["totals"]["pending"],
                "risk": summary["totals"]["risk"],
                "returned": summary["totals"]["returned"],
                "total": summary["totals"]["total"],
            }
            self._bump_version(batch)            # 收口也推进版本，顺带重建缓存
            fresh = self.board_locked(biz_date)

            result = {
                "ok": True,
                "message": f"{biz_date} 收口完成，提交账号：{operator}",
                "batch": self._batch_view(batch),
                "summary": fresh,
            }
            if request_id:
                self._idempotency[request_id] = deepcopy(result)
            return result


close_service = CloseService()
