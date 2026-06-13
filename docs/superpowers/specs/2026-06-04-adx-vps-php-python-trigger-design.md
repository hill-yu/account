# AdX VPS PHP 触发式架构设计

## 概述

这份设计定义了当前 AdX 拉数链路的第一版生产化部署形态，目标结构如下：

- Cloudflare 负责 DNS、HTTPS 和反向代理入口
- VPS 承载真实执行栈
- 公网 PHP 入口负责触发任务
- 本机 Python HTTP 服务负责拉取 AdX 数据
- MySQL 存储账号配置、拉取运行记录、代理绑定和归一化报表数据

第一版特意保持最小化：

- 先支持单账号执行即可
- 采用同步触发 -> 同步拉取 -> 同步返回结果
- 复用现有已经跑通的 Python AdX SOAP 模块
- 第一版不要求按账号走不同代理，但现在就预留好接口和表结构

## 目标

- 复用当前已经跑通的 Python AdX 拉数模块，并部署到 VPS
- 支持通过一个公网 PHP 脚本按账号和日期触发一次报表拉取
- 将归一化后的站点级 AdX 数据写入 VPS 本地数据库
- 给触发方返回清晰的成功/失败结果
- 为后续“多账号 + 固定代理/IP”执行模型保留升级路径

## 非目标

- 不把当前本地 control-plane 整套搬到 VPS
- 第一版不支持多账号并发调度
- 第一版不对中台开放读接口
- 第一版不做基于队列的异步 worker
- 第一版不真正落地账号级代理路由

## 架构

### 外部入口层

Cloudflare 只负责入口，不负责拉数逻辑。它终止 HTTPS、代理请求，并把不同子域名路由到 VPS 源站。

### 公网触发层

VPS 上提供一个 PHP 脚本作为公网触发入口，例如：

- `https://api.example.com/ke/fetch.php?account_key=a1&report_date=2026-06-03`

职责：

- 校验请求参数
- 做简单请求鉴权
- 生成请求 id
- 调用本机 Python HTTP 服务
- 将 JSON 结果返回给调用方

PHP 必须保持很薄。它不负责 OAuth 换 token、SOAP 调用、CSV 解析、代理选择或结果归一化。

### Python 执行层

VPS 上运行一个仅监听回环地址的本机 Python 服务，例如：

- `http://127.0.0.1:9100/internal/fetch`

职责：

- 加载账号配置
- 加载代理绑定配置
- 为该账号选择连接策略
- 调用现有 `AdxReportService`
- 归一化并保存结果行
- 持久化执行状态到拉取运行表
- 将机器可读结果返回给 PHP

这层是执行核心，也是未来接入账号级固定代理和中台读接口的扩展点。

### 数据存储层

VPS 本地的 MySQL 存储：

- AdX 账号凭据与元数据
- 可选的账号代理绑定
- 拉取执行记录
- 归一化后的站点级 AdX 行数据

### 未来读取层

后续会再补一个读接口，让中台读取已经落库的结果。这个能力先延期，但当前的存储和执行模型已经为它做好准备，不需要重构拉数路径。

## 数据模型

### `adx_accounts`

用于存储每个 AdX 账号的 API 配置。

建议字段：

- `id`
- `account_key`
- `account_name`
- `network_code`
- `client_id`
- `client_secret`
- `refresh_token`
- `status`
- `created_at`
- `updated_at`

### `adx_account_proxies`

用于存储账号级代理绑定。这是后续“固定 IP 拉数”模型的扩展点。

建议字段：

- `id`
- `account_id`
- `proxy_type`
- `proxy_host`
- `proxy_port`
- `proxy_username`
- `proxy_password`
- `expected_egress_ip`
- `is_active`
- `created_at`
- `updated_at`

第一版可以让这张表为空，或者只放一条默认代理记录。但 Python 执行层从现在开始就要围绕这层接口写，后面才能无痛升级到账号级代理。

### `adx_fetch_runs`

用于记录每一次拉数尝试。

建议字段：

- `id`
- `account_id`
- `report_date`
- `trigger_source`
- `request_id`
- `status`
- `row_count`
- `started_at`
- `finished_at`
- `error_message`

这张表是后续排错和运维的核心审计表。

### `adx_site_daily_reports`

用于存储当前已验证可用的站点级 AdX 日报数据。

建议字段：

- `id`
- `account_id`
- `report_date`
- `site_name`
- `responses_served`
- `impressions`
- `clicks`
- `revenue`
- `ecpm`
- `fetch_run_id`
- `created_at`

建议唯一约束：

- `account_id, report_date, site_name`

这样可以支持按日重跑时安全地“删旧写新”或 upsert。

## 接口设计

### 公网 PHP 触发接口

示例：

- `GET /ke/fetch.php?account_key=a1&report_date=2026-06-03&token=...`

输入：

- `account_key`
- `report_date`
- 触发鉴权 token 或签名

行为：

- 校验输入
- 生成 `request_id`
- 调本机 Python API
- 返回 JSON

成功响应示例：

```json
{
  "ok": true,
  "request_id": "req_20260604_001",
  "run_id": 17,
  "account_key": "a1",
  "report_date": "2026-06-03",
  "row_count": 8,
  "status": "success"
}
```

失败响应示例：

```json
{
  "ok": false,
  "request_id": "req_20260604_001",
  "error_code": "FETCH_ERROR",
  "message": "Google report download failed"
}
```

### 本机 Python 拉数接口

示例：

