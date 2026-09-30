# 地质勘探数据管理平台

面向地质勘探的钻孔编录、岩心取样、物探数据、化探分析、测绘资料与储量估算的综合数据管理后台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 今日收口泳道 | （看板）`/` | 钻孔/岩心/地层/外业车辆 | 待办、风险、退回补录、业务日批次 |
| 钻孔编录 | `borehole` | 钻孔 | 钻孔编号、勘探区、孔口坐标 |
| 岩心管理 | `core` | 岩心样本 | 岩心编号、所属钻孔、取样深度起 |
| 地层划分 | `stratigraphy` | 地层单元 | 单元编号、钻孔编号、地层名称 |
| 外业车辆 | `field_vehicle` | 外业车辆 | 车辆编号、车牌号、责任司机、出车时间 |
| 地球物理 | `geophysics` | 物探测线 | 测线编号、勘探区、物探方法 |
| 化探分析 | `geochem` | 化探样品 | 样品编号、样品类型、采样点位 |
| 化验数据 | `assay` | 化验结果 | 化验编号、样品编号、元素名称 |
| 地质填图 | `mapping` | 填图单元 | 图幅编号、图幅名称、比例尺 |
| 测绘控制 | `survey_point` | 控制点 | 点号、点类型、坐标X |
| 钻探日志 | `drilling_log` | 钻探记录 | 日志编号、钻孔编号、钻进深度 |
| 储量估算 | `reserve` | 矿体块段 | 块段编号、矿体名称、面积 |
| 样品登记 | `sample_registry` | 送检样品 | 送检编号、样品名称、采样位置 |
| 勘探设备 | `equipment` | 勘探仪器 | 仪器编号、仪器名称、型号规格 |
| 水文地质 | `hydro` | 水文观测点 | 观测编号、观测类型、所在钻孔 |
| 剖面编录 | `section` | 实测剖面 | 剖面编号、剖面名称、剖面长度 |
| 地质报告 | `geological_report` | 勘探报告 | 报告编号、勘探区、报告类型 |
| 遥感解译 | `remote` | 遥感数据 | 数据编号、数据源、分辨率 |
| 矿产评价 | `mineral` | 矿化线索 | 线索编号、勘探区、矿种 |
| 环境地质 | `environmental` | 环境调查点 | 调查编号、调查区域、灾害类型 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 今日收口泳道口径

首页“今日收口泳道”（`backend/app/services/close.py`）横向展示**钻孔、岩心、地层、外业车辆**
四条泳道的待办与风险数量，相关约定如下：

- **业务日归属**：四条泳道的记录带 `collected_at`（原始采集时间）与据此推导的 `biz_date`。
  跨日资料按原始采集时间归属业务日，不受提交/处置时刻影响；接口可用 `biz_date` 查询指定业务日。
- **既有确认成果留档**：`confirmed=true` 的成果按原口径留档，不进待办、不进风险，也不参与收口计数。
- **风险格处置**：从风险格可“退回补录”或“现场整改”。退回补录会同时同步
  ①对应模块台账（写 `disposition` 留痕、置 `pending/returned`）、②待办清单（记录回到待办）、
  ③概览看板（风险 -1、待办 +1）；现场整改则当场清除风险、不进待办。
- **汇总缓存与批次状态**：按业务日缓存泳道汇总，台账变更即令缓存失效；批次带 `version`，
  每次处置/收口成功都推进版本并重建缓存，收口时落盘 `snapshot`。
- **并发收口**：提交收口携带 `expected_version` 做乐观并发控制，另用 `request_id` 做幂等。
  两个账号同时收口时，先提交者成功并推进版本，后发起者收到 `409` 冲突提示；
  同一 `request_id` 的重试回放首次结果，不会重复计数。仍有未处置风险时收口默认被拦截。
- 接口：`GET /api/close/board`、
  `POST /api/close/lanes/{module}/risks/{id}/dispose`、`POST /api/close/batch`。
