# ADX Account Isolated Collector 项目交接文档

更新时间：2026-06-03  
项目路径：`D:\code\adx-account-isolated-collector`

## 1. 项目目标

本项目是一个独立于旧 `adxmanager` 项目的新系统，目标是实现：

- 一个 AdX/Ad Manager 账号对应一个独立 OAuth 应用
- 一个账号对应一个独立 collector 实例
- 一个账号对应一个固定代理和固定出口 IP
- collector 负责拉取该账号数据并主动回传到 control plane
- control plane 负责账号、实例、代理、任务、结果汇总和状态展示

当前项目已经有可运行的 control plane backend、collector runtime、前端控制台，以及本地联调脚本。

---

## 2. 当前整体状态

### 已完成

#### 2.1 control plane backend

已完成：

- 账号管理
- OAuth App 配置管理
- 实例创建
- 代理绑定
- 手动任务创建
- collector runtime config 下发
- collector 心跳
- 任务领取
- batch 接收
- 最终结果查询接口

关键路径：

- [main.py](D:\code\adx-account-isolated-collector\backend\app\main.py)
- [router.py](D:\code\adx-account-isolated-collector\backend\app\collectors\router.py)
- [service.py](D:\code\adx-account-isolated-collector\backend\app\collectors\service.py)
- [ingestion_service.py](D:\code\adx-account-isolated-collector\backend\app\collectors\ingestion_service.py)

#### 2.2 collector runtime

已完成：

- bootstrap settings 读取
- 使用 `instance_token` 向 control plane 拉 runtime-config
- 按 runtime-config 进行代理配置
- egress IP 检查
- 领取任务
- 执行 fetcher
- 提交 batch
- 更新任务状态

关键路径：

- [main.py](D:\code\adx-account-isolated-collector\collector\app\main.py)
- [config.py](D:\code\adx-account-isolated-collector\collector\app\config.py)
- [runtime.py](D:\code\adx-account-isolated-collector\collector\app\runtime.py)
- [control_plane_client.py](D:\code\adx-account-isolated-collector\collector\app\control_plane_client.py)
- [proxy.py](D:\code\adx-account-isolated-collector\collector\app\proxy.py)
- [egress.py](D:\code\adx-account-isolated-collector\collector\app\egress.py)

#### 2.3 前端控制台

已完成两页结构：

- `Operations`
- `Reports`

已接好的区块：

- Accounts
- OAuth Apps
- Instances
- Proxies
- Tasks
- Site Daily
- Account Daily

已接好 OAuth 前端回调页：

- [OAuthCallbackPage.tsx](D:\code\adx-account-isolated-collector\frontend\src\pages\OAuthCallbackPage.tsx)

关键路径：

- [App.tsx](D:\code\adx-account-isolated-collector\frontend\src\App.tsx)
- [router.tsx](D:\code\adx-account-isolated-collector\frontend\src\router.tsx)
- [OperationsPage.tsx](D:\code\adx-account-isolated-collector\frontend\src\pages\OperationsPage.tsx)
- [ReportsPage.tsx](D:\code\adx-account-isolated-collector\frontend\src\pages\ReportsPage.tsx)

#### 2.4 测试和构建

最近一次确认结果：

- backend 测试通过
- collector 测试通过
- frontend 测试通过
- frontend 构建通过

其中本次调试过程中确认：

- `collector`：`17 passed`
- `frontend`：`10 passed`
- `frontend build`：通过

---

## 3. 当前数据库与默认配置

### 默认数据库

backend 默认使用 SQLite：

- [control_plane.db](D:\code\adx-account-isolated-collector\backend\control_plane.db)

配置来源：

- [config.py](D:\code\adx-account-isolated-collector\backend\app\config.py)

默认值：

```python
sqlite:///.../backend/control_plane.db
```

### 当前重要表

- `accounts`
- `oauth_app_configs`
- `collector_instances`
- `proxy_bindings`
- `collector_sync_tasks`
- `collector_ingestion_batches`
- `site_daily_reports`
- `account_daily_reports`

### 一个重要现状

实例 token 目前仍然是明文存储在数据库里，仅用于 MVP 阶段。  
实例创建成功时前端只显示一次 token，列表页不再展示。

---

## 4. 本地启动方式

### 4.1 backend

```powershell
cd D:\code\adx-account-isolated-collector\backend
python -m alembic upgrade head
$env:ADX_COLLECTOR_COLLECTOR_EGRESS_CHECK_URL="http://ipinfo.io/ip"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

说明：

- 这里显式把 egress check URL 改成了 `http://ipinfo.io/ip`
- 原来的默认值是 `https://api.ipify.org`
- 在当前代理条件下，`api.ipify.org` 的 HTTPS 握手不稳定，容易触发 `SSLEOFError`

### 4.2 frontend

```powershell
cd D:\code\adx-account-isolated-collector\frontend
npm install
npm run dev
```

如 backend 不在 8000 端口：

