# 中台调用示例

日期：2026-06-08

这份文档给中台接入方直接使用，目标是回答 3 个问题：

1. 先调用哪个接口
2. 每个接口传什么参数
3. 各种响应应该怎么解释

当前公网入口：

- `fetch.php`：提交任务
- `report.php`：读取最新成功结果快照

当前示例域名：

- `https://api.wangmengmeng.fun`

## 1. 调用顺序

中台建议固定按下面顺序调用：

1. 调 `fetch.php`
2. 确认返回 `ok=true` 且 `status=accepted`
3. 等待 `2-5` 秒
4. 调 `report.php`
5. 如果 `has_run=true` 且 `run_status=success`，直接读取 `items`
6. 如果 `has_run=false`，继续轮询或等待下一次成功结果生成

一句话理解：

- `fetch.php` 只负责“受理”
- `report.php` 只负责“返回最新成功结果”

## 2. 触发接口

接口地址：

```text
GET /ke/fetch.php
```

完整示例：

```text
https://api.wangmengmeng.fun/ke/fetch.php?account_key=a1&report_date=2026-05-14&token=YOUR_TOKEN
```

参数说明：

- `account_key`
  - 账号唯一标识
- `report_date`
  - 日期，格式固定 `YYYY-MM-DD`
- `token`
  - 当前公网鉴权 token

### 成功响应示例

```json
{
  "ok": true,
  "run_id": 9,
  "account_key": "a1",
  "report_date": "2026-05-14",
  "row_count": 0,
  "status": "accepted",
  "request_id": "req_20260608_031000_02d4024a"
}
```

解释：

- `ok=true`
  - 说明接口层成功
- `status=accepted`
  - 说明任务已受理
- `row_count=0`
  - 在 `fetch.php` 中没有业务意义，不要拿它判断是否成功出数
- `run_id`
  - 这次任务的标识，可用于排查

### 失败响应示例

```json
{
  "ok": false,
  "error_code": "REQUEST_ERROR",
  "message": "invalid token"
}
```

解释：

- 这是接口层失败
- 中台应直接视为“本次触发失败”

## 3. 读数接口

接口地址：

```text
GET /ke/report.php
```

完整示例：

```text
https://api.wangmengmeng.fun/ke/report.php?account_key=a1&report_date=2026-05-14&token=YOUR_TOKEN
```

参数说明和 `fetch.php` 完全一致：

- `account_key`
- `report_date`
- `token`

## 4. `report.php` 字段说明

稳定字段如下：

- `ok`
- `account_key`
- `report_date`
- `has_run`
- `run_status`
- `run_id`
- `row_count`
- `error_message`
- `items`
- `request_id`

其中 `items` 的稳定字段如下：

- `site_name`
- `responses_served`
- `impressions`
- `clicks`
- `revenue`
- `ecpm`

## 5. `report.php` 语义

当前 `report.php` 返回的是：

**该账号、该日期的最新成功结果快照**

它不是“最新任务实时状态接口”。

这点非常重要：

- 如果刚触发，还没有形成新的成功结果，可能返回 `has_run=false`
- 如果之前已经有成功结果，那么即使这次新任务还在跑，`report.php` 仍可能直接返回旧的成功快照

所以中台应这样解释：

- `has_run=true` 且 `run_status=success`
  - 当前已经有成功结果，可以消费
- `has_run=false`
  - 当前还没有成功结果快照可用

## 6. 成功且有数据示例

```json
{
  "ok": true,
  "account_key": "a1",
  "report_date": "2026-05-14",
  "has_run": true,
  "run_status": "success",
  "run_id": 9,
  "row_count": 8,
  "error_message": null,
  "items": [
    {
      "site_name": "jane.ghfkl.com",
      "responses_served": 34,
      "impressions": 33,
      "clicks": 4,
      "revenue": "7.646800",
      "ecpm": "231.721203"
    },
    {
      "site_name": "longan.ghfkl.com",
      "responses_served": 53,
      "impressions": 51,
      "clicks": 4,
      "revenue": "8.871416",
      "ecpm": "173.949341"
    }
  ],
  "request_id": "req_20260608_031005_674956df"
}
```

解释：

- 这是中台最理想的情况
- 直接消费 `items`
- `row_count` 表示结果条数

## 7. 成功但无数据示例

```json
{
  "ok": true,
  "account_key": "a1",
  "report_date": "2026-05-14",
  "has_run": true,
  "run_status": "success",
  "run_id": 10,
  "row_count": 0,
  "error_message": null,
  "items": [],
  "request_id": "req_example_success_empty"
}
```

解释：

- 不是失败
- 只是这一天的最新成功结果没有站点数据

## 8. 当前没有成功结果快照示例

```json
{
  "ok": true,
  "account_key": "a1",
  "report_date": "2026-05-15",
  "has_run": false,
  "run_status": null,
  "run_id": null,
  "row_count": 0,
  "error_message": null,
  "items": [],
  "request_id": "req_example_not_started"
}
```

解释：

- 这不一定代表“没触发过”
- 也可能代表：
  - 当前任务还没产出成功结果
  - 最近一次任务失败，而且没有历史成功结果

中台建议动作：

- 可以继续轮询
- 或在超时后转人工排查

## 9. 推荐轮询策略

第一版建议：

- 触发后等待 `2-5` 秒再查第一次
- 后续每 `3-5` 秒查一次
- 最长轮询 `1-3` 分钟

如果超过这个时间还没有成功结果快照：

- 视为“本次未在预期时间完成”
- 由中台记录超时并进入人工或补偿逻辑

## 10. cURL 示例

### 触发

```bash
curl "https://api.wangmengmeng.fun/ke/fetch.php?account_key=a1&report_date=2026-05-14&token=YOUR_TOKEN"
```

### 查询

```bash
curl "https://api.wangmengmeng.fun/ke/report.php?account_key=a1&report_date=2026-05-14&token=YOUR_TOKEN"
```

## 11. 中台最小判断逻辑

推荐中台按下面顺序判断：

1. 看 `ok`
2. 看 `has_run`
3. 只有在 `has_run=true` 且 `run_status=success` 时，才读取：
   - `row_count`
   - `items`

不要这样做：

- 不要只看 `row_count`
- 不要把 `has_run=false` 直接理解成“任务失败”
- 不要把 `request_id` 当作业务主键

更稳的依赖顺序是：

- 业务结果：`has_run` + `run_status`
- 结果规模：`row_count`
- 结果内容：`items`
- 排查关联：`run_id`

## 12. 当前契约边界

这份接口当前只承诺：

- 单账号
- 单日期
- 站点级日报
- 轮询式读取

当前不承诺：

- 批量日期
- 批量账号
- 分页
- 实时任务状态透传
- 失败原因透传

如果后面你要做“中台正式 SDK”或者“自动拉数”，可以继续在这份文档之上扩展。