- `POST /internal/fetch`

输入 JSON：

```json
{
  "account_key": "a1",
  "report_date": "2026-06-03",
  "trigger_source": "php_manual",
  "request_id": "req_20260604_001"
}
```

输出 JSON：

```json
{
  "ok": true,
  "run_id": 17,
  "account_key": "a1",
  "report_date": "2026-06-03",
  "row_count": 8,
  "status": "success"
}
```

这个接口只允许本机访问，不能对公网暴露。

## 运行流程

1. 调用方请求公网 PHP 触发接口。
2. PHP 校验请求并生成 `request_id`。
3. PHP 调用本机 Python 拉数接口。
4. Python 从 `adx_accounts` 加载目标账号。
5. Python 从 `adx_account_proxies` 读取代理配置。
6. Python 在 `adx_fetch_runs` 中插入一条 `running` 记录。
7. Python 执行现有 `AdxReportService` 的站点级 SOAP 拉数。
8. Python 将报表行写入 `adx_site_daily_reports`。
9. Python 将拉取运行状态更新为 `success` 或 `failed`。
10. Python 返回结构化结果给 PHP。
11. PHP 将结构化结果返回给外部调用方。

## 报表语义

第一版复用当前已经验证可用的真实报表语义：

- 维度：
  - `DATE_PT`
  - `SITE_NAME`
- 指标：
  - `AD_EXCHANGE_RESPONSES_SERVED`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE`
  - `AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM`

第一版存的是站点级数据，不是 URL 级数据。这个是可接受的，因为你当前最关心的业务指标已经真实可拉到。

`revenue` 和 `ecpm` 仍然必须在入库前按 micros 归一化。

## 代理扩展设计

架构里已经明确保留了“代理选择层”，位于 Python 执行层和 Google API 出站请求之间。

Python 服务依赖一个很小的代理解析抽象，它需要做到：

- 接收 `account_id` 或 `account_key`
- 返回以下三种之一：
  - 直连
  - 默认共享代理
  - 账号专属代理配置

第一版可以返回直连，或者一条默认代理。但 Python 拉数主路径里不能把这个决定写死在代码里。这样后面升级成“不同账号固定走不同 IP”时，不需要改公网 PHP 契约。

## 错误处理

错误统一分成 4 类。

### `REQUEST_ERROR`

示例：

- 缺少 `account_key`
- `report_date` 非法
- 缺少或错误的触发 token

由 PHP 处理，返回 HTTP 400 或 401。

### `ACCOUNT_CONFIG_ERROR`

示例：

- 账号不存在
- 缺少 `network_code`
- 缺少 OAuth 凭据

由 Python 处理，返回 HTTP 422。如果运行记录已创建，需要把失败信息写入 `adx_fetch_runs`。

### `FETCH_ERROR`

示例：

- refresh token 换取失败
- SOAP 报表执行失败
- 报表下载失败
- 代理连接失败

由 Python 处理，返回 HTTP 502 或 500，并把详细错误写入 `adx_fetch_runs.error_message`。

### `STORE_ERROR`

示例：

- 数据库连接失败
- 行数据写入失败
- 结果持久化异常

由 Python 处理，返回 HTTP 500，并持久化失败原因。

## 部署模型

### Cloudflare

- 负责 DNS 和 HTTPS
- 反向代理到 VPS 源站
- 后续可选加 WAF / 限流

### VPS 服务

- nginx 或 Apache 负责 PHP 公网入口
- PHP-FPM 执行 `fetch.php`
- MySQL 存储账号配置和报表数据
- 一个由 `systemd` 或 `supervisor` 托管的本机 Python HTTP 服务，监听 `127.0.0.1`

## 安全要求

第一版最低要求：

- Python API 只监听回环地址
- 公网 PHP 入口必须要求 token 或签名
- OAuth 密钥只保存在服务端
- PHP 不能泄露 Google 原始凭据
- 数据库日志和应用日志不能直接打出密钥

## 分阶段上线

### 阶段 1：最小生产复刻

- 把 Python 拉数服务部署到 VPS
- 接入 MySQL
- 暴露 PHP 触发入口
- 用一个账号、一天数据跑通端到端

### 阶段 2：中台读取

- 在已存储数据上增加读接口
- 不改现有拉数路径

### 阶段 3：账号级固定 IP 执行

- 启用 `adx_account_proxies`
- 实现按账号选代理
- 可选增加出口 IP 校验与运维工具

## 测试策略

### 单元测试

- Python API 请求校验
- 账号查找与配置校验
- 代理解析行为
- 拉取运行记录与站点结果的持久化逻辑
- 同账号同日期重跑的幂等行为

### 集成测试

- PHP 入口调用 Python loopback API
- Python API 写入 MySQL 表
- VPS 环境下一次真实账号冒烟测试

### 运维验收标准

第一版成功的标准是：

- 公网 PHP 触发器返回成功 JSON
- Python 拉取运行表里出现 `status=success`
- `adx_site_daily_reports` 里出现目标日期的站点级数据
- 同一天重跑不会产生逻辑重复行

## 推荐实现顺序

1. 先把当前可复用的 Python 模块抽成 VPS 导向的服务边界。
2. 加上 MySQL 持久化层，覆盖账号、运行记录和站点级报表。
3. 增加本机 Python HTTP API。
4. 增加薄 PHP 触发器。
5. 部署到 Cloudflare + VPS。
6. 先只接代理抽象层，不立即打开账号级代理执行。