```powershell
$env:VITE_API_BASE_URL="http://127.0.0.1:8010"
npm run dev
```

### 4.3 collector

```powershell
cd D:\code\adx-account-isolated-collector\collector
python -m pip install -r requirements.txt
$env:CONTROL_PLANE_BASE_URL="http://127.0.0.1:8000"
$env:COLLECTOR_INSTANCE_TOKEN="实际实例 token"
python -m app.main
```

说明：

- `COLLECTOR_INSTANCE_TOKEN` 必须来自实例创建成功后的返回值，或数据库查询
- collector 运行前会先做 egress 校验，再领取任务

---

## 5. 已经确认打通的链路

### 5.1 OAuth

已确认真实 OAuth 可用：

- 前端生成授权链接
- Google 授权完成
- 回跳前端 callback 页面
- 前端调用 backend 完成 token exchange
- `authorization_status = authorized`
- `refresh_token` 已存储

注意：

- redirect URI 必须按前端端口配置，例如：
  - `http://127.0.0.1:4173/oauth/google/callback`
- 前端 callback 页之前有一个开发模式下的重复提交问题，原因是 React StrictMode 双调用 effect
- 已修复为同一个 `state + code` 只提交一次

相关文件：

- [OAuthCallbackPage.tsx](D:\code\adx-account-isolated-collector\frontend\src\pages\OAuthCallbackPage.tsx)
- [oauth.ts](D:\code\adx-account-isolated-collector\frontend\src\lib\oauth.ts)

### 5.2 代理与 egress

已确认：

- 代理为 `socks5`
- 在本地开启 TUN 模式后，代理供应商官方测试命令可成功返回香港 IP
- collector 在此基础上可以通过 egress 校验

当前注意事项：

- 如果本地不是 TUN/全局模式，代理供应商可能会拒绝连接
- `https://api.ipify.org` 在当前代理下不稳定，应使用 `http://ipinfo.io/ip`

### 5.3 真实 Ad Manager API 接入

已确认：

- OAuth access token refresh 正常
- `reports.create` 已成功
- `reports.run` 已成功

这里曾经修过两个 Beta REST 请求体问题：

1. 创建 report 时不应包一层 `"report": {...}`
2. `reportDefinition` 中不应传 `adUnitView`

相关文件：

- [admanager_api.py](D:\code\adx-account-isolated-collector\collector\app\admanager_api.py)
- [test_runtime.py](D:\code\adx-account-isolated-collector\collector\tests\test_runtime.py)

---

## 6. 当前最关键的阻塞点

### 结论

**当前技术链路已基本跑通，但“真实报表口径”实现方向不对。**

现象：

- 前端任务状态显示 `succeeded`
- 但 `collector_ingestion_batches` 没有新增记录
- `site_daily_reports` / `account_daily_reports` 没有真实新数据

### 证据

已直接用当前真实账号和 OAuth 凭证验证：

#### 当前实现使用的定义

- 维度：
  - `URL_ID`
  - `URL`
- 指标：
  - `AD_SERVER_RESPONSES_SERVED`
  - `AD_SERVER_IMPRESSIONS`
  - `AD_SERVER_CLICKS`
  - `AD_SERVER_REVENUE_WITHOUT_CPD`
  - `AD_SERVER_AVERAGE_ECPM_WITHOUT_CPD`

#### 真实结果

- `create report` 成功
- `run report` 成功
- `fetchRows` 成功
- **返回 0 行**

即使改成：

- `DATE` 维度 + 同一组 `AD_SERVER_*` 指标

结果也仍是 **0 行**

### 根因判断

当前系统接入的是：

- **Ad Manager API (Beta) REST reports**
- 且使用的是 **`AD_SERVER_*` 指标家族**

但用户当前想拉的是：

- **AdX / Ad Exchange 数据**

这两者口径不一致。

换句话说：

- 系统“技术上成功”
- 但“业务报表口径错误”

所以才会出现：

- 任务成功
- 报表无数据

---

## 7. 已验证过但不应继续走的方向

### 7.1 继续在当前 Beta REST 上硬试 `AD_EXCHANGE_*`

已直接试过下列 Beta REST 枚举：

- `AD_EXCHANGE_URL_ID`
- `AD_EXCHANGE_URL`
- `AD_EXCHANGE_AD_REQUESTS`
- `AD_EXCHANGE_MATCHED_REQUESTS`
- `AD_EXCHANGE_ESTIMATED_REVENUE`

结果：

- Google Beta REST 直接返回 `INVALID_ARGUMENT`

这说明：

**不能简单把 SOAP/迁移文档里的 `AD_EXCHANGE_*` 名称原样塞给当前 Beta REST。**

### 7.2 继续怀疑前端、写库或任务状态

现阶段不应该继续在以下方向浪费时间：

- 前端报表页
- backend 最终表投影
- batch 接收逻辑
- OAuth 授权链

因为已经明确证明：

