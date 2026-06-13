# VPS 单账号链路稳定化设计

日期：2026-06-07  
状态：Draft for review

## 1. 背景

当前项目已经完成以下验证：

- 真实 AdX 数据可以通过 Google Ad Manager SOAP 报表链路拉取
- VPS 上的 Python API 可以成功触发拉数并写入 MySQL
- 公网 PHP 触发器 `fetch.php` 已能通过 Cloudflare + VPS 正常触发拉数
- 公网 PHP 读数入口 `report.php` 已具备接入方向，但仍需要和整体服务一起正式收口

当前系统已经具备“能跑通”的能力，但还未完全达到“可长期稳定运营”的状态。下一阶段目标不是继续扩大功能面，而是先把单账号线上链路稳定化，同时为后续中台读数和多账号固定代理扩展预留边界。

## 2. 阶段目标

本阶段目标是：

**将当前单账号 Cloudflare + VPS + PHP + Python + MySQL 链路，收口成稳定、可重复部署、可排障、可对外读取的在线服务，并预留中台读取与多账号代理扩展接口。**

本阶段完成后，系统应满足：

- 单账号、单日真实 AdX 拉数可稳定执行
- 公网可触发拉数
- 公网可读取指定日期结果
- Python API 以系统服务方式常驻运行
- MySQL 中有明确的运行记录和结果数据
- 后续中台读取无需改动底层数据表
- 后续多账号代理扩展无需推翻现有接口边界

## 3. 范围

### 3.1 本阶段要做

1. Python API 常驻化
- 使用 `systemd` 托管 `uvicorn app.vps_api:app`
- 固定 env 文件读取方式
- 固定服务重启、日志查看、健康检查方式

2. 公网接口定型
- 保留 `GET /ke/fetch.php`
- 保留 `GET /ke/report.php`
- 固定参数风格与返回结构

3. 内部只读接口定型
- 保留 `POST /internal/fetch`
- 新增或固定 `GET /internal/reports/site-daily`

4. 最小运维能力
- 约定健康检查命令
- 约定最近一次拉数结果查看方式
- 约定数据库排查路径

5. 文档收口
- VPS 部署说明
- 公网触发与读数说明
- 运行与排障说明

### 3.2 本阶段不做

- 多账号并发调度
- 账号池管理 UI
- 自动代理分配策略
- 出口 IP 自动核验编排
- 复杂权限与用户体系
- 新前端管理界面

### 3.3 风险接受项

用户明确决定本阶段**不执行 token 轮换**。因此当前触发 token 作为已接受风险保留。文档中应记录这一点，但本阶段不把 token 轮换作为必做任务。

## 4. 目标架构

本阶段架构保持不变，只做稳定化收口：

`Cloudflare -> 公网 PHP -> 127.0.0.1 Python API -> AdX 拉数模块 -> MySQL`

分层职责如下：

### 4.1 Cloudflare

- 提供 DNS、HTTPS 和入口代理
- 不承载拉数逻辑
- 不参与代理分配逻辑

### 4.2 公网 PHP 层

两个脚本：

- `fetch.php`
  - 负责公网触发
  - 校验 token、参数
  - 调本机 Python 内部 API
- `report.php`
  - 负责公网读数
  - 校验 token、参数
  - 调本机 Python 内部读数 API

PHP 层只做薄入口，不承担 OAuth、SOAP、MySQL 查询拼装等核心逻辑。

### 4.3 Python API 层

职责：

- 执行真实拉数
- 持久化运行记录
- 读取指定日期站点结果
- 提供内部 API 给 PHP 调用

这一层继续复用：

- `AdxReportService`
- `AdManagerSoapClient`
- `VpsFetchService`
- `VpsRepository`

### 4.4 MySQL

继续使用当前 4 张表：

- `adx_accounts`
- `adx_account_proxies`
- `adx_fetch_runs`
- `adx_site_daily_reports`

其中：

- `adx_account_proxies` 本阶段仍然主要作为扩展位存在
- `adx_fetch_runs` 是运行状态、排障和未来自动化的重要基础

