# VPS 公网触发异步化与 report 状态语义设计

日期：2026-06-07  
状态：Draft for review

## 1. 背景

当前线上链路已经验证通过：

- 真实 AdX 数据可以通过 VPS 上的 Python API 成功拉取并写入 MySQL
- `fetch.php` 可以通过 Cloudflare 公网入口触发拉数
- `report.php` 可以读取指定日期的数据结果

但现有实现还存在两个实际问题：

1. `fetch.php` 当前是同步等待真实拉数完成。放在 Cloudflare 前面时，容易出现“后台仍在执行，但公网请求先超时”的假失败。
2. `report.php` 当前只能返回数据本身，无法区分“从未触发过”“仍在执行中”“执行成功但 0 行”“执行失败”这几种状态。

用户明确要求：

- 先解决这两个问题
- 不新增新的公网接口
- 尽量不新增新的内部接口
- 以前期最快把系统做稳为第一优先级

## 2. 阶段目标

本次设计目标是：

**将公网 `fetch.php` 改成“接单即返回”的异步触发方式，避免 Cloudflare 长请求超时；同时扩充现有 `report.php` 的返回语义，让它在不新增接口的前提下承载任务状态判断。**

完成后，中台调用流程应变成：

1. 调 `fetch.php`
2. 立即收到“已受理”
3. 轮询 `report.php`
4. 通过 `report.php` 中的状态字段判断任务是否完成
5. 完成后直接从同一个 `report.php` 响应中拿数据

## 3. 范围

### 3.1 本次要做

1. 将 `fetch.php` 的语义从“同步执行”改成“异步入队”
2. 将 `POST /internal/fetch` 从“同步拉数”改成“创建 pending run 并立即返回 accepted”
3. 在现有 Python API 进程内增加一个轻量后台消费线程，轮询执行 `pending` run
4. 扩充 `report.php` 和现有内部读数逻辑的返回字段，使其能表达 run 状态
5. 保持现有公网接口数量不变：
   - `GET /ke/fetch.php`
   - `GET /ke/report.php`

### 3.2 本次不做

- 不新增独立公网状态接口
- 不新增独立内部状态接口
- 不新增第二个 worker 进程或第二个 systemd 服务
- 不新增数据库表
- 不修改 token 传递方式
- 不做多账号代理调度

## 4. 目标架构

改造后的结构仍然保持：

`Cloudflare -> 公网 PHP -> 127.0.0.1 Python API -> MySQL`

但内部执行语义变化如下：

### 4.1 公网 `fetch.php`

- 校验 `token`、`account_key`、`report_date`
- 调用现有 `POST /internal/fetch`
- 不再等待真实拉数完成
- 只返回“已受理”

### 4.2 Python 内部 `POST /internal/fetch`

- 校验账号是否存在
- 创建一条 `adx_fetch_runs` 记录，初始状态为 `pending`
- 返回：
  - `ok`
  - `request_id`
  - `run_id`
  - `account_key`
  - `report_date`
  - `status = accepted`

### 4.3 Python 进程内后台线程

- 在 FastAPI 进程启动后挂载一个轻量轮询线程
- 周期性扫描 `adx_fetch_runs` 中的 `pending`
- 抢占后改成 `running`
- 复用当前真实拉数逻辑执行
- 成功后改成 `success`
- 失败后改成 `failed`

### 4.4 公网 `report.php`

仍然只负责读取结果，但返回语义扩充为：

- 当前是否存在 run
- 当前 run 状态
- 是否有错误
- 当前是否有结果数据

这样它既是“数据接口”，也承担最小状态查询能力，但不额外拆接口。

## 5. 数据状态流

本次正式固定 `adx_fetch_runs.status` 的状态流：

- `pending`
- `running`
- `success`
- `failed`

状态变迁规则：

1. `fetch.php` 被调用后创建 `pending`
2. 后台线程抢占到任务后改成 `running`
3. 执行成功后改成 `success`
4. 执行异常后改成 `failed`

`row_count` 只在执行结束后可信：

- `success` 且 `row_count > 0`：成功且有数据
- `success` 且 `row_count = 0`：成功但业务空结果
- `failed`：失败，`error_message` 必填

## 6. 接口设计

### 6.1 公网触发接口

#### `GET /ke/fetch.php`

参数：

- `account_key`
- `report_date`
- `token`

成功返回：

```json
{
  "ok": true,
  "request_id": "req_xxx",
  "run_id": 12,
  "account_key": "a1",
  "report_date": "2026-05-14",
  "status": "accepted"
}
```

说明：

- 不再返回最终 `row_count`
- 不再返回最终 `success`
- 只表示系统已接受任务

失败返回：

```json
{
  "ok": false,
  "request_id": "req_xxx",
  "error_code": "REQUEST_ERROR",
  "message": "..."
}
```

### 6.2 公网读数接口