- 没有任何 rows 从 Google 返回
- 所以根本没有 batch 可以入库

---

## 8. 推荐给下一位开发者的正确方向

### 优先级最高：切换真实 fetcher 实现方向

建议把当前真实 fetcher 从：

- `Ad Manager API (Beta) REST reports`

切到：

- **Ad Manager SOAP ReportService**

原因：

- Google 官方 AdX Seller REST 迁移文档给出的映射更偏向 SOAP 报表体系
- 当前项目目标是拉取 AdX/Ad Exchange 数据，而不是普通 `AD_SERVER_*` 数据
- 继续在 Beta REST 上试错会持续遇到“口径不对但任务成功”的问题

### 下一位开发者应优先阅读的官方资料

1. AdX 迁移文档  
   [Migrating from AdX Seller REST API](https://developers.google.com/ad-manager/api/adx_reporting_migration)

2. Ad Manager SOAP Reporting  
   [Reporting Basics (SOAP)](https://developers.google.com/ad-manager/api/reporting)

3. 当前项目已有的设计文档  
   [2026-05-22-adx-account-isolated-collector-plan-a-design.md](D:\code\adx-account-isolated-collector\docs\superpowers\specs\2026-05-22-adx-account-isolated-collector-plan-a-design.md)

### 建议的实现顺序

1. 保留现有 control plane / collector runtime / frontend，不推倒重来
2. 把真实 fetcher 从 Beta REST 抽换为 SOAP ReportService 实现
3. 先用最小可验证的 AdX 维度/指标组合跑通
4. collector 能产出至少一批真实 rows 后，再确认：
   - `collector_ingestion_batches`
   - `site_daily_reports`
   - `account_daily_reports`
5. 最后再补更准确的网站/域名映射口径

---

## 9. 代码层建议关注点

### 9.1 真实 fetcher 的切换入口

当前 fetcher 入口：

- [fetcher.py](D:\code\adx-account-isolated-collector\collector\app\fetcher.py)

目前真实实现类：

- `AdManagerRestReportFetcher`

下一步最合理的改法：

- 保留 `StubFetcher`
- 新增一个 `AdManagerSoapReportFetcher`
- 通过 `fetch_mode` 或新 runtime 配置字段切换

### 9.2 当前投影逻辑可以先保留

文件：

- [ingestion_service.py](D:\code\adx-account-isolated-collector\backend\app\collectors\ingestion_service.py)

现状：

- 只要 rows 回来，并且 schema 能被标准化，投影逻辑基本是可用的
- 当前真正缺的是“正确的真实 rows 来源”

### 9.3 前端无需优先修改

前端现在已经足够支撑下一阶段开发：

- 可以创建账号、OAuth、实例、代理、任务
- 可以看任务状态
- 可以看最终结果

所以前端当前不是瓶颈。

---

## 10. 本地常用排查命令

### 查询实例 token

```powershell
cd D:\code\adx-account-isolated-collector\backend
@'
import sqlite3
conn = sqlite3.connect("control_plane.db")
cur = conn.cursor()
cur.execute("select id, account_id, name, instance_token from collector_instances order by id desc")
for row in cur.fetchall():
    print(row)
conn.close()
'@ | python
```

### 查询任务状态

```powershell
cd D:\code\adx-account-isolated-collector\backend
@'
import sqlite3
conn = sqlite3.connect("control_plane.db")
cur = conn.cursor()
cur.execute("select id, account_id, collector_instance_id, report_date, status from collector_sync_tasks order by id desc")
for row in cur.fetchall():
    print(row)
conn.close()
'@ | python
```

### 查询 batch 是否真的回传

```powershell
cd D:\code\adx-account-isolated-collector\backend
@'
import sqlite3
conn = sqlite3.connect("control_plane.db")
cur = conn.cursor()
cur.execute("select id, task_id, account_id, batch_key, row_count, schema_version from collector_ingestion_batches order by id desc")
for row in cur.fetchall():
    print(row)
conn.close()
'@ | python
```

### 查询最终表

```powershell
cd D:\code\adx-account-isolated-collector\backend
@'
import sqlite3
conn = sqlite3.connect("control_plane.db")
cur = conn.cursor()
print("site_daily_reports:")
cur.execute("select id, account_id, report_date, url, responses_served, revenue from site_daily_reports order by id desc limit 20")
for row in cur.fetchall():
    print(row)
print("\\naccount_daily_reports:")
cur.execute("select id, account_id, report_date, responses_served, revenue from account_daily_reports order by id desc limit 20")
for row in cur.fetchall():
    print(row)
conn.close()
'@ | python
```

---

## 11. 给下一位开发者的一句话建议

**不要继续在“前端为什么没数据显示”上打转，也不要继续围绕当前 `AD_SERVER_* + Beta REST` 组合试错。**

当前真正要做的是：

**把真实 AdX 数据抓取实现切到更合适的 Ad Manager SOAP ReportService，并按官方迁移文档重新定义维度与指标。**

