# 定时自动拉数设计

日期：2026-06-08

## 目标

为当前已经跑通的 VPS 单账号公网拉数链路补一层最小可用的自动化触发能力。

本阶段目标是：
- 不新增公网接口
- 不修改现有 `fetch.php` / `report.php` 语义
- 不引入新的调度服务
- 只通过 VPS `cron` 定时调用现有 `fetch.php`
- 默认每天北京时间 `09:00` 和 `21:00` 自动触发一次
- 默认拉取“昨天”的数据
- 失败先写日志，不做复杂重试

## 推荐方案

推荐方案：VPS `cron` 直接调用现有 `fetch.php`

路径：
- `cron -> run-fetch.sh -> fetch.php -> Python API -> MySQL`

优点：
- 复用现有公网契约最多
- 改动最小
- 部署最简单
- 不会引入新的接口和状态语义

不采用的方案：
- `cron` 直接打 Python 内部 API：绕开现有稳定公网链路，不利于统一行为
- `systemd timer`：可做，但比 `cron` 更重，不符合当前“最快成系统”的目标

## 新增文件

本阶段只新增 3 个文件：

1. `deploy/vps/cron/run-fetch.sh`
- VPS 定时触发脚本
- 负责读取配置、计算日期、调用 `fetch.php`、记录日志、返回 exit code

2. `deploy/vps/cron/adx-fetch-cron.env.example`
- cron 配置样板
- 供 VPS 上复制为 `adx-fetch-cron.env`

3. 更新 `deploy/vps/README.md`
- 补 cron 部署步骤
- 补 crontab 示例
- 补日志查看命令

## 配置项

脚本读取一份简单 env 文件，建议位置：
- `/srv/adx-account-isolated-collector/deploy/vps/cron/adx-fetch-cron.env`

建议支持这些配置项：
- `ADX_FETCH_BASE_URL`
  - 示例：`https://api.wangmengmeng.fun`
- `ADX_FETCH_ACCOUNT_KEY`
  - 示例：`a1`
- `ADX_FETCH_TOKEN`
  - 当前公网触发 token
- `ADX_FETCH_TIMEZONE`
  - 默认：`Asia/Shanghai`

第一版不做复杂配置系统，不接数据库，不接多账号列表。

## run-fetch.sh 行为

脚本执行步骤固定为：

1. 加载 env 配置
2. 设置时区（默认 `Asia/Shanghai`）
3. 计算“昨天”的日期，格式为 `YYYY-MM-DD`
4. 组装 `fetch.php` URL
5. 发起 HTTP GET 请求
6. 记录：
   - 执行时间
   - 账号
   - 目标日期
   - HTTP 状态码
   - 原始响应体
7. 判断成功/失败：
   - HTTP 200 且返回 JSON 中 `ok=true` 且 `status=accepted` 视为成功
   - 其他情况视为失败
8. 成功返回 `0`
9. 失败返回非 `0`

## 日期策略

第一版固定策略：
- 每天 `09:00` 拉“昨天”
- 每天 `21:00` 再拉一次“昨天”

这样做的原因：
- 避免当天数据口径波动
- 晚上补跑一次，提高同一天结果成功率

## 日志策略

第一版只做本地文件日志。

推荐通过 crontab 直接重定向到：
- `/var/log/adx-fetch-cron.log`

日志至少要包含：
- 执行时间
- 账号
- 日期
- HTTP 状态
- 原始响应体

第一版不做：
- 独立日志轮转逻辑
- 结构化日志平台接入
- 自动告警

## 失败处理

第一版失败处理原则：
- 本次失败只写日志
- 不自动重试
- 下一次 cron 正常继续执行

不做：
- 指数退避
- 同日多次自动补偿
- 告警推送

## crontab 方案

推荐由 VPS 用户手工安装 crontab，示例：

```cron
0 9 * * * /bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh >> /var/log/adx-fetch-cron.log 2>&1
0 21 * * * /bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh >> /var/log/adx-fetch-cron.log 2>&1
```

脚本内部会固定时区，因此不依赖服务器系统时区必须是北京时间。

## 成功标准

这一阶段完成后，应满足：

1. VPS 上存在可执行的 `run-fetch.sh`
2. cron 配置可以每天北京时间 `09:00`、`21:00` 触发
3. 脚本默认拉“昨天”的数据
4. 成功时 `fetch.php` 返回 `accepted`
5. 失败时日志可排查
6. 不影响现有 `fetch.php` / `report.php` 线上行为

## 不做的内容

本阶段明确不做：
- 多账号轮询
- 代理分账号调度
- 自动重试
- 告警通知
- 状态面板
- 新增中台接口
- 修改现有 PHP/Python 主业务逻辑
