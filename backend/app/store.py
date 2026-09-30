"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。

收口相关的状态（业务日批次、退回补录待办、幂等回执）也挂在这里：
所有写入都走同一把可重入锁，保证两个账号同时收口时批次状态与汇总缓存一致。
"""
from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

from app.seed import SEED_ROWS

# 各模块“原始采集时间”取值字段；岩心、地层没有日期列时按记录号回落到示例日期。
DATE_FIELDS: dict[str, str | None] = {
    "borehole": "开孔日期",
    "core": None,
    "stratigraphy": None,
    "geophysics": "施测日期",
    "geochem": "分析日期",
    "assay": "化验日期",
    "mapping": "野外日期",
    "survey_point": "观测日期",
    "drilling_log": None,
    "reserve": None,
    "sample_registry": "收样日期",
    "equipment": "检定日期",
    "hydro": "观测日期",
    "section": "编录日期",
    "geological_report": "提交日期",
    "remote": "获取日期",
    "mineral": "踏勘日期",
    "environmental": "调查日期",
    "vehicle": "出车日期",
}

# 今日收口泳道覆盖的四个模块（顺序即泳道顺序）。
CLOSING_LANES = ("borehole", "core", "stratigraphy", "vehicle")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._lock = threading.RLock()
        # business_date(YYYY-MM-DD) -> 批次状态与收口后的汇总缓存快照
        self.closing_batches: dict[str, dict[str, Any]] = {}
        # 风险处置（退回补录）产生的待办
        self.closing_todos: list[dict[str, Any]] = []
        # request_id -> 已成功的响应体，重试同号请求时原样返回，不重复计数
        self.idem_results: dict[str, dict[str, Any]] = {}
        # 看板单调版本号：任何处置都会推高，前端用它检测并发覆盖
        self.closing_version = 0
        self._annotate_collected_at()
        self._seed_closing_demo()

    @contextmanager
    def lock(self) -> Any:
        """收口流程的读改写都包在这把锁里，避免并发收口产生交叉写入。"""
        self._lock.acquire()
        try:
            yield
        finally:
            self._lock.release()

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    # ------------------------------------------------------------------
    # 收口示例数据
    # ------------------------------------------------------------------
    def _annotate_collected_at(self) -> None:
        """给既有种子记录补原始采集时间/入库接收时间。

        跨日资料按原始采集时间归属业务日，所以两个时间都要保留；
        没有日期列的模块按记录号回落到 2026-09-01~03，方便切换业务日演示。
        """
        for name, rows in self._tables.items():
            date_field = DATE_FIELDS.get(name)
            for row in rows:
                if "collected_at" in row:
                    continue
                day = str(row.get(date_field, "")) if date_field else ""
                if not _DATE_RE.match(day):
                    day = f"2026-09-{min(int(row.get('id', 1)), 3):02d}"
                row["collected_at"] = f"{day}T08:00:00"
                row["received_at"] = f"{day}T08:30:00"
                row.setdefault(
                    "archived",
                    not row.get("pending", False) and not row.get("abnormal", False),
                )

    def _seed_closing_demo(self) -> None:
        """给四条泳道补今日待办、今日风险和一条跨日资料。

        跨日资料昨天深夜采集、今天凌晨才入库，用来演示“按原始采集时间
        归属业务日”：它不会出现在今日泳道，切到昨天的业务日才能处置。
        """
        today = date.today()
        yesterday = today - timedelta(days=1)

        def stamp(day: date, hm: str) -> str:
            return f"{day.isoformat()}T{hm}:00"

        plans: dict[str, list[dict[str, Any]]] = {
            "borehole": [
                {"status": "待施工", "pending": True, "abnormal": False,
                 "钻孔编号": "BORE-T01", "勘探区": "东翼勘探区", "孔口坐标": "X=4021.5 Y=8830.2",
                 "collected": (today, "08:05"), "received": (today, "08:20")},
                {"status": "钻进中", "pending": True, "abnormal": True,
                 "钻孔编号": "BORE-T02", "勘探区": "东翼勘探区", "孔口坐标": "X=4055.0 Y=8812.7",
                 "collected": (today, "09:10"), "received": (today, "09:40")},
                {"status": "待施工", "pending": True, "abnormal": True,
                 "钻孔编号": "BORE-T03", "勘探区": "北岭勘探区", "孔口坐标": "X=3980.1 Y=9010.0",
                 "collected": (yesterday, "23:20"), "received": (today, "00:15")},
            ],
            "core": [
                {"status": "待编录", "pending": True, "abnormal": False,
                 "岩心编号": "CORE-T01", "所属钻孔": "BORE-T02", "取样深度起": "12.00",
                 "collected": (today, "08:30"), "received": (today, "08:50")},
                {"status": "已编录", "pending": True, "abnormal": True,
                 "岩心编号": "CORE-T02", "所属钻孔": "BORE-T02", "取样深度起": "28.50",
                 "collected": (today, "10:05"), "received": (today, "10:30")},
                {"status": "待编录", "pending": True, "abnormal": True,
                 "岩心编号": "CORE-T03", "所属钻孔": "BORE-T03", "取样深度起": "6.40",
                 "collected": (yesterday, "23:40"), "received": (today, "00:20")},
            ],
            "stratigraphy": [
                {"status": "待划分", "pending": True, "abnormal": False,
                 "单元编号": "STRA-T01", "钻孔编号": "BORE-T02", "地层名称": "第四系覆盖层",
                 "collected": (today, "08:40"), "received": (today, "09:00")},
                {"status": "已划分", "pending": True, "abnormal": True,
                 "单元编号": "STRA-T02", "钻孔编号": "BORE-T02", "地层名称": "灰色灰岩",
                 "collected": (today, "10:20"), "received": (today, "10:50")},
                {"status": "待划分", "pending": True, "abnormal": True,
                 "单元编号": "STRA-T03", "钻孔编号": "BORE-T03", "地层名称": "砂岩夹泥岩",
                 "collected": (yesterday, "23:50"), "received": (today, "00:25")},
            ],
            "vehicle": [
                {"status": "待派车", "pending": True, "abnormal": False,
                 "车辆编号": "VEHI-T01", "车牌号": "吉A·T001", "车辆类型": "皮卡",
                 "驾驶员": "周海涛",
                 "collected": (today, "07:40"), "received": (today, "07:55")},
                {"status": "外业中", "pending": True, "abnormal": True,
                 "车辆编号": "VEHI-T02", "车牌号": "吉A·T002", "车辆类型": "越野车",
                 "驾驶员": "李保田",
                 "collected": (today, "08:15"), "received": (today, "08:45")},
                {"status": "待派车", "pending": True, "abnormal": True,
                 "车辆编号": "VEHI-T03", "车牌号": "吉A·T003", "车辆类型": "面包车",
                 "驾驶员": "未指派",
                 "collected": (yesterday, "22:30"), "received": (today, "00:10")},
            ],
        }

        for module, specs in plans.items():
            table = self.rows(module)
            next_id = max((int(row.get("id", 0)) for row in table), default=0) + 1
            for offset, spec in enumerate(specs):
                collected_day, collected_hm = spec.pop("collected")
                received_day, received_hm = spec.pop("received")
                row: dict[str, Any] = {
                    "id": next_id + offset,
                    "archived": False,
                    "collected_at": stamp(collected_day, collected_hm),
                    "received_at": stamp(received_day, received_hm),
                    **spec,
                }
                if DATE_FIELDS.get(module):
                    row[DATE_FIELDS[module]] = collected_day.isoformat()  # type: ignore[index]
                table.append(row)

    # ------------------------------------------------------------------
    # 旧版运营概览（保留，今日收口泳道上线后不再挂首页）
    # ------------------------------------------------------------------
    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
