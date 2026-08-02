# 国家与广告单元维度明细报表实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 为 `user_system` 提供小时与权威日报的国家 × 广告单元明细报表，并返回填充率、点击率与展示率，且不改变任何既有聚合接口的契约。

**架构：** 小时报继续以现有带维度的小时事实表为来源；权威日报使用新的 Ad Manager 日报维度报表定义直接拉取并写入两张独立事实表。日报查询只读取权威维度事实表，不从小时数据伪造权威日报。所有比例在服务端对已聚合的原始计数计算，零分母按已确认的产品规则返回数值 `0.0000`。

**技术栈：** FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、SQLite、Google Ad Manager SOAP、pytest。

**已确认的不可变约束：**

- 覆盖率 = `responses_served / requests`；点击率 = `clicks / impressions`；曝光率 = `impressions / responses_served`；分母为 0 时为 `0.0000`。
- 国家稳定键为 `ad_country_code`，广告单元稳定键为 `ad_slot_id`；名称为可更新展示快照。
- 维度功能仅对上线后的数据生效，历史日期返回 HTTP 200、空 `items` 与 `dimension_data_available=false`。
- 旧 `account-daily` 与 `site-daily` 路径、行粒度、排序和返回字段均不修改。
- Google 真实拉取验证只能使用用户指定且获授权的测试账号与绑定代理；本计划的自动化测试不得调用 Google。

---

## 文件职责

- 创建 `backend/app/models/account_daily_dimension_report.py`：账号权威日报维度事实。
- 创建 `backend/app/models/site_daily_dimension_report.py`：站点权威日报维度事实。
- 创建 `backend/alembic/versions/20260802_0014_daily_dimension_reports.py`：新增表与查询索引。
- 修改 `collector/app/admanager_soap.py`：权威日报维度 SOAP 定义与 CSV 解析。
- 修改 `collector/app/adx_report_service.py`、`collector/app/fetcher.py`：将日报任务发送为 `admanager_daily_dimension_v1` 批次。
- 修改 `backend/app/collectors/ingestion_service.py`：按完整维度键幂等写入日报维度事实；绝不删除旧聚合日报。
- 修改 `backend/app/collectors/schemas.py`、`service.py`、`router.py`：新增四个独立维度查询 API（账号/站点 × 小时/日报）。
- 修改对应 `collector/tests/*` 与 `backend/tests/*`：覆盖解析、入库、比例、筛选、历史不可用和旧接口回归。

## 任务 1：定义持久化契约与迁移

- [ ] 先在 `backend/tests/test_models.py` 写失败测试，断言两张新表、唯一键、查询索引和原始指标列存在。
- [ ] 运行该测试，预期因表不存在失败。
- [ ] 创建两个 ORM 模型及 Alembic migration。两表都保存：归属标识、`report_date`、国家/广告单元键与名称、`source_kind='authoritative_daily'`、`currency`、原始指标、`coverage_hours`、`expected_hours`、`is_complete`、时间戳。
- [ ] 运行模型测试，预期通过。

## 任务 2：权威日报维度采集和入库

- [ ] 在 `collector/tests/test_admanager_soap.py` 写失败测试，要求 `DailyDimensionSoapReportDefinition` 请求 `DATE + SITE_NAME + COUNTRY_CODE + AD_UNIT_ID`，解析返回四维键和原始指标。
- [ ] 在 `collector/tests/test_fetcher.py` 写失败测试，要求 `report_fetch` 发出 `admanager_daily_dimension_v1`。
- [ ] 在 `backend/tests/test_ingestion_service.py` 写失败测试，要求同一账号、日期、站点、国家、广告单元可幂等替换；账号维度行按站点维度行聚合，且原 `site_daily_reports` / `account_daily_reports` 不被删除或改写。
- [ ] 运行上述测试，预期因类型/模式不存在失败。
- [ ] 实现 SOAP 定义、解析、fetcher 分派和 ingestion；缺失国家或广告单元值规范化为 `UNKNOWN`，不会丢弃原始计数；权威日报将 `coverage_hours=expected_hours` 且 `is_complete=true`。
- [ ] 运行上述测试，预期通过。

## 任务 3：独立维度查询 API 与比例口径

- [ ] 在 `backend/tests/test_collector_router.py` 写失败测试，覆盖四个新路径：
  - `/operator/mid-platform/reports/account-hourly-dimensions`
  - `/operator/mid-platform/reports/site-hourly-dimensions`
  - `/operator/mid-platform/reports/account-daily-dimensions`
  - `/operator/mid-platform/reports/site-daily-dimensions`
- [ ] 测试必须验证：国家/广告单元筛选、稳定排序、比率公式、零分母 `0.0`、维度上线日前 `dimension_data_available=false`、日报 `source_kind='authoritative_daily'` 与旧日报接口响应未变化。
- [ ] 运行测试，预期因路由和响应模型不存在失败。
- [ ] 实现 Pydantic 读模型、受限日期范围/分页参数、服务查询与路由。日接口不从小时表回退；小时接口读取既有小时维度事实表。
- [ ] 运行接口测试，预期通过。

## 任务 4：质量门禁、审阅与发布准备

- [ ] 运行 backend 与 collector 全量 pytest。
- [ ] 对完整 diff 做独立审阅；修复全部 Critical/Important 后复审。
- [ ] 更新 `docs/system-maintainer-onboarding-guide.md` 的变更记录（若该治理文档尚未合入基线，则将等价记录随本次文档提交纳入）。
- [ ] 提交代码、测试、migration、计划与变更记录至 Git，推送分支；不得部署。
- [ ] 在用户提供测试账号标识与代理标识后，进行一次受控 Google 拉取并核对任务、batch、两张维度日报表和新 API；未提供前不得执行真实 Google 测试或部署。

## 审阅整改（阻塞提交）

1. `report_fetch` 必须保留 `admanager_site_core_v1`，同时产生独立 `admanager_daily_dimension_v1` 批次；后端分别投影，旧聚合日报持续更新。
2. 维度日报首个完整快照批次必须先按 `account_id + report_date + source_kind` 清空两张维度表，再写入新快照；后续分页批次必须在明确完成边界后才可替换可见快照。
3. 新 API 必须补齐国家、广告单元、站点筛选、分页、上线日期边界、小时时间字段与 DST 覆盖状态；每项均有红绿测试。

## 实施状态（2026-08-02）

- [x] 持久化模型、迁移、唯一键和查询索引已实现，并与 Alembic 一致。
- [x] 核心日报链和权威维度日报链并存；维度快照按 schema 首批清理，且不会影响既有日报或小时汇总。
- [x] 四个维度 API 已实现：单日或最长 31 天日期范围、筛选、稳定数据库分页、上线数据边界、小时 UTC/源时区与三项比率。
- [x] 已完成 TDD 回归、后端 141 项与采集端 89 项测试、`git diff --check`，并经第四轮独立审阅通过。
- [ ] 尚未提交、合并、部署或进行真实 Google 拉取；真实拉取仍需要用户明确指定测试账号与代理标识。
