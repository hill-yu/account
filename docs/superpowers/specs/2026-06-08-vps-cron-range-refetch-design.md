# VPS cron 范围补跑增强设计

日期：2026-06-08

## 目标

在不改变现有公网接口和 Python 主链路的前提下，增强当前 `deploy/vps/cron/run-fetch.sh`，让它同时支持：

- 默认拉“昨天”
- 手工补跑单个日期
- 手工补跑日期范围

本阶段目标是：
- 不新增公网接口
- 不修改现有 `fetch.php` / `report.php` 语义
- 不改变 cron 默认调用方式
- 继续通过现有 `fetch.php` 逐天提交任务
- 范围模式下遇到单天失败继续执行后续日期
- 最终输出范围汇总，并用 exit code 反映是否存在失败日期

## 推荐方案

推荐方案：增强现有 `run-fetch.sh`

路径保持为：
- `run-fetch.sh -> fetch.php -> Python API -> MySQL`

不采用的方案：
- 新增独立 `run-fetch-range.sh`：会复制大量相同逻辑，后续维护成本更高
- 修改后端接口为“一次提交多个日期”：会扩大改动面，影响现有稳定契约

## 参数设计

脚本支持 3 种调用形式：

1. 不传参数
- 行为：拉昨天
- 示例：
  `/bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh`

2. 传 1 个日期参数
- 行为：只拉这一天
- 示例：
  `/bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh 2026-06-07`

3. 传 2 个日期参数
- 行为：拉闭区间内所有日期
- 示例：
  `/bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh 2026-06-01 2026-06-07`

## 参数校验

第一版固定做以下校验：
- 只允许 0、1、2 个参数
- 日期格式必须为 `YYYY-MM-DD`
- 范围模式下 `start_date <= end_date`
- 不支持 `today`、`yesterday`、`7d` 等相对日期字符串

校验失败时：
- 输出错误信息到 stderr
- 返回非 0 exit code

## 范围执行语义

范围模式下：
- 从 `start_date` 逐天递增到 `end_date`
- 每一天都单独调用一次现有 `fetch.php`
- 每一天都是一条现有单日期任务
- 脚本不尝试等待最终 `report.php success`
- 只判断该日期的触发是否被系统成功“受理”

成功标准仍然是：
- HTTP 200
- JSON 中 `ok=true`
- JSON 中 `status=accepted`

## 失败处理

如果范围中的某一天失败：
- 记录该天失败
- 继续执行后续日期
- 脚本整体不中断

最终：
- 如果全部日期成功受理，exit code 为 `0`
- 只要有任意一天失败，exit code 为非 `0`

## 日志与输出

每一天继续输出单行日志，格式延续当前风格：
- 执行时间
- `account_key`
- `report_date`
- `http_code`
- 原始响应体

示例：

```text
[2026-06-08 11:39:29 CST] account_key=a1 report_date=2026-06-07 http_code=200 body={...}
```

如果是范围模式，脚本末尾额外输出汇总：

```text
[adx-fetch-cron] range summary start=2026-06-01 end=2026-06-07 success_count=6 failed_count=1
[adx-fetch-cron] success_dates=2026-06-01,2026-06-02,2026-06-03,2026-06-05,2026-06-06,2026-06-07
[adx-fetch-cron] failed_dates=2026-06-04
```

如果全部成功，则只要求：
- `failed_count=0`
- 可省略 `failed_dates` 行或输出空值

## 与现有 cron 的兼容性

当前 crontab 继续保持不变：

```cron
0 9 * * * /bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh >> /var/log/adx-fetch-cron.log 2>&1
0 21 * * * /bin/bash /srv/adx-account-isolated-collector/deploy/vps/cron/run-fetch.sh >> /var/log/adx-fetch-cron.log 2>&1
```

因为 cron 仍然是“不传参数”模式，所以增强后不会影响现有自动拉数行为。

## 文档变更

本阶段需要更新：
- `deploy/vps/README.md`
  - 增补单日补跑与范围补跑示例
- `docs/operator-notes.md`
  - 增补范围补跑语义和失败处理说明
- 中台契约文档不需要修改，因为不涉及公网 API 变化

## 成功标准

本阶段完成后，应满足：

1. `run-fetch.sh` 不传参数时仍然正常拉“昨天”
2. `run-fetch.sh YYYY-MM-DD` 可成功补跑单天
3. `run-fetch.sh START END` 可逐天补跑范围
4. 范围内单天失败不会中断后续日期
5. 范围执行结束后会输出 success/failed 汇总
6. cron 默认调用方式无需修改
7. 现有 `fetch.php` / `report.php` 线上行为不受影响

## 不做的内容

本阶段明确不做：
- 后端批量日期接口
- 自动等待 `report.php` 成功
- 自动重试失败日期
- 多账号范围补跑
- 范围模式专用新脚本
- 状态面板或告警