## 5. 接口设计

## 5.1 公网触发接口

### `GET /ke/fetch.php`

参数：

- `account_key`
- `report_date`
- `token`

成功返回：

- `ok`
- `request_id`
- `run_id`
- `account_key`
- `report_date`
- `row_count`
- `status`

失败返回：

- `ok = false`
- `request_id`（如果能生成）
- `error_code`
- `message`

## 5.2 公网读数接口

### `GET /ke/report.php`

参数：

- `account_key`
- `report_date`
- `token`

成功返回：

- `ok`
- `request_id`
- `account_key`
- `report_date`
- `run_id`
- `row_count`
- `items`

`items` 当前固定包含：

- `site_name`
- `responses_served`
- `impressions`
- `clicks`
- `revenue`
- `ecpm`

失败返回：

- `ok = false`
- `request_id`（如果能生成）
- `error_code`
- `message`

## 5.3 Python 内部接口

### `POST /internal/fetch`

作用：

- 给 `fetch.php` 调用
- 执行真实拉数并写库

### `GET /internal/reports/site-daily`

作用：

- 给 `report.php` 调用
- 从 `adx_site_daily_reports` 读取指定账号、指定日期结果

参数：

- `account_key`
- `report_date`

返回：

- `ok`
- `account_key`
- `report_date`
- `run_id`
- `row_count`
- `items`

## 6. 运行与部署要求

### 6.1 Python API 常驻

必须从临时 `nohup` 运行方式收口到 `systemd` 服务：

- 服务名固定
- WorkingDirectory 固定
- Env 文件路径固定
- Python 解释器固定到虚拟环境

### 6.2 日志与健康检查

必须约定以下检查路径：

- Python API 健康检查：`/health`
- `systemctl status`
- `journalctl`
- MySQL 最近一次 `adx_fetch_runs`

### 6.3 PHP / nginx / php-fpm 约束

必须确保：

- `.php` 路由真实进入 `php-fpm`
- nginx 与 `php-fpm` socket 权限匹配
- Cloudflare 公网入口与本机回环测试一致

## 7. 为阶段 2 和阶段 3 预留的边界

## 7.1 为中台读取预留

原则：

- 中台通过公网只读接口读取数据
- 中台不直接访问 MySQL
- 中台不直接调用 Google API

因此，`report.php` 和 `/internal/reports/site-daily` 的接口风格应从现在开始保持稳定。

未来可以增加：

- 最近一次运行状态接口
- 日期范围查询接口
- 分页与筛选

但不应破坏当前单日查询契约。

## 7.2 为多账号代理扩展预留

原则：

拉数服务内部始终维持下面这条链路：

`account_key -> account config -> proxy route -> report service`

当前：

- `proxy route` 主要返回 `direct`

未来：

- 可以替换为每账号独立代理
- 可以引入 `expected_egress_ip`
- 可以引入代理可用性检查

但不应改变：

- 公网接口参数结构
- 账号主表结构
- 结果表结构
- `VpsFetchService` 的高层调用方式

## 8. 验收标准

本阶段完成后，应满足以下标准：

1. Python API 通过 `systemd` 常驻运行
2. 公网 `fetch.php` 能稳定返回成功 JSON
3. 公网 `report.php` 能稳定返回真实站点结果
4. `adx_fetch_runs` 中能看到成功与失败记录
5. `adx_site_daily_reports` 中能稳定看到目标日期结果
6. Cloudflare 公网访问与 VPS 本机验证行为一致
7. 当前接口契约可直接供中台读取使用
8. 当前代码边界可继续扩展到多账号代理，而无需重构主链路

## 9. 推荐的后续顺序

本阶段完成后，后续顺序建议固定为：

1. 单账号稳定化收口
2. 中台正式读取接入
3. 自动化触发（cron 或任务调度）
4. 多账号 + 固定代理/IP

这样可以避免在底层不稳的情况下过早引入多账号复杂度。
