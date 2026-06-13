# VPS `report.php` 中台读取契约设计

日期：2026-06-07  
状态：Draft for review

## 1. 背景

当前系统已经具备以下能力：

- 真实 AdX 数据可以通过 VPS 上的 Python API 成功拉取并写入 MySQL
- `fetch.php` 可以通过 Cloudflare 公网入口触发异步拉数
- `report.php` 可以返回指定账号、指定日期的最新成功结果快照

在上一阶段改造完成后，系统已经跑通以下链路：

`Cloudflare -> fetch.php -> Python API -> MySQL -> report.php`

现在下一阶段目标不再是“让系统能跑”，而是：

**把 `report.php` 正式收口成中台可依赖的读取契约。**

这样后续无论由你自己还是其他系统来对接，都不需要再依赖聊天记录或临时口头约定来理解字段含义。

## 2. 设计目标

本次设计目标是：

**将公网 `report.php` 正式定义为中台读取“单账号 + 单日期”最新成功站点级日报快照的正式接口，并明确其字段、状态语义、调用顺序和稳定性边界。**

本次设计不新增接口、不修改 URL，只做契约收口。

## 3. 范围

### 3.1 本次要做

1. 明确 `fetch.php` 的正式触发契约
2. 明确 `report.php` 的正式读取契约
3. 明确中台的标准调用顺序
4. 明确状态字段的解释规则
5. 明确当前哪些字段可视为稳定字段
6. 明确这份契约当前的适用边界

### 3.2 本次不做

- 不新增新的中台专用接口
- 不新增批量日期接口
- 不新增批量账号接口
- 不新增分页读取接口
- 不调整 token 传递方式
- 不调整当前站点级结果字段结构

## 4. 总体交互模型

中台通过两个公网 GET 接口与系统交互：

1. `GET /ke/fetch.php`
   - 负责触发拉数任务
   - 不负责返回最终结果

2. `GET /ke/report.php`
   - 负责读取某个账号、某个日期的最新成功结果快照
   - 是中台正式读取接口

因此，中台应把这两个接口理解成：

- `fetch.php` = 提交任务
- `report.php` = 读取最新成功结果快照

## 5. `fetch.php` 正式契约

### 5.1 接口地址

`GET /ke/fetch.php`

示例：

```text
https://api.example.com/ke/fetch.php?account_key=a1&report_date=2026-05-14&token=change-me
```

### 5.2 请求参数

- `account_key`
  - 字符串
  - 用于标识具体账号

- `report_date`
  - 格式固定为 `YYYY-MM-DD`
  - 用于标识目标日期

- `token`
  - 当前阶段使用的公网访问鉴权令牌

### 5.3 成功返回

成功时最少保证这些字段存在：

- `ok`
- `request_id`
- `run_id`
- `account_key`
- `report_date`
- `row_count`
- `status`

当前标准成功响应示例：

```json
{
  "ok": true,
  "request_id": "req_20260607_152528_0103b3db",
  "run_id": 7,
  "account_key": "a1",
  "report_date": "2026-05-14",
  "row_count": 0,
  "status": "accepted"
}
```

### 5.4 语义约定

- `ok=true` 且 `status=accepted`
  - 表示任务已成功提交
  - **不表示最终拉数已完成**

- `row_count`
  - 在 `fetch.php` 成功响应中当前固定视为 `0`
  - 中台不应使用它判断任务结果

- 同一 `account_key + report_date`
  - 当系统中已经存在 `pending` 或 `running` 的活跃任务时，重复触发应被拒绝
  - 当前实现会返回冲突响应，而不是再创建第二条并发中的同日任务

### 5.5 失败返回

失败时返回：

- `ok=false`
- `error_code`
- `message`
- 可能附带 `request_id`

中台不应从 `fetch.php` 的失败响应中推断业务状态，而应直接将其视为触发失败。

## 6. `report.php` 正式契约

### 6.1 接口地址

`GET /ke/report.php`

示例：

```text
https://api.example.com/ke/report.php?account_key=a1&report_date=2026-05-14&token=change-me
```

### 6.2 请求参数

参数与 `fetch.php` 保持一致：

- `account_key`
- `report_date`
- `token`

### 6.3 返回字段

`report.php` 成功返回时，正式字段定义为：

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

### 6.4 `items` 字段结构

`items` 是站点级结果数组。每个元素当前稳定包含：

- `site_name`
- `responses_served`
- `impressions`
- `clicks`
- `revenue`
- `ecpm`

示例：

```json
{
  "site_name": "jane.ghfkl.com",
  "responses_served": 34,
  "impressions": 33,
  "clicks": 4,
  "revenue": "7.646800",
  "ecpm": "231.721203"
}
```

## 7. 状态字段语义

## 7.1 `ok`

`ok` 表示接口层是否处理成功。

- `ok=true`
  - 表示接口成功处理了本次请求
  - **不等于业务已经成功拿到数据**

- `ok=false`
  - 表示接口本身失败，例如鉴权、参数或内部调用错误
  - 此时中台不应再解读业务状态字段

## 7.2 `has_run`

`has_run` 表示该账号该日期是否已经存在**成功结果快照**。

- `has_run=false`
  - 该日期当前没有可返回的成功结果
  - 可能是从未触发过，也可能是任务仍在执行，或最近一次执行失败且没有历史成功结果

- `has_run=true`
  - 该日期已经至少有一条成功 run，可返回其最新成功结果快照

## 7.3 `run_status`

`run_status` 在当前契约里表示**返回快照本身的状态**，而不是最新任务的实时执行状态。当前正式有效值为：

- `null`
- `success`

解释规则如下：

- `has_run=false` 且 `run_status=null`
  - 当前没有成功结果快照可返回

