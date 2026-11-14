# 数据洞察与自助分析平台

面向业务分析师的自助式数据洞察平台。覆盖数据集市构建、自助SQL查询、可视化拖拽分析、分析看板协作、指标异动归因、分析模型沉淀、查询优化建议与数据故事编排的完整洞察链路。

这是一个前后端分离的管理平台：前端 React + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 React + Vite + TypeScript 前端
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
| 数据集市构建 | `mart` | 集市定义 | 集市编号、集市名称、数据源表 |
| 自助SQL查询 | `sqlpad` | 查询脚本 | 脚本编号、脚本名称、SQL语句 |
| 拖拽可视化 | `vizdrag` | 可视化方案 | 方案编号、方案名称、数据源绑定 |
| 看板协作管理 | `collab` | 协作看板 | 看板编号、看板名称、协作成员 |
| 指标异动归因 | `anomaly` | 异动记录 | 记录编号、指标名称、异动方向 |
| 分析模型沉淀 | `model` | 模型注册 | 模型编号、模型名称、模型类型 |
| 查询优化建议 | `opt` | 优化建议 | 建议编号、目标查询、优化类型 |
| 数据故事编排 | `story` | 故事模板 | 模板编号、故事标题、分析主题 |
| 数据准备流水线 | `etl` | 准备任务 | 任务编号、任务名称、输入源 |
| 数据目录检索 | `catalog` | 目录条目 | 条目编号、数据集名称、业务域 |
| 数据采样管理 | `sample` | 采样配置 | 配置编号、数据源名称、采样算法 |
| 同环比分析 | `compare` | 对比方案 | 方案编号、对比指标、基准周期 |
| 分析导出中心 | `export` | 导出任务 | 任务编号、数据源名称、导出格式 |
| 分析告警规则 | `alarm` | 告警规则 | 规则编号、监控指标、告警条件 |
| 数据定时刷新 | `refresh` | 刷新策略 | 策略编号、目标数据集、刷新周期 |
| 查询审计日志 | `audit` | 审计记录 | 记录编号、查询语句、执行人 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 拖拽可视化字段绑定准入

字段绑定的唯一标准集中在 `backend/app/services/vizdrag.py`，规则接口为
`GET /api/vizdrag/rules`，前端候选项完全由该接口驱动：

- 同一数据源下，横轴只允许取维度字段、纵轴只允许取度量字段、分组取分组白名单，
  图表类型同样限定在数据源允许范围内；范围外绑定不允许保存。
- 各位置上限：横轴 1 个、纵轴 1 个、分组 2 个、绑定字段总数 4 个，超过上限不允许保存；
  同一位置内重复绑定（含重复分组）直接拒绝。
- 横纵轴条件冲突（同一字段落到多个位置）时，按唯一优先级
  **纵轴字段 > 横轴字段 > 分组字段** 裁决，冲突即拒绝并提示删除低优先级绑定。
- 发布走完整准入：缺数据源、图表类型、横轴或纵轴任一项都拒绝发布；
  草稿保存只校验已提交绑定，空值表示清空该位置。
- 同一方案编号的校验结论按绑定指纹缓存，只保留最新一份，绑定变更后自动失效。
- 绑定保存带 `expected_version` 乐观版本号，两个编辑者并发修改时只接受先通过条件
  校验的版本，后到的旧版本被拒绝。
- 发布成功后自动同步到分析导出中心（任务编号 `EXPO-VIZD-<方案编号>`，幂等 upsert），
  导出中心按同一套字段规则验收；方案归档时同步任务置为已过期。
  补偿入口：`POST /api/export/sync-vizdrag`。

验收脚本：`backend/tests/test_vizdrag_rules.py`（纯标准库，
`python -I tests/test_vizdrag_rules.py` 运行）。

领域：数据工程
子方向：数仓与数据湖