#### `GET /ke/report.php`

参数：

- `account_key`
- `report_date`
- `token`

成功返回统一增加这些字段：

- `has_run`
- `run_status`
- `run_id`
- `row_count`
- `error_message`
- `items`

状态语义如下：

#### 情况 1：从未触发过

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
  "items": []
}
```

#### 情况 2：已触发但仍在执行

```json
{
  "ok": true,
  "account_key": "a1",
  "report_date": "2026-05-14",
  "has_run": true,
  "run_status": "pending",
  "run_id": 12,
  "row_count": 0,
  "error_message": null,
  "items": []
}
```

或：

```json
{
  "ok": true,
  "account_key": "a1",
  "report_date": "2026-05-14",
  "has_run": true,
  "run_status": "running",
  "run_id": 12,
  "row_count": 0,
  "error_message": null,
  "items": []
}
```

#### 情况 3：执行成功且有数据

```json
{
  "ok": true,
  "account_key": "a1",
  "report_date": "2026-05-14",
  "has_run": true,
  "run_status": "success",
  "run_id": 12,
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
  ]
}
```

#### 情况 4：执行成功但 0 行

```json
{
  "ok": true,
  "account_key": "a1",
  "report_date": "2026-05-14",
  "has_run": true,
  "run_status": "success",
  "run_id": 12,
  "row_count": 0,
  "error_message": null,
  "items": []
}
```

#### 情况 5：执行失败

```json
{
  "ok": true,
  "account_key": "a1",
  "report_date": "2026-05-14",
  "has_run": true,
  "run_status": "failed",
  "run_id": 12,
  "row_count": 0,
  "error_message": "invalid_client ...",
  "items": []
}
```

### 6.3 内部接口

本次不新增新的 HTTP 路由数量，只调整现有职责：

#### `POST /internal/fetch`

由同步执行改成异步入队：

- 输入保持不变
- 输出改为 `accepted`

#### `GET /internal/reports/site-daily`

继续保留，但输出字段扩充为：

- `has_run`
- `run_status`
- `run_id`
- `row_count`
- `error_message`
- `items`

## 7. 代码边界

本次最小改造只涉及以下边界：

### 7.1 `collector/app/vps_repository.py`

补充最少量 run 队列方法：

- 创建 `pending` run
- 查询可执行的 `pending` run
- 抢占一条 `pending -> running`
- 更新 `success/failed`
- 查询指定账号指定日期的最近一条 run，不再只查 success

### 7.2 `collector/app/vps_service.py`

拆成两层职责：

- `enqueue_fetch(...)`
  - 创建 pending run 并返回 accepted 结果
- `execute_fetch_run(run_id)`
  - 真正执行拉数

同时调整读数结果对象，支持：

- `has_run`
- `run_status`
- `error_message`

### 7.3 `collector/app/vps_api.py`

- `POST /internal/fetch` 改成入队返回
- 增加后台轮询线程初始化逻辑
- `GET /internal/reports/site-daily` 扩充返回模型

### 7.4 `deploy/vps/php/fetch.php`

- 继续转发到 `POST /internal/fetch`
- 但不再假设返回的是最终执行结果
- 成功时只返回 `accepted`

### 7.5 `deploy/vps/php/report.php`

- 继续读取现有内部读数接口
- 但将状态字段原样透出

## 8. 错误处理

### 8.1 触发阶段错误

如果 `fetch.php` 参数不合法或 token 错误：

- 返回 `4xx`
- 不创建 run

### 8.2 入队阶段错误

如果账号不存在、配置缺失：

- 返回 `4xx/422`
- 不创建 run

### 8.3 执行阶段错误

如果后台线程真实拉数失败：

- `report.php` 不再需要靠空数据猜测
- 而是通过：
  - `has_run = true`
  - `run_status = failed`
  - `error_message = ...`
  直接体现

## 9. 成功标准

本次改造完成后，应满足：

1. `fetch.php` 在 Cloudflare 前面可以快速返回，不再依赖长时间同步等待
2. `POST /internal/fetch` 返回 `status = accepted`
3. 后台线程可以自动消费 `pending` run 并完成真实拉数
4. `report.php` 能明确区分：
   - 没跑过
   - 还在跑
   - 跑失败
   - 跑成功但 0 行
   - 跑成功且有数据
5. 不新增新的公网接口
6. 不新增新的数据库表

## 10. 风险与边界

### 10.1 本次接受的风险

- 仍然使用 URL query token
- 仍然由同一个 Python 进程同时承担 HTTP 服务和后台轮询

这是为了满足“前期最快把系统做稳”的目标。

### 10.2 后续可演进方向

本次设计完成后，后续可以平滑升级为：

- 独立 worker 进程
- 独立状态接口
- 多账号代理绑定
- 更安全的 header/token 方案

但这些都不应该阻塞当前这一轮最小改造。