- `has_run=true` 且 `run_status=success`
  - 当前返回的是该日期最新成功 run 的结果快照

## 7.4 `row_count`

`row_count` 表示当前返回的最新成功结果快照里包含多少条站点结果。

解释规则：

- 只有 `has_run=true` 且 `run_status=success` 时，`row_count` 才具有业务意义
- `has_run=false` 时，`row_count=0` 只表示“当前没有成功结果快照”

因此：

- `has_run=true` 且 `row_count=0`
  - 存在成功结果快照，但该天无数据

- `has_run=true` 且 `row_count>0`
  - 存在成功结果快照，且有数据

## 7.5 `error_message`

`error_message` 在当前契约中固定用于占位，与 `report.php` 解耦失败态透传。

- 当前 `report.php` 只返回最新成功结果快照
- 因此该字段通常为 `null`
- 最新失败任务的错误信息不再通过 `report.php` 透传

## 7.6 `items`

`items` 表示当前返回的最新成功结果快照内容。

解释规则：

- `has_run=true` 且 `items` 非空
  - 存在成功结果快照，且有数据

- `has_run=true` 且 `items=[]`
  - 存在成功结果快照，但该天无数据

- `has_run=false`
  - `items=[]` 只表示当前没有成功结果快照

## 7.7 `request_id`

`request_id` 是当前这次 `report.php` 请求本身的请求号，用于排查链路问题。

它不是任务主键，也不是 `fetch.php` 触发那次请求的 `request_id`。

中台可以记录它用于日志，但不应将它作为业务主键依赖。

## 7.8 `run_id`

`run_id` 是任务级标识，代表该账号该日期对应的那次 run 记录。

在当前契约里，它表示**最新成功 run** 的 `run_id`。

如果中台需要关联这份返回结果，应优先依赖 `run_id`，而不是 `request_id`。

## 8. 中台标准调用顺序

中台标准流程建议固定为：

1. 调用 `fetch.php`
2. 当返回 `ok=true` 且 `status=accepted` 时，认为任务已提交
3. 等待数秒后开始轮询 `report.php`
4. 当 `has_run=true` 且 `run_status=success` 时，读取 `items`
5. 如果长时间 `has_run=false`，则视为还没有成功结果快照，可继续等待或转人工排查

## 8.1 推荐轮询策略

第一版推荐使用简单轮询：

- 触发后等待 `2-5` 秒再查询第一次
- 后续每 `3-5` 秒轮询一次
- 最长等待 `1-3` 分钟

当前链路任务较轻，一般不需要更复杂的回退策略。

## 8.2 中台推荐判断顺序

建议中台按下面顺序解释 `report.php`：

1. 先看 `ok`
2. 再看 `has_run`
3. 只有 `has_run=true` 且 `run_status=success` 时，再正式使用：
   - `row_count`
   - `items`

## 9. 字段稳定性约定

以下字段定义为当前可稳定依赖字段：

- `ok`
- `account_key`
- `report_date`
- `has_run`
- `run_status`
- `run_id`
- `row_count`
- `error_message`
- `items`
- `site_name`
- `responses_served`
- `impressions`
- `clicks`
- `revenue`
- `ecpm`

其中：

- `request_id`
  - 允许中台记录
  - 但不建议作为核心业务字段依赖

## 10. 当前适用边界

这份契约当前适用于：

- 单账号读取
- 单日期读取
- 站点级日报结果
- 轮询式中台接入

当前不承诺：

- 批量日期读取
- 批量账号读取
- 分页返回
- 游标式增量读取
- 多账号并发调度状态聚合
- 域名/API 版本协商机制

## 11. 推荐的中台解释示例

### 11.1 还没触发

```json
{
  "ok": true,
  "account_key": "a1",
  "report_date": "2026-05-14",
  "has_run": false,
  "run_status": null,
  "run_id": null,
  "row_count": 0,
  "error_message": null,
  "items": [],
  "request_id": "req_xxx"
}
```

中台解释：

- 这一天还没发起任务

### 11.2 已触发但还没有成功结果

```json
{
  "ok": true,
  "account_key": "a1",
  "report_date": "2026-05-14",
  "has_run": false,
  "run_status": null,
  "run_id": null,
  "row_count": 0,
  "error_message": null,
  "items": [],
  "request_id": "req_xxx"
}
```

中台解释：

- 任务可能仍在执行，也可能最近一次执行失败且还没有成功结果快照
- `report.php` 不负责区分这两种情况，只负责返回最新成功结果

### 11.3 成功且有数据

```json
{
  "ok": true,
  "account_key": "a1",
  "report_date": "2026-05-14",
  "has_run": true,
  "run_status": "success",
  "run_id": 7,
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
    }
  ],
  "request_id": "req_xxx"
}
```

中台解释：

- 可直接消费 `items`

### 11.4 成功但无数据

```json
{
  "ok": true,
  "account_key": "a1",
  "report_date": "2026-05-14",
  "has_run": true,
  "run_status": "success",
  "run_id": 7,
  "row_count": 0,
  "error_message": null,
  "items": [],
  "request_id": "req_xxx"
}
```

中台解释：

- 不是失败，而是业务空结果

### 11.5 执行失败

`report.php` 当前不再透传最新失败任务的错误信息。

如果某次 rerun 失败，但该日期已经存在更早的成功结果，则：

- `report.php` 仍然返回那份最新成功结果快照
- `run_id` 指向最新成功 run，而不是失败 run
- `error_message` 仍为 `null`

## 12. 后续演进方向

本次契约收口完成后，后续可以平滑扩展到：

- 中台专用只读接口
- 批量日期或批量账号读取
- 多账号代理/IP 状态聚合
- 更安全的 header/token 模式

但这些都不应改变当前 `report.php` 已经明确的基础字段语义。
