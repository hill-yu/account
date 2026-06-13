# VPS 单账号固定代理执行节点设计

日期：2026-06-08

## 目标

将当前单账号执行节点从“直连或代理占位”升级为：

- 真正通过账号绑定的固定代理请求 Google
- 在真实拉数前验证该代理的观测出口 IP
- 当代理缺失、代理不可连、代理认证失败或出口 IP 不匹配时，明确失败并阻断拉数
- 保持现有 `fetch.php`、`report.php`、cron 调用方式不变

本阶段定位是：
**单账号执行节点的真实代理出站能力落地**，而不是多账号调度平台建设。

## 背景约束

当前真实业务形态是：
- 一个账号通常对应一个网站入口
- 一个网站/API 节点对应一个执行节点
- 一个执行节点只服务一个账号
- 中台在另一套环境中读取结果并生成报告
- Cloudflare 只负责入口代理，不负责真实拉数

因此，这一阶段的运行模型正式定为：
- 一节点一账号
- 一节点一固定代理
- 一节点一固定出口 IP

代码层面仍可保留 `adx_accounts`、`account_key` 等通用模型，但部署约束上先按单账号节点落地。

## 推荐方案

推荐方案：在现有 VPS 执行节点骨架上接通代理出站，并复用已有 egress/proxy 校验逻辑。

执行路径变为：
- `fetch.php -> vps_api.py -> vps_service.py -> ProxyResolver -> proxy egress check -> AdxReportService -> Google AdX -> MySQL`

不采用的方案：
- 新增第二套专用代理 worker：会重复现有执行链路，增加维护面
- 改造公网接口：当前中台契约已经稳定，不应该被代理实现细节影响
- 单节点多账号运行优先：与当前真实部署形态不一致，会扩大复杂度

## 范围

### 本阶段要做

1. 让 `ProxyResolver` 返回的 `configured_proxy` 真正下传到底层请求链路
2. 让 `AdxReportService` / `AdManagerSoapClient` 支持通过代理访问 Google OAuth 和 SOAP 报表接口
3. 在真实拉数前增加出口 IP 校验
4. 把代理失败和 IP 错配写入 `adx_fetch_runs.error_message`
5. 补测试和文档

### 本阶段不做

- 单节点多账号调度
- 多账号并发执行
- 自动代理 failover
- 一个账号多条备选代理
- 中台跨节点聚合
- 新增公网接口

## 现有可复用边界

当前这些边界已经可以继续复用：

1. `collector/app/vps_models.py`
- `AdxAccount`
- `AdxAccountProxy`
- `AdxFetchRun`
- `AdxSiteDailyReport`

2. `collector/app/vps_service.py`
- 已经有 `account_key -> account -> proxy -> report service -> run result` 主流程

3. `collector/app/vps_proxy_resolver.py`
- 已经有 `direct` 与 `configured_proxy` 的抽象返回

4. `collector/app/egress.py` 与 `collector/app/proxy.py`
- 已有公网 IP 检查与代理基础能力可参考/复用

## 关键改造点

### 1. 代理真正接入 AdX 请求链路

当前 `VpsFetchService._build_report_service(...)` 在 `proxy_route.mode != "direct"` 时会直接失败。

这一阶段需要改成：
- `configured_proxy` 模式下，真实构造一个带代理配置的 `AdxReportService`
- 该代理配置必须继续传入 Google OAuth token 请求
- 同时也必须传入 Google Ad Manager SOAP 请求

### 2. 拉数前的出口 IP 校验

每次真实拉数前，固定执行：
1. 读取账号绑定代理
2. 使用该代理访问公网 IP 检查地址
3. 得到 `observed_egress_ip`
4. 如果配置了 `expected_egress_ip`，则要求完全匹配
5. 不匹配时立即失败，不进入 Google 拉数

这一步是复刻逆向系统“固定代理 + 固定出口 IP”最关键的执行约束。

### 3. 失败语义

以下情况都应明确写入 `adx_fetch_runs`：
- 未配置所需代理
- 代理配置不合法
- 代理请求失败
- 代理认证失败
- 出口 IP 不匹配
- Google 拉数失败

状态要求：
- `status = failed`
- `error_message` 必须可排查

### 4. 不允许直连替代代理账号

如果当前账号配置的是 `configured_proxy`：
- 就必须走该代理
- 不允许失败后静默 fallback 到 `direct`

这条规则必须写死，否则“固定代理隔离”这个设计就失去意义。

## 推荐实现顺序

### 阶段 1：先打通代理参数下传

目标：
- 让底层请求链路真实使用代理

验收：
- 某执行节点配置代理后，真实请求可以通过代理发出

### 阶段 2：再加出口 IP 校验

目标：
- 拉数前先检查代理出口 IP

验收：
- 代理出口符合 `expected_egress_ip` 时才允许拉数
- 不符合时立即失败

### 阶段 3：最后收口失败语义与测试

目标：
- 把代理失败和 IP 错配完整写入运行记录
- 补齐单元测试/集成测试

## 代码边界建议

预计主要修改：
- `collector/app/vps_service.py`
- `collector/app/vps_proxy_resolver.py`
- `collector/app/adx_report_service.py`
- `collector/app/admanager_soap.py`

预计复用或抽取：
- `collector/app/egress.py`
- `collector/app/proxy.py`

文档预计修改：
- `deploy/vps/README.md`
- `docs/operator-notes.md`

## 成功标准

本阶段完成后，应满足：

1. 执行节点配置固定代理后，真实拉数能通过该代理成功执行
2. 拉数前会使用该代理进行出口 IP 检查
3. `expected_egress_ip` 不匹配时，任务会明确失败
4. 失败时不会偷偷 fallback 到直连
5. `fetch.php` / `report.php` / cron 调用方式不变
6. 中台读取契约不需要重写

## 不做的内容

本阶段明确不做：
- 多账号集中调度
- 多代理池轮换
- 自动故障切换
- 节点间统一控制平面
- 中台跨节点聚合逻辑
